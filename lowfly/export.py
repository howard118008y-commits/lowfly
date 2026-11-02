"""匯出四個不含憑證的公開 JSON，固定同一 generated_at。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .baseline import MIN_TP_PAIRS, compute_baseline, tp_sample_count
from .config import ROOT
from .dates import date_pairs, google_url, pair_key, parse_time, split_key
from .models import FLIGHT_FIELDS, number
from .sources.travelpayouts import AIRLINE_ZH
from .state import write_json


def _baselines(cfg: dict, state: dict, now: datetime) -> dict:
    return {route["id"]: compute_baseline(state, cfg, now, route["id"]) for route in cfg["routes"]}


def build_pairs(cfg: dict, state: dict, now: datetime) -> dict:
    baselines = _baselines(cfg, state, now)
    win = cfg["window"]
    result = []
    for route in cfg["routes"]:
        baseline = baselines[route["id"]]
        for out, back in date_pairs(now.date(), win["days_ahead"], win["min_lead_days"], route["stay_nights"]):
            key = pair_key(route["id"], out, back)
            p = state["pairs"].get(key, {})
            verified = number(p.get("last_price")) is not None
            price = p.get("last_price") if verified else p.get("tp_price")
            source = "serpapi" if verified else ("travelpayouts" if price is not None else None)
            prefix = "last" if verified else "tp"
            flight = {name: None for name in (*FLIGHT_FIELDS, "airline_code")} | (p.get(f"{prefix}_flight") or {})
            airline = p.get("last_airline" if verified else "tp_airline") if price is not None else None
            if flight["airline_code"] is None and isinstance(airline, str) and len(airline) == 2 and airline.isupper():
                flight["airline_code"] = airline   # 舊資料 airline 欄位存的就是 IATA 代碼
            if airline and airline == flight["airline_code"]:
                airline = AIRLINE_ZH.get(airline, airline)   # 代碼換成中文名，畫面不出現「UO」這種裸代碼
            result.append({"pair_key": key, "route_id": route["id"], "outbound": out.isoformat(), "inbound": back.isoformat(),
                           "nights": (back - out).days, "price": price, "source": source,
                           # price 與 total 都是含行李總價；fare 為原票價。舊狀態沒有行李拆分時 fare/bag_fee 留空，
                           # 前端就不顯示「票價＋行李」，避免把未知行李費誤標成「已含」。
                           "total": price, "fare": p.get(f"{prefix}_fare") if price is not None else None,
                           "bag_fee": p.get(f"{prefix}_bag_fee") if price is not None and p.get(f"{prefix}_fare") is not None else None,
                           "bag_estimated": bool(p.get(f"{prefix}_bag_estimated")) if price is not None else False,
                           "ratio": baseline.ratio(price) if baseline and price is not None else None,
                           "airline": airline, **flight,
                           "verified": verified, "checked_at": p.get("last_serpapi" if verified else "tp_at"),
                           "price_level": p.get("price_level"), "tp_price": p.get("tp_price"), "tp_at": p.get("tp_at"),
                           "url": p.get("last_url" if verified else "tp_url") or "",
                           "google_flights_url": p.get("last_url") or google_url(cfg, route, out.isoformat(), back.isoformat())})
    return {"generated_at": now.isoformat(timespec="seconds"),
            "baseline": {rid: b.value if b else None for rid, b in baselines.items()}, "pairs": result}


def build_summary(cfg: dict, state: dict, now: datetime, pair_keys=None, tp_count: int | None = None) -> dict:
    baselines = _baselines(cfg, state, now)
    pairs = build_pairs(cfg, state, now)["pairs"]
    indexed = {p["pair_key"]: p for p in pairs}
    routes = []
    for route in cfg["routes"]:
        baseline = baselines[route["id"]]
        deals = []
        if baseline:
            for key, item in state["digest_pool"]["items"].items():
                if key not in indexed or split_key(key)[0] != route["id"] or baseline.ratio(item["price"]) > cfg["thresholds"]["digest"]:
                    continue
                deals.append({**item, "ratio": baseline.ratio(item["price"]),
                              "google_flights_url": indexed[key]["google_flights_url"]})
        mine = [p for p in pairs if p["route_id"] == route["id"]]
        verified = [p for p in mine if p["verified"]]
        cached = [p for p in mine if p["source"] == "travelpayouts"]
        routes.append({"id": route["id"], "label": route["label"], "origin": route["origin"],
                       "destination": route["destination"], "direct_only": route["direct_only"], "adults": route["adults"],
                       "stay_nights": route["stay_nights"], "color": route.get("color"),
                       "baseline": {"value": baseline.value if baseline else None,
                                    "google_low": baseline.google_low if baseline else None, "google_high": baseline.google_high if baseline else None,
                                    "n_ranges": baseline.n_ranges if baseline else 0, "lookback_days": cfg["baseline"]["lookback_days"],
                                    "source": baseline.source if baseline else None,
                                    "samples": tp_sample_count(state, cfg, now, route["id"]), "min_samples": MIN_TP_PAIRS},
                       "deals": sorted(deals, key=lambda item: (item["ratio"], item["pair_key"])),
                       "cheapest_verified": min(verified, key=lambda p: p["price"]) if verified else None,
                       "cheapest_cached": min(cached, key=lambda p: p["price"]) if cached else None})
    sc = cfg["sources"]["serpapi"]
    return {"generated_at": now.isoformat(timespec="seconds"), "app": cfg["app_name"], "routes": routes,
            "currency": cfg["currency"], "baggage": {"checked_kg": (cfg.get("baggage") or {}).get("checked_kg", 0),
                                                      "pieces_each_way": (cfg.get("baggage") or {}).get("pieces_each_way", 1)},
            "timezone": cfg["timezone"], "window": cfg["window"], "thresholds": cfg["thresholds"],
            "budget": {"serpapi_used_month": state["serpapi"]["used_month"], "serpapi_quota": sc["monthly_quota"],
                       "serpapi_used_day": state["serpapi"]["used_day"], "serpapi_daily_budget": sc["daily_budget"],
                       "monthly_safety": sc["monthly_safety"], "reserve_for_candidates": sc["reserve_for_candidates"],
                       "reverify_hours": sc["reverify_hours"], "tp_pairs": tp_count if tp_count is not None else state.get("last_tp_count", 0)},
            "stats": state["stats"], "schedule": cfg["schedule"], "dedupe": cfg["dedupe"],
            "digest": cfg["digest"], "demo": state.get("demo", False)}


def build_history(rows: list[dict], now: datetime) -> dict:
    grouped = {}
    for row in rows:
        if row.get("pair_key") and row.get("observed_at") and number(row.get("price")):
            grouped.setdefault(row["pair_key"], []).append([row["observed_at"], row["price"], row.get("source", "")])
    # 過期 90 天以外的組合不再匯出，原始 JSONL 保留供稽核。
    cutoff = (now.date() - timedelta(days=90)).isoformat()
    series = {}
    for key, values in grouped.items():
        route_id, out, _ = split_key(key)
        if out >= cutoff:
            series.setdefault(route_id, {})[key] = sorted(values, key=lambda p: parse_time(p[0]))[-60:]
    return {"generated_at": now.isoformat(timespec="seconds"), "series": series}


def build_alerts(cfg: dict, state: dict, rows: list[dict], now: datetime) -> dict:
    # 兼容只有 alerts 字典的舊版狀態，同時保留每一次再推播事件。
    records = list(state.get("alert_history", []))
    existing = {(r["pair_key"], r["at"]) for r in records}
    for key, value in state["alerts"].items():
        if (key, value["at"]) not in existing:
            records.append({"pair_key": key, **value})
    labels = {route["id"]: route["label"] for route in cfg["routes"]}
    result = []
    cutoff = (now.date() - timedelta(days=90)).isoformat()
    for record in records:
        key = record["pair_key"]
        route_id, out, back = split_key(key)
        if out < cutoff:
            continue
        price = record["price"]
        observations = [r for r in rows if r.get("pair_key") == key and r.get("source") == "serpapi"
                        and number(r.get("price")) and parse_time(r["observed_at"]) >= parse_time(record["at"])]
        # 同一次搜尋會有多家航空；回顧採該次最低，而非最後一筆較貴航班。
        batches = {}
        for row in observations:
            at = row["observed_at"]
            batches[at] = min(batches.get(at, row["price"]), row["price"])
        latest = batches[max(batches, key=parse_time)] if batches else record.get("latest_price", price)
        minimum = min([price, record.get("min_price_after", price), *batches.values()])
        verdict = "已結束" if out < now.date().isoformat() else ("低點" if latest >= price * 1.05 else "還有更低" if latest <= price * .95 else "持平")
        result.append({"pair_key": key, "route_id": route_id, "route_label": labels.get(route_id, route_id),
                       "alerted_at": record["at"], "price_at_alert": price,
                       "baseline_at_alert": record.get("baseline_at_alert"), "ratio_at_alert": record.get("ratio"),
                       "airline": record.get("airline", ""), "latest_price": latest, "min_price_after": minimum,
                       "outbound": out, "inbound": back, "verdict": verdict})
    return {"generated_at": now.isoformat(timespec="seconds"), "alerts": sorted(result, key=lambda a: parse_time(a["alerted_at"]), reverse=True)}


def export_all(cfg: dict, state: dict, now: datetime, rows: list[dict], output_dir: Path | None = None) -> dict:
    target = Path(output_dir or ROOT / "docs/data")
    payloads = {"summary": build_summary(cfg, state, now), "pairs": build_pairs(cfg, state, now),
                "history": build_history(rows, now), "alerts": build_alerts(cfg, state, rows, now)}
    for name, payload in payloads.items():
        write_json(payload, target / f"{name}.json")
    return payloads


def write_summary(summary: dict, path: Path | None = None) -> None:
    write_json(summary, Path(path or ROOT / "docs/data/summary.json"))
