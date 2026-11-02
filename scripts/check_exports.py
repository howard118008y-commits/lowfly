"""無額外依賴的 JSON 資料合約檢查。"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate(folder: Path) -> None:
    docs = {name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("summary", "pairs", "history", "alerts")}
    timestamps = {document["generated_at"] for document in docs.values()}
    assert len(timestamps) == 1, "四個 JSON 必須屬於同一次掃描"
    for timestamp in timestamps:
        assert datetime.fromisoformat(timestamp).tzinfo is not None, "時間必須含時區"
    summary, pairs = docs["summary"], docs["pairs"]["pairs"]
    for field in ("app", "routes", "window", "thresholds", "budget", "stats", "baggage"):
        assert field in summary, f"summary 缺少 {field}"
    for removed in ("route", "baseline", "deals", "cheapest_verified"):
        assert removed not in summary, f"summary 不應再有頂層 {removed}"
    routes = summary["routes"]
    assert routes, "summary.routes 不可為空"
    ids = [r["id"] for r in routes]
    assert len(set(ids)) == len(ids), "航線 id 重複"
    for field in ("serpapi_used_month", "serpapi_quota", "serpapi_used_day", "serpapi_daily_budget", "tp_pairs"):
        assert field in summary["budget"], f"budget 缺少 {field}"
    win = summary["window"]
    today = datetime.fromisoformat(summary["generated_at"]).date()
    assert set(docs["pairs"]["baseline"]) == set(ids), "pairs.baseline 須依 route_id 分組"
    for route in routes:
        for field in ("id", "label", "origin", "destination", "stay_nights", "baseline", "deals", "cheapest_verified", "cheapest_cached"):
            assert field in route, f"route 缺少 {field}"
        assert isinstance(route["baseline"]["samples"], int) and route["baseline"]["min_samples"] > 0
        assert route.get("color") is None or re.fullmatch(r"#[0-9A-Fa-f]{6}", route["color"])
        assert route["baseline"].get("source") in (None, "google", "travelpayouts")
        assert (route["baseline"]["value"] is None) == (route["baseline"]["source"] is None)
        for field in ("value", "google_low", "google_high", "n_ranges", "lookback_days"):
            assert field in route["baseline"], f"baseline 缺少 {field}"
        mine = [p for p in pairs if p["route_id"] == route["id"]]
        expected = (win["days_ahead"] - win["min_lead_days"] + 1) * len(route["stay_nights"])
        assert len(mine) == expected, f"{route['id']} 日期組合應有 {expected} 筆"
        expected_keys = {f"{route['id']}:{today + timedelta(days=lead)}_{today + timedelta(days=lead + night)}"
                         for lead in range(win["min_lead_days"], win["days_ahead"] + 1) for night in route["stay_nights"]}
        assert {p["pair_key"] for p in mine} == expected_keys, f"{route['id']} 日期窗口錯誤"
        assert [d["ratio"] for d in route["deals"]] == sorted(d["ratio"] for d in route["deals"])
        assert all(d["pair_key"].startswith(route["id"] + ":") for d in route["deals"])
        assert docs["pairs"]["baseline"][route["id"]] == route["baseline"]["value"]
    assert [p["route_id"] for p in pairs] == sorted((p["route_id"] for p in pairs), key=ids.index), "pairs 須依航線優先序"
    assert len({p["pair_key"] for p in pairs}) == len(pairs), "日期組合重複"
    baselines = {r["id"]: r["baseline"]["value"] for r in routes}
    for pair in pairs:
        for field in ("pair_key", "route_id", "outbound", "inbound", "nights", "price", "source", "ratio", "airline", "verified", "checked_at", "price_level", "tp_price", "url",
                      "total", "fare", "bag_fee", "bag_estimated", "airline_code", "flight_no", "depart_time", "arrive_time",
                      "return_depart_time", "origin_airport", "destination_airport", "duration_to", "duration_back"):
            assert field in pair, f"pair 缺少 {field}"
        assert pair["route_id"] in baselines
        assert pair["price"] is None or (isinstance(pair["price"], (float, int)) and pair["price"] > 0)
        assert pair["source"] in (None, "serpapi", "travelpayouts")
        assert pair["total"] == pair["price"]
        for clock in ("depart_time", "arrive_time", "return_depart_time"):
            assert pair[clock] is None or re.fullmatch(r"\d{2}:\d{2}", pair[clock]), f"{clock} 須為 HH:MM 或 None"
        for minutes in ("duration_to", "duration_back"):
            assert pair[minutes] is None or (isinstance(pair[minutes], int) and pair[minutes] > 0)
        if pair["price"] is not None and pair["fare"] is not None:   # 舊狀態沒有行李拆分時兩者皆為 None
            assert pair["bag_fee"] >= 0 and abs(pair["fare"] + pair["bag_fee"] - pair["total"]) < 1e-6
        assert (pair["fare"] is None) == (pair["bag_fee"] is None)
        assert pair["verified"] == (pair["source"] == "serpapi")
        if pair["ratio"] is not None:
            value = baselines[pair["route_id"]]
            assert value and abs(pair["ratio"] - pair["price"] / value) < 1e-8
    assert set(docs["history"]["series"]) <= set(ids)
    for route_id, by_pair in docs["history"]["series"].items():
        for key, series in by_pair.items():
            assert key.startswith(route_id + ":") and len(series) <= 60
            for point in series:
                assert len(point) == 3 and datetime.fromisoformat(point[0]).tzinfo and point[1] > 0
    for alert in docs["alerts"]["alerts"]:
        for field in ("pair_key", "route_id", "route_label", "alerted_at", "price_at_alert", "ratio_at_alert", "latest_price", "min_price_after", "outbound", "inbound", "verdict"):
            assert field in alert
        assert alert["route_id"] in ids
        assert alert["verdict"] in ("低點", "還有更低", "持平", "已結束")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", type=Path, default=ROOT / "docs/data")
    validate(parser.parse_args().folder)
    print("四份 JSON 合約檢查通過")
