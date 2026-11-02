"""固定時間可注入的模擬來源；絕不連線或發送真 Telegram。"""
from __future__ import annotations

import calendar
import hashlib
from datetime import date, datetime, timedelta

from .dates import google_url
from .models import Offer
from .sources.serpapi_flights import Insights, SearchResult


# 各航線示範價的倍率（東京較貴）；未列者視為 1。
SCALE = {"TYO": 1.6}


def make_sources(now: datetime, cfg: dict):
    at = now.isoformat(timespec="seconds")
    # SerpApi 收到的是 arrival_id（可能是 "NRT,HND"），Travelpayouts 收到 destination；兩者都對回航線。
    by_code = {code: route for route in cfg["routes"] for code in (route["destination"], route["serpapi_arrival"])}

    def price(route_id: str, outbound: str, inbound: str) -> float:
        lead = (date.fromisoformat(outbound) - now.date()).days
        seed = int(hashlib.sha256(f"{route_id}_{outbound}_{inbound}".encode()).hexdigest()[:8], 16)
        if lead in (9, 23):
            base = 3980.0
        elif lead in (5, 12, 17):
            base = 5200.0 + seed % 700
        else:
            base = 7600.0 + seed % 4100
        return round(base * SCALE.get(route_id, 1))

    def serp(origin, destination, outbound, inbound, key, currency="TWD", direct_only=True, adults=1):
        route = by_code[destination]
        value = price(route["id"], outbound, inbound)
        url = google_url(cfg, route, outbound, inbound)
        airlines = ["台灣虎航", "長榮航空", "澳門航空", "星宇航空"]
        codes = ["IT", "BR", "NX", "JX"]
        index = date.fromisoformat(outbound).day % 4
        offers = [Offer("serpapi", outbound, inbound, value, currency, airlines[index], True, url, at, airline_code=codes[index]),
                  Offer("serpapi", outbound, inbound, value + 1800, currency, "長榮航空", True, url, at, airline_code="BR")]
        history = [[int((now - timedelta(days=10 - i)).timestamp()), value + (10 - i) * 180] for i in range(11)]
        scale = SCALE.get(route["id"], 1)
        return SearchResult(offers, Insights(value, "low" if value < 7200 * scale else "typical", 7200 * scale, 10000 * scale, history), url, 2)

    def tp(origin, destination, month, token, currency="TWD", direct_only=True):
        route = by_code[destination]
        year, month_number = map(int, month.split("-"))
        offers = []
        for day in range(1, calendar.monthrange(year, month_number)[1] + 1):
            out = date(year, month_number, day)
            for nights in route["stay_nights"]:
                back = out + timedelta(days=nights)
                if (day + nights) % 4 == 0:
                    continue
                offers.append(Offer("travelpayouts", out.isoformat(), back.isoformat(), price(route["id"], out.isoformat(), back.isoformat()),
                                    currency, "台灣虎航", True, "https://www.aviasales.com", at, airline_code="IT"))
        return offers
    return serp, tp
