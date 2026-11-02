"""優惠須知：航空公司規則與深夜抵達提醒。內容全部來自 config.yaml 的 notices，推播與前端共用同一份。"""
from __future__ import annotations


def deal_notes(cfg: dict, airline_code: str | None, destination_airport: str | None, arrive_time: str | None) -> list[str]:
    notices = cfg.get("notices") or {}
    notes = [str(text) for text in (notices.get("airlines") or {}).get((airline_code or "").upper(), [])]
    late = (notices.get("late_arrival") or {}).get((destination_airport or "").upper())
    # 時間皆為當地 "HH:MM"，字串比較即時間比較；05:00 前抵達也算深夜。
    if late and arrive_time and (arrive_time >= str(late["after"]) or arrive_time < "05:00"):
        notes.append(f"{arrive_time} {late['text']}")
    return notes


def good_price(route: dict) -> float | None:
    """航線的社群好價線（含行李總價）；沒設定回傳 None。"""
    value = route.get("good_price_twd")
    return float(value) if value else None
