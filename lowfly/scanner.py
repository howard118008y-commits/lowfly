"""可注入來源的漏斗掃描器；不負責檔案持久化。"""
from __future__ import annotations

import logging
import math
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from .baggage import bag_fee, bag_line
from .baseline import Baseline, compute_baseline
from .config import ROOT
from .dates import date_pairs, fmt_date, google_url, months_covering, pair_key, parse_time, split_key
from .models import Offer, number
from .notifier import Telegram, esc, fmt_money, fmt_pct, fmt_range, link
from .sources import serpapi_flights, travelpayouts
from .state import prune_typical_ranges

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, cfg: dict, secrets, state: dict, tg: Telegram, now_local: datetime,
                 serpapi_fn=None, tp_fn=None, force_digest: bool = False,
                 output_dir: Path | None = None, render_images: bool = True):
        self.cfg, self.secrets, self.state, self.tg, self.now = cfg, secrets, state, tg, now_local
        self.serpapi_fn = serpapi_fn or serpapi_flights.search_round_trip
        self.tp_fn = tp_fn or travelpayouts.fetch_month
        self.force_digest = force_digest
        self.output_dir = Path(output_dir or ROOT / "out")
        self.render_images = render_images
        self.routes = {route["id"]: route for route in cfg["routes"]}
        self.history_rows: list[dict] = []
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
        self.summary["tp_offers"] = len(tp_best)
        self._record_tp(tp_best)
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
        self._maybe_digest(baselines, tp_best)
        st["stats"]["runs"] += 1
        st["last_run_at"] = self.now.isoformat(timespec="seconds")
        st["last_tp_count"] = len(tp_best)
        return self.summary

    def _stamp(self, offer: Offer, route_id: str) -> Offer:
        """蓋上航線並加計行李：price 變成總價（之後所有判斷都用它），原票價留在 fare。"""
        fee, estimated = bag_fee(self.cfg, route_id, offer.airline_code)
        return replace(offer, route_id=route_id, fare=offer.price, price=offer.price + fee, bag_fee=fee, bag_estimated=estimated)

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
        cap = math.ceil(daily / int(self.cfg["schedule"]["runs_per_day"])) + 1
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
                for field in ("tp_price", "tp_airline", "tp_url", "tp_at", "tp_fare", "tp_bag_fee", "tp_bag_estimated"):
                    p.pop(field, None)
        for key, offer in best.items():
            p = self.state["pairs"].setdefault(key, {})
            if p.get("tp_price") != offer.price:
                self.history_rows.append({**offer.to_dict(), "observed_at": self.now.isoformat(timespec="seconds")})
            p.update(tp_price=offer.price, tp_airline=offer.airline, tp_url=offer.url, tp_at=self.now.isoformat(timespec="seconds"),
                     tp_fare=offer.fare, tp_bag_fee=offer.bag_fee, tp_bag_estimated=offer.bag_estimated)
        # TP 基準用的累積樣本：每組日期每天一筆（同日多次掃描只留最新），保留 lookback_days 天。
        samples = self.state.setdefault("tp_samples", {})
        for key, offer in best.items():
            samples[f"{key}|{self.now.date().isoformat()}"] = {
                "route": offer.route_id, "price": offer.price, "basis": "total", "at": self.now.isoformat(timespec="seconds")}
        cutoff = self.now - timedelta(days=int(self.cfg["baseline"]["lookback_days"]))
        for k in [k for k, s in samples.items() if parse_time(s["at"]) < cutoff]:
            del samples[k]

    def _record_serpapi(self, key: str, result) -> None:
        at = self.now.isoformat(timespec="seconds")
        p = self.state["pairs"].setdefault(key, {})
        p["last_serpapi"] = at
        if result.offers:
            best = min(result.offers, key=lambda o: o.price)
            p.update(last_price=best.price, last_airline=best.airline, last_url=best.url, last_source="serpapi",
                     last_fare=best.fare, last_bag_fee=best.bag_fee, last_bag_estimated=best.bag_estimated)
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
            for field in ("last_price", "last_airline", "last_url", "last_source", "last_fare", "last_bag_fee", "last_bag_estimated"):
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
        def ranked(offers):   # 比例低的先處理，單 run 即時通知達上限時留下最好的
            return sorted(((baselines[o.route_id].ratio(o.price), k, o) for k, o in offers.items()
                           if baselines.get(o.route_id)), key=lambda item: item[:2])
        for ratio, key, offer in ranked(verified):
            baseline = baselines[offer.route_id]
            self._maybe_instant(key, offer, baseline, ratio, True, at)
            if ratio <= self.cfg["thresholds"]["digest"]:
                items[key] = {**offer.to_dict(), "ratio": ratio, "verified": True, "at": at}
        for ratio, key, offer in ranked(tp_best):
            baseline = baselines[offer.route_id]
            if key in checked:
                continue
            if self.tp_only:
                self._maybe_instant(key, offer, baseline, ratio, False, at)
            existing = items.get(key)
            if existing and existing["verified"]:
                continue
            if ratio <= self.cfg["thresholds"]["digest"]:
                items[key] = {**offer.to_dict(), "ratio": ratio, "verified": False, "at": at}
            else:
                items.pop(key, None)

    def _maybe_instant(self, key: str, offer: Offer, baseline: Baseline, ratio: float, verified: bool, at: str) -> None:
        thresholds = self.cfg["thresholds"]
        if (ratio > thresholds["instant"] or self.summary["instant_alerts"] >= int(thresholds.get("max_instant_per_run", 5))
                or not self._should_alert(key, offer.price)):
            return
        if self._send_instant(offer, baseline, ratio, verified):
            record = {"pair_key": key, "route_id": offer.route_id, "price": offer.price, "at": at, "baseline_at_alert": baseline.value,
                      "ratio": ratio, "airline": offer.airline, "outbound": offer.outbound, "inbound": offer.inbound,
                      "url": offer.url, "latest_price": offer.price, "min_price_after": offer.price, "verified": verified}
            self.state["alerts"][key] = record
            self.state["alert_history"].append(dict(record))
            self.state["stats"]["alerts_sent"] += 1
            self.summary["instant_alerts"] += 1

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

    def _send_instant(self, offer: Offer, baseline: Baseline, ratio: float, verified: bool = True) -> bool:
        cfg = self.cfg
        level = self.state["pairs"].get(offer.pair_key, {}).get("price_level") or "—"
        source = "" if baseline.source == "google" else "，Travelpayouts 中位數"
        head = (f"✈️ <b>{esc(cfg['app_name'])}｜神票 ≤{cfg['thresholds']['instant'] * 100:.0f}%</b>\n"
                f"{esc(self.routes[offer.route_id]['label'])} 直飛來回（{offer.nights} 晚）\n"
                f"出發 {fmt_date(offer.outbound)} → 回程 {fmt_date(offer.inbound)}\n"
                f"<b>{fmt_money(offer.price)}</b>（基準 {fmt_money(baseline.value)}{source}，{fmt_pct(ratio)}）\n"
                f"航空：{esc(offer.airline or '—')}\n")
        bag = bag_line(cfg, offer.fare, offer.bag_fee, offer.bag_estimated)
        if bag:
            head += esc(bag) + "\n"
        if verified:
            text = (head + f"Google 價位：{esc(level)}｜典型區間 {fmt_range(baseline.google_low, baseline.google_high)}\n"
                    f"🔗 {link(offer.url, 'Google Flights 查看／訂票')}")
        else:
            route = self.routes[offer.route_id]
            text = (head + "⚠️ Travelpayouts 快取價，未經 Google 驗證，訂票前請以實際頁面為準\n"
                    f"🔗 {link(google_url(cfg, route, offer.outbound, offer.inbound), 'Google Flights 查看')}"
                    f"｜{link(offer.url, 'Aviasales')}")
        return self._deliver(text, "alert", offer, baseline)

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
                tag = "✓ 已驗證" if item["verified"] else "⌛ 待驗證（Aviasales 快取）"
                lines.append(f"• {esc(self.routes[item['route_id']]['label'])} {fmt_date(item['outbound'])}→{fmt_date(item['inbound'])} <b>{fmt_money(item['price'])}</b>（{fmt_pct(item['ratio'])}）{esc(item['airline'])} {tag} {link(item['url'])}")
                bag = bag_line(cfg, item.get("fare"), item.get("bag_fee", 0), item.get("bag_estimated"))
                if bag:
                    lines.append(f"　{esc(bag)}")
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
