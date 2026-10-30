"""無額外依賴的 JSON 資料合約檢查。"""
from __future__ import annotations

import argparse
import json
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
    for field in ("app", "route", "window", "thresholds", "baseline", "budget", "deals", "cheapest_verified", "stats"):
        assert field in summary, f"summary 缺少 {field}"
    for field in ("value", "google_low", "google_high", "n_ranges", "lookback_days"):
        assert field in summary["baseline"], f"baseline 缺少 {field}"
    for field in ("serpapi_used_month", "serpapi_quota", "serpapi_used_day", "serpapi_daily_budget", "tp_pairs"):
        assert field in summary["budget"], f"budget 缺少 {field}"
    win = summary["window"]
    expected = (win["days_ahead"] - win["min_lead_days"] + 1) * len(win["stay_nights"])
    assert len(pairs) == expected, f"日期組合應有 {expected} 筆"
    assert len({p["pair_key"] for p in pairs}) == expected, "日期組合重複"
    today = datetime.fromisoformat(summary["generated_at"]).date()
    expected_keys = {f"{today + timedelta(days=lead)}_{today + timedelta(days=lead + night)}"
                     for lead in range(win["min_lead_days"], win["days_ahead"] + 1) for night in win["stay_nights"]}
    assert {p["pair_key"] for p in pairs} == expected_keys, "日期窗口錯誤"
    for pair in pairs:
        for field in ("pair_key", "outbound", "inbound", "nights", "price", "source", "ratio", "airline", "verified", "checked_at", "price_level", "tp_price", "url"):
            assert field in pair, f"pair 缺少 {field}"
        assert pair["price"] is None or (isinstance(pair["price"], (float, int)) and pair["price"] > 0)
        assert pair["source"] in (None, "serpapi", "travelpayouts")
        assert pair["verified"] == (pair["source"] == "serpapi")
        if pair["ratio"] is not None:
            assert summary["baseline"]["value"] and abs(pair["ratio"] - pair["price"] / summary["baseline"]["value"]) < 1e-8
    assert [d["ratio"] for d in summary["deals"]] == sorted(d["ratio"] for d in summary["deals"])
    for series in docs["history"]["series"].values():
        assert len(series) <= 60
        for point in series:
            assert len(point) == 3 and datetime.fromisoformat(point[0]).tzinfo and point[1] > 0
    for alert in docs["alerts"]["alerts"]:
        for field in ("pair_key", "alerted_at", "price_at_alert", "ratio_at_alert", "latest_price", "min_price_after", "outbound", "inbound", "verdict"):
            assert field in alert
        assert alert["verdict"] in ("低點", "還有更低", "持平", "已結束")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", type=Path, default=ROOT / "docs/data")
    validate(parser.parse_args().folder)
    print("四份 JSON 合約檢查通過")
