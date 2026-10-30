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

    @property
    def pair_key(self) -> str:
        return f"{self.outbound}_{self.inbound}"

    @property
    def nights(self) -> int:
        return (date.fromisoformat(self.inbound) - date.fromisoformat(self.outbound)).days

    def to_dict(self) -> dict:
        return {**asdict(self), "pair_key": self.pair_key, "nights": self.nights}
