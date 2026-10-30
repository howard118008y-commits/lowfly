"""可注入來源的漏斗掃描器；不負責檔案持久化。"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from pathlib import Path

from .baseline import Baseline, compute_baseline
from .config import ROOT
from .dates import date_pairs, fmt_date, months_covering, pair_key, parse_time
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
        self.history_rows: list[dict] = []
        self.summary = {"instant_alerts": 0, "digest_sent": False, "serpapi_calls": 0,
                        "tp_offers": 0, "candidates": [], "errors": []}

    def run(self) -> dict:
        st, cfg = self.state, self.cfg
        win, route = cfg["window"], cfg["route"]
        pairs = date_pairs(self.now.date(), int(win["days_ahead"]), int(win["min_lead_days"]), win["stay_nights"])
        keys = [pair_key(o, b) for o, b in pairs]
        self.summary["pair_keys"] = keys
        self._rollover_budgets()
        self._prune_pairs()
        tp_best: dict[str, Offer] = {}
        if cfg["sources"]["travelpayouts"].get("enabled", True) and self.secrets.travelpayouts_token:
            for month in months_covering(pairs):
                try:
                    offers = self.tp_fn(route["origin"], route["destination"], month,
                                        self.secrets.travelpayouts_token, cfg["currency"], route["direct_only"])
                    for offer in offers:
                        if self._valid_offer(offer) and offer.pair_key in keys:
                            if offer.pair_key not in tp_best or offer.price < tp_best[offer.pair_key].price:
                                tp_best[offer.pair_key] = offer
                except Exception as exc:
                    self._error(f"Travelpayouts {month} 失敗（{type(exc).__name__}）")
        self.summary["tp_offers"] = len(tp_best)
        self._record_tp(tp_best)
        baseline = compute_baseline(st, cfg, self.now)
        selected = self._select_pairs(keys, tp_best, baseline)
        self.summary["candidates"] = selected
        verified, checked = {}, set()
        for key in selected:
            result = self._serpapi(key)
            if result is None:
                break
            checked.add(key)
            result.offers = [o for o in result.offers if self._valid_offer(o) and o.pair_key == key]
            self._record_serpapi(key, result)
            if result.offers:
                verified[key] = min(result.offers, key=lambda o: o.price)
        prune_typical_ranges(st)
        baseline = compute_baseline(st, cfg, self.now)
        self.summary["baseline"] = baseline.value if baseline else None
        self._evaluate(verified, tp_best, baseline, checked)
        self._maybe_digest(baseline, tp_best)
        st["stats"]["runs"] += 1
        st["last_run_at"] = self.now.isoformat(timespec="seconds")
        st["last_tp_count"] = len(tp_best)
        return self.summary

    def _valid_offer(self, offer: Offer) -> bool:
        return bool(number(offer.price) and offer.currency.upper() == self.cfg["currency"].upper()
                    and (offer.direct or not self.cfg["route"]["direct_only"]))

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

    def _select_pairs(self, keys: list[str], tp_best: dict[str, Offer], baseline: Baseline | None) -> list[str]:
        budget = self._run_budget()
        if not budget:
            return []
        sc = self.cfg["sources"]["serpapi"]
        cands = sorted((k for k, o in tp_best.items() if baseline is None or baseline.ratio(o.price) <= self.cfg["thresholds"]["digest"]),
                       key=lambda k: (tp_best[k].price, k))
        cutoff = self.now - timedelta(hours=float(sc["reverify_hours"]))
        skipped = set()
        chosen = []
        for key in cands:
            p = self.state["pairs"].get(key, {})
            recent = (p.get("last_serpapi") and p.get("last_price") and parse_time(p["last_serpapi"]) >= cutoff
                      and tp_best[key].price > p["last_price"] * (1 - self.cfg["dedupe"]["min_drop_ratio"]))
            if recent:
                skipped.add(key)
            elif len(chosen) < min(int(sc["reserve_for_candidates"]), budget):
                chosen.append(key)
        def order(key):
            at = self.state["pairs"].get(key, {}).get("last_serpapi")
            return (parse_time(at).timestamp() if at else float("-inf"), key)
        for key in sorted(keys, key=order):
            if len(chosen) >= budget:
                break
            if key not in chosen and key not in skipped:
                chosen.append(key)
        return chosen

    def _serpapi(self, key: str):
        route, cfg = self.cfg["route"], self.cfg
        try:
            result = self.serpapi_fn(route["origin"], route["destination"], *key.split("_"), self.secrets.serpapi_key,
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
                for field in ("tp_price", "tp_airline", "tp_url", "tp_at"):
                    p.pop(field, None)
        for key, offer in best.items():
            p = self.state["pairs"].setdefault(key, {})
            if p.get("tp_price") != offer.price:
                self.history_rows.append({**offer.to_dict(), "observed_at": self.now.isoformat(timespec="seconds")})
            p.update(tp_price=offer.price, tp_airline=offer.airline, tp_url=offer.url, tp_at=self.now.isoformat(timespec="seconds"))

    def _record_serpapi(self, key: str, result) -> None:
        at = self.now.isoformat(timespec="seconds")
        p = self.state["pairs"].setdefault(key, {})
        p["last_serpapi"] = at
        if result.offers:
            best = min(result.offers, key=lambda o: o.price)
            p.update(last_price=best.price, last_airline=best.airline, last_url=best.url, last_source="serpapi")
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
            for field in ("last_price", "last_airline", "last_url", "last_source"):
                p.pop(field, None)
        insight = result.insights
        if insight:
            p["price_level"] = insight.price_level
            p["price_history"] = insight.price_history[-60:]
            if insight.has_range:
                self.state["typical_ranges"].append({"at": at, "pair": key, "low": insight.typical_low,
                                                      "high": insight.typical_high, "level": insight.price_level})

    def _prune_pairs(self) -> None:
        today = self.now.date()
        for key in list(self.state["pairs"]):
            if key.split("_")[0] < today.isoformat():
                del self.state["pairs"][key]
        cutoff = (today - timedelta(days=90)).isoformat()
        self.state["alerts"] = {k: v for k, v in self.state["alerts"].items() if k.split("_")[0] >= cutoff}
        self.state["alert_history"] = [a for a in self.state["alert_history"] if a["outbound"] >= cutoff]

    def _maintain_pool(self, tp_best: dict, checked: set, baseline: Baseline | None) -> None:
        items = self.state["digest_pool"]["items"]
        for key in list(items):
            item = items[key]
            gone = not item["verified"] and key not in tp_best
            old = item["verified"] and parse_time(item["at"]) < self.now - timedelta(days=7)
            if key.split("_")[0] < self.now.date().isoformat() or gone or old or key in checked:
                del items[key]
            else:
                item["ratio"] = baseline.ratio(item["price"]) if baseline else None
                if baseline and item["ratio"] > self.cfg["thresholds"]["digest"]:
                    del items[key]

    def _evaluate(self, verified: dict[str, Offer], tp_best: dict[str, Offer], baseline: Baseline | None, checked: set) -> None:
        self._maintain_pool(tp_best, checked, baseline)
        if baseline is None:
            return
        items = self.state["digest_pool"]["items"]
        at = self.now.isoformat(timespec="seconds")
        for key, offer in verified.items():
            ratio = baseline.ratio(offer.price)
            if ratio <= self.cfg["thresholds"]["instant"] and self._should_alert(key, offer.price):
                if self._send_instant(offer, baseline, ratio):
                    record = {"pair_key": key, "price": offer.price, "at": at, "baseline_at_alert": baseline.value,
                              "ratio": ratio, "airline": offer.airline, "outbound": offer.outbound, "inbound": offer.inbound,
                              "url": offer.url, "latest_price": offer.price, "min_price_after": offer.price}
                    self.state["alerts"][key] = record
                    self.state["alert_history"].append(dict(record))
                    self.state["stats"]["alerts_sent"] += 1
                    self.summary["instant_alerts"] += 1
            if ratio <= self.cfg["thresholds"]["digest"]:
                items[key] = {**offer.to_dict(), "ratio": ratio, "verified": True, "at": at}
        for key, offer in tp_best.items():
            if key in checked:
                continue
            existing = items.get(key)
            if existing and existing["verified"]:
                continue
            ratio = baseline.ratio(offer.price)
            if ratio <= self.cfg["thresholds"]["digest"]:
                items[key] = {**offer.to_dict(), "ratio": ratio, "verified": False, "at": at}
            else:
                items.pop(key, None)

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
                    path = render_digest(self.cfg, self.state, self.now, baseline, payload, self.output_dir)
            except Exception as exc:
                log.warning("圖片產生失敗（%s）；改送純文字", type(exc).__name__)
        return self.tg.send_photo(path, text)

    def _send_instant(self, offer: Offer, baseline: Baseline, ratio: float) -> bool:
        cfg = self.cfg
        level = self.state["pairs"].get(offer.pair_key, {}).get("price_level") or "—"
        text = (f"✈️ <b>{esc(cfg['app_name'])}｜神票 ≤{cfg['thresholds']['instant'] * 100:.0f}%</b>\n"
                f"{esc(cfg['route']['label'])} 直飛來回（{offer.nights} 晚）\n"
                f"出發 {fmt_date(offer.outbound)} → 回程 {fmt_date(offer.inbound)}\n"
                f"<b>{fmt_money(offer.price)}</b>（基準 {fmt_money(baseline.value)}，{fmt_pct(ratio)}）\n"
                f"航空：{esc(offer.airline or '—')}\n"
                f"Google 價位：{esc(level)}｜典型區間 {fmt_range(baseline.google_low, baseline.google_high)}\n"
                f"🔗 {link(offer.url, 'Google Flights 查看／訂票')}")
        return self._deliver(text, "alert", offer, baseline)

    def _maybe_digest(self, baseline: Baseline | None, tp_best: dict) -> None:
        cfg, st, today = self.cfg, self.state, self.now.date()
        due = self.now.hour >= cfg["digest"]["hour_local"] and st["last_digest_date"] != today.isoformat()
        if not (due or self.force_digest):
            return
        win, nights = cfg["window"], cfg["window"]["stay_nights"]
        lines = [f"✈️ <b>{esc(cfg['app_name'])}｜每日摘要</b> {fmt_date(today)}",
                 f"{esc(cfg['route']['label'])} 直飛來回，未來 {win['days_ahead']} 天、{min(nights)}～{max(nights)} 晚"]
        if baseline:
            lines.append(f"基準價 <b>{fmt_money(baseline.value)}</b>（Google 典型區間 {fmt_range(baseline.google_low, baseline.google_high)}，近 {cfg['baseline']['lookback_days']} 天 {baseline.n_ranges} 筆）")
        else:
            lines.append("基準價：尚未取得 Google 典型區間（程式剛啟動或 SerpAPI 額度用完）")
        items = sorted(st["digest_pool"]["items"].values(), key=lambda item: item.get("ratio") or float("inf")) if baseline else []
        lines.append("")
        threshold = cfg["thresholds"]["digest"] * 100
        if items:
            lines.append(f"目前好價（≤{threshold:.0f}%）：")
            for item in items[:cfg["digest"]["top_n"]]:
                tag = "✓ 已驗證" if item["verified"] else "⌛ 待驗證（Aviasales 快取）"
                lines.append(f"• {fmt_date(item['outbound'])}→{fmt_date(item['inbound'])} <b>{fmt_money(item['price'])}</b>（{fmt_pct(item['ratio'])}）{esc(item['airline'])} {tag} {link(item['url'])}")
            extra = len(items) - cfg["digest"]["top_n"]
            if extra > 0:
                lines.append(f"…另有 {extra} 筆")
        else:
            lines.append(f"目前沒有低於基準 {threshold:.0f}% 的票。")
        verified = [(k, p) for k, p in st["pairs"].items() if p.get("last_price") and k in self.summary["pair_keys"]]
        if verified:
            key, p = min(verified, key=lambda item: item[1]["last_price"])
            out, back = key.split("_")
            discount = fmt_pct(baseline.ratio(p["last_price"])) + "，" if baseline else ""
            lines += ["", f"目前已驗證最低：{fmt_date(out)}→{fmt_date(back)} {fmt_money(p['last_price'])}（{discount}{esc(p.get('last_airline', ''))}）"]
        lines.append(f"SerpAPI 本月 {st['serpapi']['used_month']}/{cfg['sources']['serpapi']['monthly_quota']}｜Travelpayouts 快取 {len(tp_best)} 組日期")
        if self._deliver("\n".join(lines), "digest", len(tp_best), baseline):
            st["last_digest_date"] = today.isoformat()
            st["stats"]["digests_sent"] += 1
            self.summary["digest_sent"] = True
