from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from ..models import Offer, number

API = "https://serpapi.com/search.json"
log = logging.getLogger(__name__)


@dataclass
class Insights:
    lowest_price: float | None
    price_level: str | None
    typical_low: float | None
    typical_high: float | None
    price_history: list = field(default_factory=list)

    @property
    def has_range(self) -> bool:
        return bool(number(self.typical_low) and number(self.typical_high) and self.typical_low <= self.typical_high)


@dataclass
class SearchResult:
    offers: list[Offer]
    insights: Insights | None
    url: str
    raw_count: int


class SerpApiError(RuntimeError):
    pass


def search_round_trip(origin: str, destination: str, outbound: str, inbound: str, api_key: str,
                      currency: str = "TWD", direct_only: bool = True, adults: int = 1,
                      timeout: int = 60) -> SearchResult:
    params = {"engine": "google_flights", "departure_id": origin, "arrival_id": destination,
              "outbound_date": outbound, "return_date": inbound, "type": 1, "currency": currency,
              "hl": "zh-tw", "gl": "tw", "adults": adults, "stops": 1 if direct_only else 0, "api_key": api_key}
    try:
        response = requests.get(API, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        # 不輸出 requests 例外原文，避免含 api_key 的 URL 出現在 log。
        raise SerpApiError(f"連線或 JSON 失敗（{type(exc).__name__}）") from None
    if not isinstance(data, dict) or "error" in data:
        raise SerpApiError("來源回報錯誤／額度用盡；本次停止後續精查")
    url = (data.get("search_metadata") or {}).get("google_flights_url", "")
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    flights = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    offers = []
    for flight in flights:
        price = number(flight.get("price"))
        legs = flight.get("flights") or []
        direct = len(legs) == 1
        if price is None or (direct_only and not direct):
            continue
        offers.append(Offer("serpapi", outbound, inbound, price, currency,
                            legs[0].get("airline", "") if legs else "", direct, url, at))
    pi = data.get("price_insights")
    insights = None
    if isinstance(pi, dict):
        rng = pi.get("typical_price_range") or []
        insights = Insights(number(pi.get("lowest_price")), pi.get("price_level"),
                            number(rng[0]) if len(rng) > 0 else None,
                            number(rng[1]) if len(rng) > 1 else None, pi.get("price_history") or [])
    log.info("SerpAPI %s→%s：%d 筆；typical_price_range=%s（來回總價）", outbound, inbound,
             len(offers), (insights.typical_low, insights.typical_high) if insights else None)
    return SearchResult(offers, insights, url, len(flights))
