"""固定時間可注入的模擬來源；絕不連線或發送真 Telegram。"""
from __future__ import annotations

import calendar
import hashlib
from datetime import date, datetime, timedelta, timezone

from .dates import google_url
from .models import Offer
from .sources.serpapi_flights import Insights, SearchResult


# 各航線示範價的倍率（東京較貴）；未列者視為 1。
SCALE = {"TYO": 1.6}


def make_sources(now: datetime, cfg: dict):
    at = now.isoformat(timespec="seconds")
    # SerpApi 收到的是 arrival_id（可能是 "NRT,HND"），Travelpayouts 收到 destination；兩者都對回航線。
    by_code = {code: route for route in cfg["routes"] if not route.get("return_origin") for code in (route["destination"], route["serpapi_arrival"])}

    def flight(route: dict, code: str, outbound: str, inbound: str) -> dict:
        """示範用的班次資料（時間為當地時間；只為了讓預覽畫面完整，不是真實班表）。"""
        seed = int(hashlib.sha256(f"{route['id']}{code}{outbound}".encode()).hexdigest()[:6], 16)
        minutes = {"HKG": 125, "TYO": 185, "MFM": 150}.get(route["id"], 150)
        depart = datetime.fromisoformat(f"{outbound}T{6 + seed % 14:02d}:{(seed // 7 % 12) * 5:02d}:00+08:00")
        offset = 9 if route["id"] == "TYO" else 8
        arrive = (depart + timedelta(minutes=minutes)).astimezone(timezone(timedelta(hours=offset)))
        airport = {"HKG": "HKG", "TYO": "NRT", "MFM": "MFM"}.get(route["id"], route["destination"])
        return {"airline_code": code, "flight_no": f"{code} {100 + seed % 800}", "depart_time": depart.strftime("%H:%M"),
                "arrive_time": arrive.strftime("%H:%M"), "return_depart_time": f"{12 + seed % 10:02d}:{(seed // 3 % 12) * 5:02d}",
                "origin_airport": route["origin"], "destination_airport": airport, "duration_to": minutes, "duration_back": minutes + 15}

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
        offers = [Offer("serpapi", outbound, inbound, value, currency, airlines[index], True, url, at, **flight(route, codes[index], outbound, inbound)),
                  Offer("serpapi", outbound, inbound, value + 1800, currency, "長榮航空", True, url, at, **flight(route, "BR", outbound, inbound))]
        history = [[int((now - timedelta(days=10 - i)).timestamp()), value + (10 - i) * 180] for i in range(11)]
        scale = SCALE.get(route["id"], 1)
        return SearchResult(offers, Insights(value, "low" if value < 7200 * scale else "typical", 7200 * scale, 10000 * scale, history), url, 2)

    def tp(origin, destination, month, token, currency="TWD", direct_only=True, one_way=False):
        route = by_code[origin if destination == "TPE" else destination]
        year, month_number = map(int, month.split("-"))
        offers = []
        for day in range(1, calendar.monthrange(year, month_number)[1] + 1):
            out = date(year, month_number, day)
            if one_way:
                day_text = out.isoformat()
                details = flight(route, "IT", day_text, day_text)
                details.update(origin_airport=origin, destination_airport=destination)
                offers.append(Offer("travelpayouts", day_text, day_text, price(route["id"], day_text, day_text) / 2,
                                    currency, "台灣虎航", True, "https://www.aviasales.com", at, **details))
                continue
            for nights in route["stay_nights"]:
                back = out + timedelta(days=nights)
                if (day + nights) % 4 == 0:
                    continue
                offers.append(Offer("travelpayouts", out.isoformat(), back.isoformat(), price(route["id"], out.isoformat(), back.isoformat()),
                                    currency, "台灣虎航", True, "https://www.aviasales.com", at,
                                    **flight(route, "IT", out.isoformat(), back.isoformat())))
        return offers
    return serp, tp
