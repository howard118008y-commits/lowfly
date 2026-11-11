from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

WEEKDAY_ZH = "一二三四五六日"


def now_local(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def date_pairs(today: date, days_ahead: int, min_lead_days: int, stay_nights: list[int]) -> list[tuple[date, date]]:
    return [(today + timedelta(days=lead), today + timedelta(days=lead + nights))
            for lead in range(min_lead_days, days_ahead + 1) for nights in stay_nights]


def months_covering(pairs: list[tuple[date, date]]) -> list[str]:
    return sorted({out.strftime("%Y-%m") for out, _ in pairs})


def pair_key(route_id: str, out: date, back: date) -> str:
    return f"{route_id}:{out.isoformat()}_{back.isoformat()}"


def split_key(key: str) -> tuple[str, str, str]:
    """pair key -> (route_id, outbound, inbound)。"""
    route_id, dates = key.split(":", 1)
    out, back = dates.split("_")
    return route_id, out, back


def fmt_date(value: str | date) -> str:
    d = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{d.month}/{d.day}（{WEEKDAY_ZH[d.weekday()]}）"


def google_url(cfg: dict, route: dict, outbound: str, inbound: str) -> str:
    query = f"Round trip flights {route['origin']} to {route['destination']} {outbound} return {inbound} nonstop {route['adults']} adult"
    if route.get("return_origin"):
        query = (f"Multi-city flights {route['origin']} to {route['destination']} {outbound}, "
                 f"{route['return_origin']} to {route['origin']} {inbound}, nonstop {route['adults']} adult")
    return "https://www.google.com/travel/flights?" + urlencode({"q": query, "curr": cfg["currency"], "hl": "zh-TW"})
