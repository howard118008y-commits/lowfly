from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from .dates import parse_time
from .models import number


@dataclass
class Baseline:
    value: float
    google_typical: float | None
    google_low: float | None
    google_high: float | None
    own_history: float | None
    social: float | None
    n_ranges: int
    n_own: int
    source: str = "google"   # google：Google 典型區間；travelpayouts：該航線 TP 價格中位數

    def ratio(self, price: float) -> float:
        # price 一律是含行李的總價。Google typical 視為已含行李的總價近似（傳統航空為主）。
        return price / self.value


MIN_TP_PAIRS = 15


def _tp_samples(state: dict, route_id: str, now: datetime, cutoff: datetime) -> list[float]:
    return [float(s["price"]) for s in state.get("tp_samples", {}).values()
            if s.get("route") == route_id and s.get("basis") == "total" and number(s.get("price"))
            and cutoff <= parse_time(s["at"]) <= now]


def tp_sample_count(state: dict, cfg: dict, now: datetime, route_id: str) -> int:
    """前端顯示「基準累積中 n/15」用：該航線回看期內 basis=total 的樣本數。"""
    return len(_tp_samples(state, route_id, now, now - timedelta(days=int(cfg["baseline"]["lookback_days"]))))


def tp_average(state: dict, cfg: dict, now: datetime, route_id: str) -> dict:
    """票根「近 N 天均價」：該航線近 average_days 天樣本（含行李總價）的平均，沒有樣本時 value 為 None。"""
    days = int(cfg["baseline"].get("average_days", 30))
    prices = _tp_samples(state, route_id, now, now - timedelta(days=days))
    return {"value": round(sum(prices) / len(prices)) if prices else None, "samples": len(prices), "days": days}


def _travelpayouts_median(state: dict, bc: dict, now: datetime, route_id: str, cutoff: datetime):
    """該航線回看期內累積的 TP 樣本（含行李總價，每組日期每天一筆）中位數；不足 15 筆則不成立。
    沒有 basis="total" 的舊樣本（只含票價）不可與總價混算，直接忽略。"""
    prices = _tp_samples(state, route_id, now, cutoff)
    return (median(prices), len(prices)) if len(prices) >= MIN_TP_PAIRS else None


def compute_baseline(state: dict, cfg: dict, now: datetime, route_id: str,
                     social_value: float | None = None) -> Baseline | None:
    bc = cfg["baseline"]
    cutoff = now - timedelta(days=int(bc["lookback_days"]))
    ranges = [r for r in state.get("typical_ranges", [])
              if r.get("route") == route_id and number(r.get("low")) and number(r.get("high")) and r["low"] <= r["high"]
              and cutoff <= parse_time(r["at"]) <= now]
    if len(ranges) < int(bc.get("min_observations", 1)):
        ranges = []
    low = median(float(r["low"]) for r in ranges) if ranges else None
    high = median(float(r["high"]) for r in ranges) if ranges else None
    google = {"low": low, "high": high, "mid": (low + high) / 2 if ranges else None}[bc["google_stat"]]
    own_prices = [float(p["last_price"]) for key, p in state.get("pairs", {}).items()
                  if key.startswith(f"{route_id}:") and number(p.get("last_price")) and p.get("last_source") == "serpapi"
                  and p.get("last_serpapi") and cutoff <= parse_time(p["last_serpapi"]) <= now]
    own = median(own_prices) if own_prices else None
    components = {"google_typical": google, "own_history": own, "social": number(social_value)}
    usable = [(v, float(bc["weights"].get(k, 0))) for k, v in components.items()
              if v is not None and float(bc["weights"].get(k, 0)) > 0]
    if google is None:
        tp = _travelpayouts_median(state, bc, now, route_id, cutoff)
        if tp is not None:
            return Baseline(tp[0], None, None, None, own, components["social"], 0, len(own_prices), "travelpayouts")
    if not usable:
        return None
    value = sum(v * w for v, w in usable) / sum(w for _, w in usable)
    return Baseline(value, google, low, high, own, components["social"], len(ranges), len(own_prices))
