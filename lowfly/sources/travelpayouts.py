from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests

from ..models import Offer, number

API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AIRLINE_ZH = {"UO": "香港快運", "TR": "酷航", "MM": "樂桃航空", "GK": "捷星日本", "IT": "台灣虎航", "HB": "大灣區航空",
              "HX": "香港航空", "CX": "國泰航空", "ZG": "ZIPAIR", "JL": "日本航空", "NH": "全日空", "NX": "澳門航空",
              "BR": "長榮航空", "CI": "中華航空", "JX": "星宇航空"}
# 機場所在地的 UTC 偏移（小時），用來把抵達時間換成當地時間；表外的機場不推算抵達時間。
AIRPORT_UTC_OFFSET = {"TPE": 8, "TSA": 8, "HKG": 8, "MFM": 8, "NRT": 9, "HND": 9}
log = logging.getLogger(__name__)
RETRY_STATUS = (429, 500, 502, 503, 504)
RETRY_WAIT = (2, 5)   # 秒；網路錯誤或 429／5xx 時重試兩次


def _hhmm(value) -> str | None:
    try:
        return datetime.fromisoformat(str(value)).strftime("%H:%M")
    except ValueError:
        return None


def _minutes(value) -> int | None:
    n = number(value)
    return int(n) if n else None


def _arrival_time(departure_at, minutes: int | None, airport: str | None) -> str | None:
    offset = AIRPORT_UTC_OFFSET.get(airport or "")
    if offset is None or not minutes:
        return None
    try:
        arrive = datetime.fromisoformat(str(departure_at)) + timedelta(minutes=minutes)
    except ValueError:
        return None
    if arrive.tzinfo is None:
        return None
    return arrive.astimezone(timezone(timedelta(hours=offset))).strftime("%H:%M")


def fetch_month(origin: str, destination: str, month: str, token: str, currency: str = "TWD",
                direct_only: bool = True, timeout: int = 30, one_way: bool = False) -> list[Offer]:
    """one_way=True 時回傳單程（inbound 與 outbound 同一天，只給 scanner 拼接用）。"""
    params = {"origin": origin, "destination": destination, "departure_at": month, "one_way": "true" if one_way else "false",
              "direct": "true" if direct_only else "false", "currency": currency.lower(), "sorting": "price",
              "unique": "false", "limit": 1000, "page": 1, "token": token}
    try:
        for wait in (*RETRY_WAIT, None):
            try:
                response = requests.get(API, params=params, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout):
                if wait is None:
                    raise
            else:
                if response.status_code not in RETRY_STATUS or wait is None:
                    break
            time.sleep(wait)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("success") is not True or not isinstance(data.get("data"), list):
            raise ValueError("來源回報失敗")
    except (requests.RequestException, ValueError) as exc:
        log.warning("Travelpayouts %s 失敗（%s）；退回空清單", month, type(exc).__name__)
        return []
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    offers = []
    for row in data["data"]:
        price = number(row.get("price"))
        out, back = str(row.get("departure_at") or "")[:10], str(row.get("return_at") or "")[:10]
        if one_way:
            back = out
        # 缺少任一方向的轉機資訊時，不宣稱已確認直飛。
        direct = row.get("transfers") == 0 and (one_way or row.get("return_transfers") == 0)
        if not out or not back or price is None or (direct_only and not direct):
            continue
        try:
            if not one_way and datetime.fromisoformat(back) <= datetime.fromisoformat(out):
                continue
        except ValueError:
            continue
        link = urljoin("https://www.aviasales.com", row.get("link") or "")
        if urlparse(link).scheme != "https" or urlparse(link).hostname != "www.aviasales.com":
            link = "https://www.aviasales.com"
        code = str(row.get("airline") or "").upper()
        number_text = str(row.get("flight_number") or "").strip()
        destination_airport = str(row.get("destination_airport") or "").upper() or None
        duration_to = _minutes(row.get("duration_to"))
        offers.append(Offer("travelpayouts", out, back, price, currency, AIRLINE_ZH.get(code, code), direct, link, at,
                            airline_code=code or None,
                            flight_no=f"{code} {number_text}" if code and number_text else None,
                            depart_time=_hhmm(row.get("departure_at")),
                            arrive_time=_arrival_time(row.get("departure_at"), duration_to, destination_airport),
                            return_depart_time=_hhmm(row.get("return_at")),
                            origin_airport=str(row.get("origin_airport") or "").upper() or None,
                            destination_airport=destination_airport,
                            duration_to=duration_to, duration_back=_minutes(row.get("duration_back"))))
    return offers
