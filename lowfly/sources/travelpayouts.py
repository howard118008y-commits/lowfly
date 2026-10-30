from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

from ..models import Offer, number

API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AIRLINE_ZH = {"BR": "長榮航空", "NX": "澳門航空", "IT": "台灣虎航", "JX": "星宇航空", "CI": "中華航空"}
log = logging.getLogger(__name__)


def fetch_month(origin: str, destination: str, month: str, token: str, currency: str = "TWD",
                direct_only: bool = True, timeout: int = 30) -> list[Offer]:
    params = {"origin": origin, "destination": destination, "departure_at": month, "one_way": "false",
              "direct": "true" if direct_only else "false", "currency": currency.lower(), "sorting": "price",
              "unique": "false", "limit": 1000, "page": 1, "token": token}
    try:
        response = requests.get(API, params=params, timeout=timeout)
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
        # 缺少任一方向的轉機資訊時，不宣稱已確認直飛。
        direct = row.get("transfers") == 0 and row.get("return_transfers") == 0
        if not out or not back or price is None or (direct_only and not direct):
            continue
        try:
            if datetime.fromisoformat(back) <= datetime.fromisoformat(out):
                continue
        except ValueError:
            continue
        link = urljoin("https://www.aviasales.com", row.get("link") or "")
        if urlparse(link).scheme != "https" or urlparse(link).hostname != "www.aviasales.com":
            link = "https://www.aviasales.com"
        code = str(row.get("airline") or "").upper()
        offers.append(Offer("travelpayouts", out, back, price, currency, AIRLINE_ZH.get(code, code), direct, link, at))
    return offers
