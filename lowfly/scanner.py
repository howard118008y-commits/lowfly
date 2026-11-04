"""可注入來源的漏斗掃描器；不負責檔案持久化。"""
from __future__ import annotations

import logging
import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from .baggage import bag_fee, bag_line
from .baseline import Baseline, compute_baseline
from .config import ROOT, runs_per_day
from .dates import date_pairs, fmt_date, google_url, months_covering, pair_key, parse_time, split_key
from .models import Offer, number
from .notices import deal_notes, good_price
from .notifier import Telegram, esc, fmt_money, fmt_pct, fmt_range, link
from .sources import airline_sales, serpapi_flights, travelpayouts
from .state import prune_typical_ranges
from .team_report import build_team_report

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, cfg: dict, secrets, state: dict, tg: Telegram, now_local: datetime,
                 serpapi_fn=None, tp_fn=None, force_digest: bool = False,
                 output_dir: Path | None = None, render_images: bool = True, sales_fn=None):
        self.cfg, self.secrets, self.state, self.tg, self.now = cfg, secrets, state, tg, now_local
        self.serpapi_fn = serpapi_fn or serpapi_flights.search_round_trip
        self.tp_fn = tp_fn or travelpayouts.fetch_month
        self.sales_fn = sales_fn or airline_sales.fetch
        self.force_digest = force_digest
        self.output_dir = Path(output_dir or ROOT / "out")
        self.render_images = render_images
        self.routes = {route["id"]: route for route in cfg["routes"]}
        self.history_rows: list[dict] = []
        self.route_lows: dict[str, dict] = {}
        self.summary = {"instant_alerts": 0, "digest_sent": False, "serpapi_calls": 0,
                        "tp_offers": 0, "candidates": [], "errors": []}

    def run(self) -> dict:
        st, cfg = self.state, self.cfg
        win = cfg["window"]
        route_pairs = {rid: date_pairs(self.now.date(), int(win["days_ahead"]), int(win["min_lead_days"]), route["stay_nights"])
                       for rid, route in self.routes.items()}
        keys = [pair_key(rid, o, b) for rid, pairs in route_pairs.items() for o, b in pairs]
        self.summary["pair_keys"] = keys
        self._rollover_budgets()
        # SerpApi 不可用（無 key、enabled false 或額度 0）時，改以 Travelpayouts 快取價判斷。
        self.tp_only = self._run_budget() == 0
        self.summary["tp_only"] = self.tp_only
        self._prune_pairs()
        tp_best: dict[str, Offer] = {}
        if cfg["sources"]["travelpayouts"].get("enabled", True) and self.secrets.travelpayouts_token:
            for rid, route in self.routes.items():
                for month in months_covering(route_pairs[rid]):
                    try:
                        offers = self.tp_fn(route["origin"], route["destination"], month,
                                            self.secrets.travelpayouts_token, cfg["currency"], route["direct_only"])
                        for offer in (self._stamp(o, rid) for o in offers):
                            if self._valid_offer(offer) and offer.pair_key in keys:
                                if offer.pair_key not in tp_best or offer.price < tp_best[offer.pair_key].price:
                                    tp_best[offer.pair_key] = offer
                    except Exception as exc:
                        self._error(f"Travelpayouts {rid} {month} 失敗（{type(exc).__name__}）")
            if cfg["sources"]["travelpayouts"].get("one_way"):
                self._splice_one_way(route_pairs, tp_best)
        self.summary["tp_offers"] = len(tp_best)
        self._record_tp(tp_best)
        self._refresh_market()
        baselines = self._baselines()
        selected = self._select_pairs(keys, tp_best, baselines)
        self.summary["candidates"] = selected
        verified, checked = {}, set()
        for key in selected:
            result = self._serpapi(key)
            if result is None:
                break
            checked.add(key)
            result.offers = [o for o in (self._stamp(o, split_key(key)[0]) for o in result.offers)
                             if self._valid_offer(o) and o.pair_key == key]
            self._record_serpapi(key, result)
            if result.offers:
                verified[key] = min(result.offers, key=lambda o: o.price)
        prune_typical_ranges(st)
        baselines = self._baselines()
        self.summary["baseline"] = {rid: b.value if b else None for rid, b in baselines.items()}
        self._evaluate(verified, tp_best, baselines, checked)
        self._check_sales()
        self._maybe_digest(baselines, tp_best)
        self._maybe_team_report(tp_best)
        st["stats"]["runs"] += 1
        st["last_run_at"] = self.now.isoformat(timespec="seconds")
        st["last_tp_count"] = len(tp_best)
        return self.summary

    def _stamp(self, offer: Offer, route_id: str) -> Offer:
        """蓋上航線並加計行李：price 變成總價（之後所有判斷都用它），原票價留在 fare。"""
        fee, estimated = bag_fee(self.cfg, route_id, offer.airline_code)
        return replace(offer, route_id=route_id, fare=offer.price, price=offer.price + fee, bag_fee=fee, bag_estimated=estimated)

    def _refresh_market(self) -> None:
        """行情：未來 months_ahead 個月出發的 TP 快取價，依出發月份彙整（含行李總價與票價），每天抓一次。
        任一次請求失敗就保留舊資料、不記日期，下一輪重抓。"""
        months_ahead = int((self.cfg.get("market") or {}).get("months_ahead", 0))
        today = self.now.date()
        if (not months_ahead or (self.state.get("market") or {}).get("date") == today.isoformat()
                or not self.cfg["sources"]["travelpayouts"].get("enabled", True) or not self.secrets.travelpayouts_token):
            return
        months = [f"{today.year + (today.month - 1 + i) // 12}-{(today.month - 1 + i) % 12 + 1:02d}" for i in range(months_ahead)]
        routes = {}
        for rid, route in self.routes.items():
            routes[rid] = {}
            for month in months:
                try:
                    offers = self.tp_fn(route["origin"], route["destination"], month,
                                        self.secrets.travelpayouts_token, self.cfg["currency"], route["direct_only"])
                except Exception as exc:
                    self._error(f"行情 Travelpayouts {rid} {month} 失敗（{type(exc).__name__}）；保留舊行情")
                    return
                best: dict[str, Offer] = {}
                for offer in (self._stamp(o, rid) for o in offers):
                    if (self._valid_offer(offer) and offer.outbound.startswith(month) and offer.outbound >= today.isoformat()
                            and offer.nights in route["stay_nights"]
                            and (offer.pair_key not in best or offer.price < best[offer.pair_key].price)):
                        best[offer.pair_key] = offer
                if best:
                    routes[rid][month] = {"n": len(best), "sum": sum(o.price for o in best.values()),
                                          "fare_sum": sum(o.fare for o in best.values()), "min": min(o.price for o in best.values())}
        self.state["market"] = {"date": today.isoformat(), "at": self.now.isoformat(timespec="seconds"),
                                "months": months, "routes": routes}

    def _splice_one_way(self, route_pairs: dict, tp_best: dict[str, Offer]) -> None:
        """兩張單程拼來回：去程、回程各取每天最低價；比來回快取便宜（或來回沒有）就採用。廉航來回本來就是兩段相加。"""
        for rid, route in self.routes.items():
            legs: dict[str, dict[str, Offer]] = {"out": {}, "back": {}}
            for direction, origin, destination, days in (
                    ("out", route["origin"], route["destination"], [o for o, _ in route_pairs[rid]]),
                    ("back", route["destination"], route["origin"], [b for _, b in route_pairs[rid]])):
                best = legs[direction]
                for month in sorted({day.strftime("%Y-%m") for day in days}):
                    try:
                        found = self.tp_fn(origin, destination, month, self.secrets.travelpayouts_token,
                                           self.cfg["currency"], route["direct_only"], one_way=True)
                    except Exception as exc:
                        self._error(f"Travelpayouts 單程 {rid} {origin}→{destination} {month} 失敗（{type(exc).__name__}）")
                        continue
                    for leg in found:
                        if (number(leg.price) and leg.currency.upper() == self.cfg["currency"].upper()
                                and (leg.direct or not route["direct_only"])
                                and (leg.outbound not in best or leg.price < best[leg.outbound].price)):
                            best[leg.outbound] = leg
            for out, back in route_pairs[rid]:
                a, b = legs["out"].get(out.isoformat()), legs["back"].get(back.isoformat())
                key = pair_key(rid, out, back)
                if a and b:
                    offer = self._splice(rid, a, b)
                    if key not in tp_best or offer.price < tp_best[key].price:
                        tp_best[key] = offer

    def _splice(self, rid: str, a: Offer, b: Offer) -> Offer:
        """去程 a＋回程 b。bag_fee 回傳來回行李費，單程各取一半，依該段航空公司計算。"""
        fee_a, est_a = bag_fee(self.cfg, rid, a.airline_code)
        fee_b, est_b = bag_fee(self.cfg, rid, b.airline_code)
        fare, fee = a.price + b.price, (fee_a + fee_b) / 2
        return Offer("travelpayouts", a.outbound, b.outbound, fare + fee, a.currency,
                     a.airline if a.airline == b.airline else f"{a.airline}／{b.airline}", a.direct and b.direct,
                     a.url, a.observed_at, rid, airline_code=a.airline_code, fare=fare, bag_fee=fee,
                     bag_estimated=est_a or est_b, flight_no="／".join(x for x in (a.flight_no, b.flight_no) if x) or None,
                     depart_time=a.depart_time, arrive_time=a.arrive_time, return_depart_time=b.depart_time,
                     origin_airport=a.origin_airport, destination_airport=a.destination_airport,
                     duration_to=a.duration_to, duration_back=b.duration_to, split=True)

    def _baselines(self) -> dict[str, Baseline | None]:
        return {rid: compute_baseline(self.state, self.cfg, self.now, rid) for rid in self.routes}

    def _valid_offer(self, offer: Offer) -> bool:
        return bool(number(offer.price) and offer.currency.upper() == self.cfg["currency"].upper()
                    and (offer.direct or not self.routes[offer.route_id]["direct_only"]))

    def _error(self, message: str) -> None:
        log.error(message)
        self.summary["errors"].append(message)

    def _rollover_budgets(self) -> None:
        budget = self.state["serpapi"]
        month, day = self.now.strftime("%Y-%m"), self.now.date().isoformat()
        if budget["month"] != month:
            budget.update(month=month, used_month=0)
        if budget["day"] != day:
            budget.update(day=day, used_day=0)

    def _run_budget(self) -> int:
        sc = self.cfg["sources"]["serpapi"]
        if not sc.get("enabled", True) or not self.secrets.serpapi_key:
            return 0
        used = self.state["serpapi"]
        daily = int(sc["daily_budget"])
        cap = math.ceil(daily / runs_per_day(self.cfg, self.now.month)) + 1
        return max(0, min(cap, daily - used["used_day"],
                          int(sc["monthly_quota"]) - int(sc["monthly_safety"]) - used["used_month"]))

    def _select_pairs(self, keys: list[str], tp_best: dict[str, Offer], baselines: dict[str, Baseline | None]) -> list[str]:
        budget = self._run_budget()
        if not budget:
            return []
        sc = self.cfg["sources"]["serpapi"]
        digest = self.cfg["thresholds"]["digest"]

        def ratio(key):
            b = baselines.get(split_key(key)[0])
            return b.ratio(tp_best[key].price) if b else None
        # pass 1：跨航線的候選優先；比例用各自航線的基準，尚無基準者排在有比例者之後。
        cands = sorted((k for k in tp_best if ratio(k) is None or ratio(k) <= digest),
                       key=lambda k: (ratio(k) is None, ratio(k) or 0, tp_best[k].price, k))
        cutoff = self.now - timedelta(hours=float(sc["reverify_hours"]))
        skipped = set()
        chosen = []
        unbased = set()   # 已取過「尚無基準」pair 的航線；每條航線最多 1 個，其餘留給 pass 2 輪流
        for key in cands:
            if ratio(key) is None and split_key(key)[0] in unbased:
                continue
            p = self.state["pairs"].get(key, {})
            recent = (p.get("last_serpapi") and p.get("last_price") and parse_time(p["last_serpapi"]) >= cutoff
                      and tp_best[key].price > p["last_price"] * (1 - self.cfg["dedupe"]["min_drop_ratio"]))
            if recent:
                skipped.add(key)
            elif len(chosen) < min(int(sc["reserve_for_candidates"]), budget):
                chosen.append(key)
                if ratio(key) is None:
                    unbased.add(split_key(key)[0])
        # pass 2：剩餘額度在航線間輪流；最近一次 SerpApi 最舊（從未驗證者最先）的航線先，同時間依清單順序。
        def stamp(key):
            at = self.state["pairs"].get(key, {}).get("last_serpapi")
            return parse_time(at).timestamp() if at else float("-inf")
        queues, last = {}, {}
        for rid in self.routes:
            mine = [k for k in keys if split_key(k)[0] == rid]
            last[rid] = max((stamp(k) for k in mine), default=float("-inf"))
            queues[rid] = sorted((k for k in mine if k not in chosen and k not in skipped), key=lambda k: (stamp(k), k))
        priority = {rid: i for i, rid in enumerate(self.routes)}
        rotation = sorted(self.routes, key=lambda rid: (last[rid], priority[rid]))
        while len(chosen) < budget and any(queues.values()):
            for rid in rotation:
                if len(chosen) >= budget:
                    break
                if queues[rid]:
                    chosen.append(queues[rid].pop(0))
        return chosen

    def _serpapi(self, key: str):
        cfg = self.cfg
        rid, out, back = split_key(key)
        route = self.routes[rid]
        try:
            result = self.serpapi_fn(route["origin"], route["serpapi_arrival"], out, back, self.secrets.serpapi_key,
                                     cfg["currency"], route["direct_only"], int(route["adults"]))
            if not isinstance(result, serpapi_flights.SearchResult):
                raise ValueError("無效 SearchResult")
        except Exception as exc:
            self._error(f"SerpAPI {key} 失敗（{type(exc).__name__}）；停止本次精查")
            return None
        self.state["serpapi"]["used_day"] += 1
        self.state["serpapi"]["used_month"] += 1
        self.summary["serpapi_calls"] += 1
        return result

    def _record_tp(self, best: dict[str, Offer]) -> None:
        for key, p in self.state["pairs"].items():
            if key not in best:
                for field in ("tp_price", "tp_airline", "tp_url", "tp_at", "tp_fare", "tp_bag_fee", "tp_bag_estimated", "tp_flight"):
                    p.pop(field, None)
        for key, offer in best.items():
            p = self.state["pairs"].setdefault(key, {})
            if p.get("tp_price") != offer.price:
                self.history_rows.append({**offer.to_dict(), "observed_at": self.now.isoformat(timespec="seconds")})
            p.update(tp_price=offer.price, tp_airline=offer.airline, tp_url=offer.url, tp_at=self.now.isoformat(timespec="seconds"),
                     tp_fare=offer.fare, tp_bag_fee=offer.bag_fee, tp_bag_estimated=offer.bag_estimated,
                     tp_flight=offer.flight_info())
        # TP 基準用的累積樣本：每組日期每天一筆（同日多次掃描只留最新），保留 lookback_days 天。
        samples = self.state.setdefault("tp_samples", {})
        self.route_lows = self._route_lows(samples)
        for key, offer in best.items():
            samples[f"{key}|{self.now.date().isoformat()}"] = {
                "route": offer.route_id, "price": offer.price, "basis": "total", "at": self.now.isoformat(timespec="seconds")}
        cutoff = self.now - timedelta(days=int(self.cfg["baseline"]["lookback_days"]))
        for k in [k for k, s in samples.items() if parse_time(s["at"]) < cutoff]:
            del samples[k]
        # 行情「過去 3／6 個月」：每天每條航線的樣本合計，從仍保留的樣本重算；樣本過期後該日合計留著，保留 190 天。
        grouped: dict[str, dict] = {}
        for k, s in samples.items():
            if s.get("basis") == "total":
                row = grouped.setdefault(k.rsplit("|", 1)[1], {}).setdefault(s["route"], {"n": 0, "sum": 0})
                row["n"] += 1
                row["sum"] += s["price"]
        daily = self.state.setdefault("market_daily", {})
        daily.update(grouped)
        for day in [d for d in daily if d < (self.now.date() - timedelta(days=190)).isoformat()]:
            del daily[day]

    def _record_serpapi(self, key: str, result) -> None:
        at = self.now.isoformat(timespec="seconds")
        p = self.state["pairs"].setdefault(key, {})
        p["last_serpapi"] = at
        if result.offers:
            best = min(result.offers, key=lambda o: o.price)
            p.update(last_price=best.price, last_airline=best.airline, last_url=best.url, last_source="serpapi",
                     last_fare=best.fare, last_bag_fee=best.bag_fee, last_bag_estimated=best.bag_estimated,
                     last_flight=best.flight_info())
            if p.get("min_price") is None or best.price < p["min_price"]:
                p.update(min_price=best.price, min_at=at)
            for offer in result.offers:
                self.history_rows.append({**offer.to_dict(), "observed_at": at})
            for alert in [self.state["alerts"].get(key)] + [a for a in self.state["alert_history"] if a["pair_key"] == key]:
                if alert:
                    alert["latest_price"] = best.price
                    alert["min_price_after"] = min(alert.get("min_price_after", alert["price"]), best.price)
        else:
            p["last_empty"] = at
            for field in ("last_price", "last_airline", "last_url", "last_source", "last_fare", "last_bag_fee", "last_bag_estimated", "last_flight"):
                p.pop(field, None)
        insight = result.insights
        if insight:
            p["price_level"] = insight.price_level
            p["price_history"] = insight.price_history[-60:]
            if insight.has_range:
                self.state["typical_ranges"].append({"at": at, "pair": key, "route": split_key(key)[0], "low": insight.typical_low,
                                                      "high": insight.typical_high, "level": insight.price_level})

    def _prune_pairs(self) -> None:
        today = self.now.date()
        for key in list(self.state["pairs"]):
            if split_key(key)[1] < today.isoformat():
                del self.state["pairs"][key]
        cutoff = (today - timedelta(days=90)).isoformat()
        self.state["alerts"] = {k: v for k, v in self.state["alerts"].items() if split_key(k)[1] >= cutoff}
        self.state["alert_history"] = [a for a in self.state["alert_history"] if a["outbound"] >= cutoff]

    def _maintain_pool(self, tp_best: dict, checked: set, baselines: dict[str, Baseline | None]) -> None:
        items = self.state["digest_pool"]["items"]
        for key in list(items):
            item = items[key]
            gone = not item["verified"] and key not in tp_best
            old = item["verified"] and parse_time(item["at"]) < self.now - timedelta(days=7)
            baseline = baselines.get(split_key(key)[0])
            if split_key(key)[1] < self.now.date().isoformat() or gone or old or key in checked:
                del items[key]
            else:
                item["ratio"] = baseline.ratio(item["price"]) if baseline else None
                if baseline and item["ratio"] > self.cfg["thresholds"]["digest"]:
                    del items[key]

    def _evaluate(self, verified: dict[str, Offer], tp_best: dict[str, Offer], baselines: dict[str, Baseline | None], checked: set) -> None:
        self._maintain_pool(tp_best, checked, baselines)
        items = self.state["digest_pool"]["items"]
        at = self.now.isoformat(timespec="seconds")
        instant = self.cfg["thresholds"]["instant"]
        def ranked(offers):
            # 依「離觸發線多深」排序（比例÷半價門檻、總價÷好價線、總價÷航線前低取小），單 run 即時通知達上限時留下最好的。
            # 沒有基準的航線只要有好價線或創新低也會進來（ratio 為 None）。
            rows = []
            for k, o in offers.items():
                baseline, good, low = baselines.get(o.route_id), good_price(self.routes[o.route_id]), self._new_low(o)
                ratio = baseline.ratio(o.price) if baseline else None
                if ratio is None and good is None and not low:
                    continue
                depth = min(ratio / instant if ratio is not None else math.inf, o.price / good if good else math.inf,
                            o.price / low["price"] if low else math.inf)
                rows.append((depth, k, ratio, o))
            return [(ratio, k, o) for _, k, ratio, o in sorted(rows, key=lambda row: row[:2])]
        for ratio, key, offer in ranked(verified):
            baseline = baselines.get(offer.route_id)
            self._maybe_instant(key, offer, baseline, ratio, True, at)
            if ratio is not None and ratio <= self.cfg["thresholds"]["digest"]:
                items[key] = {**offer.to_dict(), "ratio": ratio, "verified": True, "at": at}
        for ratio, key, offer in ranked(tp_best):
            baseline = baselines.get(offer.route_id)
            if key in checked:
                continue
            if self.tp_only:
                self._maybe_instant(key, offer, baseline, ratio, False, at)
            if ratio is None:   # 沒有基準：摘要池維持原狀
                continue
            existing = items.get(key)
            if existing and existing["verified"]:
                continue
            if ratio <= self.cfg["thresholds"]["digest"]:
                items[key] = {**offer.to_dict(), "ratio": ratio, "verified": False, "at": at}
            else:
                items.pop(key, None)

    def _maybe_instant(self, key: str, offer: Offer, baseline: Baseline | None, ratio: float | None, verified: bool, at: str) -> None:
        thresholds = self.cfg["thresholds"]
        good = good_price(self.routes[offer.route_id])
        half = ratio is not None and ratio <= thresholds["instant"]
        low = self._new_low(offer)
        if (not (half or (good is not None and offer.price <= good) or low)
                or self.summary["instant_alerts"] >= int(thresholds.get("max_instant_per_run", 5))
                or not self._should_alert(key, offer.price)):
            return
        if self._send_instant(offer, baseline, ratio, verified, low):
            if low:   # 記下推過的新低：同航線同價的其他組合、同一天之後的掃描都不再重複推
                self.route_lows[offer.route_id] = {**low, "price": offer.price}
                self.state.setdefault("new_low_sent", {})[offer.route_id] = {"price": offer.price, "at": at}
            record = {"pair_key": key, "route_id": offer.route_id, "price": offer.price, "at": at,
                      "baseline_at_alert": baseline.value if baseline else None,
                      "ratio": ratio, "airline": offer.airline, "outbound": offer.outbound, "inbound": offer.inbound,
                      "url": offer.url, "latest_price": offer.price, "min_price_after": offer.price, "verified": verified}
            self.state["alerts"][key] = record
            self.state["alert_history"].append(dict(record))
            self.state["stats"]["alerts_sent"] += 1
            self.summary["instant_alerts"] += 1

    def _route_lows(self, samples: dict) -> dict[str, dict]:
        """航線新低的比較基準：近 new_low.days 天（不含今天）該航線樣本最低價與有樣本的天數，再併入期間內推過的新低。
        不看今天的樣本：本輪被上限擋下或送失敗的新低，下一輪仍能推；同一天重複推由 new_low_sent 擋。"""
        days = int((self.cfg.get("new_low") or {}).get("days", 0) or 0)
        if not days:
            return {}
        cutoff, today = self.now - timedelta(days=days), self.now.date().isoformat()
        lows: dict[str, dict] = {}
        for k, s in samples.items():
            day = k.rsplit("|", 1)[1]
            if s.get("basis") == "total" and day != today and parse_time(s["at"]) >= cutoff:
                row = lows.setdefault(s["route"], {"price": math.inf, "dates": set()})
                row["price"] = min(row["price"], s["price"])
                row["dates"].add(day)
        for rid, sent in self.state.get("new_low_sent", {}).items():
            if rid in lows and parse_time(sent["at"]) >= cutoff:
                lows[rid]["price"] = min(lows[rid]["price"], sent["price"])
        return {rid: {"price": row["price"], "days": len(row["dates"])} for rid, row in lows.items()}

    def _new_low(self, offer: Offer) -> dict | None:
        """航線新低：比近 new_low.days 天該航線最低價再低 dedupe.min_drop_ratio 以上；紀錄未滿 min_days 天不算。"""
        cfg, low = self.cfg.get("new_low") or {}, self.route_lows.get(offer.route_id)
        if not low or low["days"] < int(cfg.get("min_days", 1)):
            return None
        return low if offer.price <= low["price"] * (1 - self.cfg["dedupe"]["min_drop_ratio"]) else None

    def _should_alert(self, key: str, price: float) -> bool:
        previous = self.state["alerts"].get(key)
        if not previous:
            return True
        dedupe = self.cfg["dedupe"]
        return (price <= previous["price"] * (1 - dedupe["min_drop_ratio"])
                or self.now - parse_time(previous["at"]) > timedelta(hours=dedupe["cooldown_hours"]))

    def _deliver(self, text: str, kind: str, payload, baseline) -> bool:
        path = None
        if self.render_images:
            try:
                from .render import render_alert, render_digest
                if kind == "alert":
                    path = render_alert(payload, baseline, self.cfg, self.state, self.output_dir)
                else:
                    # 摘要每條航線一張圖（baseline 為 {route_id: Baseline|None}），依優先序以相簿送出。
                    paths = [render_digest(self.cfg, self.state, self.now, baseline.get(route["id"]), payload,
                                           self.output_dir, route) for route in self.cfg["routes"]]
                    return self.tg.send_album(paths, [route["label"] for route in self.cfg["routes"]], text)
            except Exception as exc:
                log.warning("圖片產生失敗（%s）；改送純文字", type(exc).__name__)
        return self.tg.send_photo(path, text)

    def _send_instant(self, offer: Offer, baseline: Baseline | None, ratio: float | None, verified: bool = True,
                      low: dict | None = None) -> bool:
        # 標題先講航線與含行李總價，接著比基準、班次、日期、行李、須知，最後是來源與連結。
        cfg, route = self.cfg, self.routes[offer.route_id]
        level = self.state["pairs"].get(offer.pair_key, {}).get("price_level") or "—"
        half = ratio is not None and ratio <= cfg["thresholds"]["instant"]
        good = good_price(route)
        kind = "神票" if half else "好價" if good is not None and offer.price <= good else "新低"
        with_bag = "含行李 " if float((cfg.get("baggage") or {}).get("checked_kg", 0) or 0) > 0 else ""
        compare = []
        if baseline:
            source = "" if baseline.source == "google" else "，Travelpayouts 中位數"
            compare.append(f"基準 {fmt_money(baseline.value)}{source}（{fmt_pct(ratio)}）")
        else:
            compare.append("基準累積中")
        if good is not None:
            compare.append(f"好價線 {fmt_money(good)}")
        flight = " ".join(part for part in (offer.airline, offer.flight_no) if part) or "航空公司未提供"
        if offer.depart_time and offer.arrive_time:
            flight += f"｜{offer.depart_time} → {offer.arrive_time}"
        head = (f"✈️ <b>{kind}｜{esc(route['label'])} {with_bag}{fmt_money(offer.price)}</b>\n"
                f"{'｜'.join(compare)}\n"
                f"{esc(flight)}\n"
                f"去 {fmt_date(offer.outbound)} → 回 {fmt_date(offer.inbound)}，{offer.nights} 晚\n")
        if low:
            days = int(cfg["new_low"]["days"])
            span = f"近 {days} 天" if low["days"] >= days else f"近 {days} 天（目前累積 {low['days']} 天紀錄）"
            head += f"📉 {span}新低：前低 {fmt_money(low['price'])}，再便宜 {fmt_money(low['price'] - offer.price)}\n"
        if offer.split:
            head += "✂️ 兩張單程拼成：去回分開訂，退改與行李各依該航空規定\n"
        same, limit = self._same_price_dates(offer)
        if same:
            shown = "、".join(fmt_date(day) for day in same[:4]) + ("…" if len(same) > 4 else "")
            head += f"📅 同價位（≤{fmt_money(limit)}）還有 {len(same)} 個出發日：{shown}\n"
        shift = self._shift_one_day(offer)
        if shift:
            label, out, back, price = shift
            diff = price - offer.price
            change = f"省 {fmt_money(-diff)}" if diff < 0 else f"多 {fmt_money(diff)}" if diff > 0 else "同價"
            lead = "🔁 改一天" if diff < 0 else "🔁 改一天最便宜"
            head += f"{lead}：{label}（{fmt_date(out)}→{fmt_date(back)}）{fmt_money(price)}，{change}\n"
        bag = bag_line(cfg, offer.fare, offer.bag_fee, offer.bag_estimated)
        if bag:
            head += esc(bag) + "\n"
        notes = deal_notes(cfg, offer.airline_code, offer.destination_airport, offer.arrive_time, ratio)
        if notes:
            head += "⚠️ 須知\n" + "".join(f"• {esc(note)}\n" for note in notes)
        if verified:
            typical = f"｜典型區間 {fmt_range(baseline.google_low, baseline.google_high)}" if baseline else ""
            text = (head + f"Google 價位：{esc(level)}{typical}\n"
                    f"🔗 {link(offer.url, 'Google Flights 查看／訂票')}")
        else:
            text = (head + f"⏱ {self.now.strftime('%m/%d %H:%M')} 掃描到｜Travelpayouts 快取價（航空公司報價時間不明），"
                    "未經 Google 驗證，訂票前請以實際頁面為準\n"
                    f"🔗 {link(google_url(cfg, route, offer.outbound, offer.inbound), 'Google Flights 查看')}"
                    f"｜{link(offer.url, 'Aviasales（去程）' if offer.split else 'Aviasales')}")
        return self._deliver(text, "alert", offer, baseline)

    def _same_price_dates(self, offer: Offer) -> tuple[list[str], float]:
        """同航線、本次窗口內總價不超過本票 +same_price_within 的其他出發日（同一天多種晚數只算一次）。"""
        within = self.cfg["thresholds"].get("same_price_within")
        limit = offer.price * (1 + float(within or 0))
        if within is None:
            return [], limit
        days = set()
        for key in self.summary.get("pair_keys", []):
            rid, out, _ = split_key(key)
            p = self.state["pairs"].get(key, {})
            price = p.get("last_price") or p.get("tp_price")
            if rid == offer.route_id and out != offer.outbound and price is not None and price <= limit:
                days.add(out)
        return sorted(days), limit

    SHIFTS = ((-1, -1, "整趟提早一天"), (1, 1, "整趟延後一天"), (-1, 0, "早一天出發"), (1, 0, "晚一天出發"),
              (0, -1, "早一天回"), (0, 1, "晚一天回"))

    def _shift_one_day(self, offer: Offer) -> tuple[str, str, str, float] | None:
        """改一天：去或回前後挪一天（只看本次窗口內有價的組合），回傳最便宜的一個 (說明, 去, 回, 總價)。"""
        keys, best = set(self.summary.get("pair_keys", [])), None
        out, back = date.fromisoformat(offer.outbound), date.fromisoformat(offer.inbound)
        for d_out, d_back, label in self.SHIFTS:
            o, b = out + timedelta(days=d_out), back + timedelta(days=d_back)
            key = pair_key(offer.route_id, o, b)
            p = self.state["pairs"].get(key, {})
            price = p.get("last_price") or p.get("tp_price")
            if key in keys and price is not None and (best is None or price < best[3]):
                best = (label, o.isoformat(), b.isoformat(), price)
        return best

    def _check_sales(self) -> None:
        """廉航促銷消息：標題有促銷字眼、max_age_hours 內、沒推過的才推；同一輪合成一則，每家航空最多列 max_items_per_airline 條。"""
        conf = self.cfg.get("airline_sales") or {}
        if not conf.get("enabled"):
            return
        seen = self.state.setdefault("sales_seen", {})
        fresh = self.now - timedelta(hours=float(conf["max_age_hours"]))
        news: dict[str, list[dict]] = {}
        picked: set[str] = set()
        for code, airline in conf["airlines"].items():
            for source in airline["sources"]:
                try:
                    items = self.sales_fn(source)
                except Exception as exc:
                    log.warning("促銷消息 %s 失敗（%s）", source, type(exc).__name__)
                    continue
                for item in items:
                    if item["id"] in seen and not item["at"]:   # 沒有時間的（官網常駐頁）還掛著就續期，不會過期重推
                        seen[item["id"]] = self.now.isoformat(timespec="seconds")
                    if (item["id"] in seen or item["id"] in picked
                            or (item["at"] and parse_time(item["at"]) < fresh) or not airline_sales.is_sale(conf, airline, item)):
                        continue
                    picked.add(item["id"])
                    news.setdefault(code, []).append(item)
        cutoff = self.now - timedelta(days=int(conf.get("keep_days", 30)))
        for k in [k for k, at in seen.items() if parse_time(at) < cutoff]:
            del seen[k]
        self.summary["sales_news"] = sum(len(items) for items in news.values())
        if not news:
            return
        # Google 新聞連結很長：超過 Telegram 單則 4096 字就每家少列一條，避免拆段送出後部分失敗整批重送。
        for shown in range(int(conf.get("max_items_per_airline", 3)), 0, -1):
            lines = ["🏷️ <b>廉航促銷消息</b>"]
            for code, items in news.items():
                lines.append(f"<b>{esc(conf['airlines'][code]['name'])}</b>")
                for item in sorted(items, key=lambda item: item["at"] or "", reverse=True)[:shown]:
                    when = f"，{parse_time(item['at']).astimezone(self.now.tzinfo).strftime('%m/%d %H:%M')}" if item["at"] else ""
                    lines.append(f"• {esc(item['title'])}（{esc(item['source'])}{when}）{link(item['url'], '看消息')}")
                if len(items) > shown:
                    lines.append(f"　另有 {len(items) - shown} 則")
            lines.append("官網限時促銷常在 Travelpayouts 快取更新前賣完，LowFly 的票價還看不到；有興趣請直接上官網查。")
            if len("\n".join(lines)) <= 4096:
                break
        if self.tg.send("\n".join(lines)):   # 送失敗的下一輪重送
            at = self.now.isoformat(timespec="seconds")
            seen.update({item["id"]: at for items in news.values() for item in items})
            log_rows = [row for row in self.state.get("sales_log", []) if parse_time(row["at"]) >= cutoff]
            self.state["sales_log"] = log_rows + [{"at": at, "count": self.summary["sales_news"]}]   # 團隊週報用

    def _maybe_team_report(self, tp_best: dict[str, Offer]) -> None:
        """團隊週報：team_report.weekday 當天 hour_local 後第一輪送出；送失敗下一輪再試。"""
        conf = self.cfg.get("team_report") or {}
        if (not conf.get("enabled") or self.now.weekday() != int(conf.get("weekday", 0))
                or self.now.hour < int(conf.get("hour_local", 9))
                or (self.state.get("team_report") or {}).get("date") == self.now.date().isoformat()):
            return
        lows: dict[str, float] = {}
        for offer in tp_best.values():
            lows[offer.route_id] = min(lows.get(offer.route_id, math.inf), offer.price)
        text, snapshot = build_team_report(self.cfg, self.state, self.now, lows)
        if self.tg.send(text):
            self.state["team_report"] = snapshot
            self.summary["team_report_sent"] = True

    def _maybe_digest(self, baselines: dict[str, Baseline | None], tp_best: dict) -> None:
        cfg, st, today = self.cfg, self.state, self.now.date()
        due = self.now.hour >= cfg["digest"]["hour_local"] and st["last_digest_date"] != today.isoformat()
        if not (due or self.force_digest):
            return
        win = cfg["window"]
        lines = [f"✈️ <b>{esc(cfg['app_name'])}｜每日摘要</b> {fmt_date(today)}",
                 f"未來 {win['days_ahead']} 天直飛來回"]
        for rid, route in self.routes.items():
            nights, baseline = route["stay_nights"], baselines.get(rid)
            head = f"{esc(route['label'])}（{min(nights)}～{max(nights)} 晚）"
            if baseline and baseline.source != "google":
                lines.append(f"{head} 基準價 <b>{fmt_money(baseline.value)}</b>（Travelpayouts 近 {cfg['baseline']['lookback_days']} 天快取價中位數）")
            elif baseline:
                lines.append(f"{head} 基準價 <b>{fmt_money(baseline.value)}</b>（Google 典型區間 {fmt_range(baseline.google_low, baseline.google_high)}，近 {cfg['baseline']['lookback_days']} 天 {baseline.n_ranges} 筆）")
            else:
                lines.append(f"{head} 基準價：尚未取得 Google 典型區間（程式剛啟動或 SerpAPI 額度用完）")
        items = sorted((item for item in st["digest_pool"]["items"].values() if item.get("ratio") is not None),
                       key=lambda item: item["ratio"])
        lines.append("")
        threshold = cfg["thresholds"]["digest"] * 100
        if items:
            lines.append(f"目前好價（≤{threshold:.0f}%）：")
            for item in items[:cfg["digest"]["top_n"]]:
                tag = ("✓ 已驗證" if item["verified"] else "⌛ 待驗證（Aviasales 快取）") + ("｜兩張單程" if item.get("split") else "")
                lines.append(f"• {esc(self.routes[item['route_id']]['label'])} {fmt_date(item['outbound'])}→{fmt_date(item['inbound'])} <b>{fmt_money(item['price'])}</b>（{fmt_pct(item['ratio'])}）{esc(item['airline'])} {tag} {link(item['url'])}")
                bag = bag_line(cfg, item.get("fare"), item.get("bag_fee", 0), item.get("bag_estimated"))
                if bag:
                    lines.append(f"　{esc(bag)}")
                for note in deal_notes(cfg, item.get("airline_code"), item.get("destination_airport"), item.get("arrive_time"), item["ratio"]):
                    lines.append(f"　⚠️ {esc(note)}")
            extra = len(items) - cfg["digest"]["top_n"]
            if extra > 0:
                lines.append(f"…另有 {extra} 筆")
        else:
            lines.append(f"目前沒有低於基準 {threshold:.0f}% 的票。")
        for rid, route in self.routes.items():
            verified = [(k, p) for k, p in st["pairs"].items() if p.get("last_price") and k in self.summary["pair_keys"] and split_key(k)[0] == rid]
            if verified:
                key, p = min(verified, key=lambda item: item[1]["last_price"])
                _, out, back = split_key(key)
                baseline = baselines.get(rid)
                discount = fmt_pct(baseline.ratio(p["last_price"])) + "，" if baseline else ""
                lines += ["", f"{esc(route['label'])} 已驗證最低：{fmt_date(out)}→{fmt_date(back)} {fmt_money(p['last_price'])}（{discount}{esc(p.get('last_airline', ''))}）"]
        if self.tp_only:
            lines.append("SerpAPI 目前不可用：以上皆為 Travelpayouts 快取價，未經 Google 驗證，訂票前請以實際頁面為準。")
        lines.append(f"SerpAPI 本月 {st['serpapi']['used_month']}/{cfg['sources']['serpapi']['monthly_quota']}｜Travelpayouts 快取 {len(tp_best)} 組日期")
        if self._deliver("\n".join(lines), "digest", len(tp_best), baselines):
            st["last_digest_date"] = today.isoformat()
            st["stats"]["digests_sent"] += 1
            self.summary["digest_sent"] = True
