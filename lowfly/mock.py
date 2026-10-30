"""固定時間可注入的模擬來源；絕不連線或發送真 Telegram。"""
from __future__ import annotations

import calendar
import hashlib
from datetime import date, datetime, timedelta

from .dates import google_url
from .models import Offer
from .sources.serpapi_flights import Insights, SearchResult


def make_sources(now: datetime, cfg: dict):
    at = now.isoformat(timespec="seconds")
    def price(outbound: str, inbound: str) -> float:
        lead = (date.fromisoformat(outbound) - now.date()).days
        seed = int(hashlib.sha256(f"{outbound}_{inbound}".encode()).hexdigest()[:8], 16)
        if lead in (9, 23):
            return 3980.0
        if lead in (5, 12, 17):
            return 5200.0 + seed % 700
        return 7600.0 + seed % 4100

    def serp(origin, destination, outbound, inbound, key, currency="TWD", direct_only=True, adults=1):
        value = price(outbound, inbound)
        url = google_url(cfg, outbound, inbound)
        airlines = ["台灣虎航", "長榮航空", "澳門航空", "星宇航空"]
        airline = airlines[date.fromisoformat(outbound).day % 4]
        offers = [Offer("serpapi", outbound, inbound, value, currency, airline, True, url, at),
                  Offer("serpapi", outbound, inbound, value + 1800, currency, "長榮航空", True, url, at)]
        history = [[int((now - timedelta(days=10 - i)).timestamp()), value + (10 - i) * 180] for i in range(11)]
        return SearchResult(offers, Insights(value, "low" if value < 7200 else "typical", 7200, 10000, history), url, 2)

    def tp(origin, destination, month, token, currency="TWD", direct_only=True):
        year, month_number = map(int, month.split("-"))
        offers = []
        for day in range(1, calendar.monthrange(year, month_number)[1] + 1):
            out = date(year, month_number, day)
            for nights in cfg["window"]["stay_nights"]:
                back = out + timedelta(days=nights)
                if (day + nights) % 4 == 0:
                    continue
                offers.append(Offer("travelpayouts", out.isoformat(), back.isoformat(), price(out.isoformat(), back.isoformat()),
                                    currency, "台灣虎航", True, "https://www.aviasales.com", at))
        return offers
    return serp, tp
