from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date


def number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError):
        return None


@dataclass
class Offer:
    source: str
    outbound: str
    inbound: str
    price: float
    currency: str
    airline: str = ""
    direct: bool = True
    url: str = ""
    observed_at: str = ""
    route_id: str = ""
    airline_code: str | None = None
    # 判斷用的 price 是「總價」（票價＋行李費）；來源回傳的原票價由 scanner 蓋章時存進 fare。
    fare: float | None = None
    bag_fee: float = 0.0
    bag_estimated: bool = False

    @property
    def total(self) -> float:
        return self.price

    @property
    def pair_key(self) -> str:
        return f"{self.route_id}:{self.outbound}_{self.inbound}"

    @property
    def nights(self) -> int:
        return (date.fromisoformat(self.inbound) - date.fromisoformat(self.outbound)).days

    def to_dict(self) -> dict:
        return {**asdict(self), "pair_key": self.pair_key, "nights": self.nights}
