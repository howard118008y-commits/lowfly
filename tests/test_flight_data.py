"""真實航班欄位：Travelpayouts／SerpApi 解析、狀態保存、匯出與基準累積進度。"""
from unittest.mock import Mock

import pytest

from lowfly.config import Secrets
from lowfly.export import build_pairs, build_summary
from lowfly.models import Offer
from lowfly.sources.serpapi_flights import search_round_trip
from lowfly.sources.travelpayouts import AIRLINE_ZH, fetch_month

from conftest import NOW

@pytest.fixture
def secrets():
    return Secrets("", "fake-tp")   # 無 SerpApi，pair 維持 TP 資料


ROW = {"departure_at": "2026-11-27T14:25:00+08:00", "return_at": "2026-12-01T22:25:00+09:00", "price": 4496,
       "airline": "TR", "flight_number": "866", "origin_airport": "TPE", "destination_airport": "NRT",
       "duration_to": 185, "duration_back": 250, "transfers": 0, "return_transfers": 0, "link": "/search/x"}


def tp_offers(monkeypatch, row):
    monkeypatch.setattr("lowfly.sources.travelpayouts.requests.get",
                        Mock(return_value=Mock(json=lambda: {"success": True, "data": [row]})))
    return fetch_month("TPE", "TYO", "2026-11", "fake")


def test_travelpayouts_keeps_real_flight_fields(monkeypatch):
    offer = tp_offers(monkeypatch, ROW)[0]
    assert (offer.flight_no, offer.depart_time, offer.return_depart_time) == ("TR 866", "14:25", "22:25")
    assert offer.arrive_time == "18:30"   # 14:25 +08 + 3h05 = 17:30 +08 = 18:30 東京當地
    assert (offer.origin_airport, offer.destination_airport, offer.duration_to, offer.duration_back) == ("TPE", "NRT", 185, 250)
    assert offer.airline == "酷航" and offer.airline_code == "TR"


def test_unknown_airport_timezone_skips_arrival_only(monkeypatch):
    offer = tp_offers(monkeypatch, {**ROW, "destination_airport": "XXX"})[0]
    assert offer.arrive_time is None and offer.depart_time == "14:25"


def test_missing_flight_fields_become_none(monkeypatch):
    offer = tp_offers(monkeypatch, {k: v for k, v in ROW.items() if k in ("departure_at", "return_at", "price", "transfers", "return_transfers")})[0]
    assert offer.flight_no is None and offer.arrive_time is None and offer.duration_to is None


def test_airline_names_cover_requested_codes():
    for code in "UO TR MM GK IT HB HX CX ZG JL NH NX BR CI JX".split():
        assert code in AIRLINE_ZH


def test_serpapi_leg_fields(monkeypatch):
    leg = {"airline": "酷航", "flight_number": "TR 866", "duration": 185,
           "departure_airport": {"id": "TPE", "time": "2026-11-27 14:25"}, "arrival_airport": {"id": "NRT", "time": "2026-11-27 18:30"}}
    body = {"best_flights": [{"price": 4496, "flights": [leg]}]}
    monkeypatch.setattr("lowfly.sources.serpapi_flights.requests.get", Mock(return_value=Mock(json=lambda: body)))
    offer = search_round_trip("TPE", "NRT,HND", "2026-11-27", "2026-12-01", "fake").offers[0]
    assert (offer.flight_no, offer.depart_time, offer.arrive_time, offer.duration_to) == ("TR 866", "14:25", "18:30", 185)
    assert offer.airline_code == "TR" and offer.return_depart_time is None


def test_flight_fields_flow_to_state_and_exports(run_scan, cfg):
    key = "HKG:2026-11-14_2026-11-17"
    def tp(origin, destination, month, *rest):
        if destination != "HKG":
            return []
        return [Offer("travelpayouts", "2026-11-14", "2026-11-17", 4000, "TWD", "香港快運", True, "https://www.aviasales.com/x",
                      NOW.isoformat(), airline_code="UO", flight_no="UO 872", depart_time="07:05", arrive_time="09:10",
                      return_depart_time="21:00", origin_airport="TPE", destination_airport="HKG", duration_to=125, duration_back=120)]
    scanner = run_scan(tp=tp)
    assert scanner.state["pairs"][key]["tp_flight"]["flight_no"] == "UO 872"
    pair = next(p for p in build_pairs(cfg, scanner.state, NOW)["pairs"] if p["pair_key"] == key)
    assert (pair["flight_no"], pair["arrive_time"], pair["airline_code"], pair["duration_back"]) == ("UO 872", "09:10", "UO", 120)
    route = next(r for r in build_summary(cfg, scanner.state, NOW)["routes"] if r["id"] == "HKG")
    assert route["cheapest_cached"]["flight_no"] == "UO 872" and route["color"] == "#B0124F"


def test_old_state_without_flight_fields_exports_none(cfg):
    from lowfly.state import default_state
    state = default_state()
    state["pairs"]["HKG:2026-11-14_2026-11-17"] = {"tp_price": 5000, "tp_airline": "UO", "tp_at": NOW.isoformat()}
    pair = next(p for p in build_pairs(cfg, state, NOW)["pairs"] if p["pair_key"] == "HKG:2026-11-14_2026-11-17")
    assert pair["flight_no"] is None and pair["depart_time"] is None and pair["airline_code"] == "UO"


def test_baseline_progress_counts_total_samples(cfg):
    from lowfly.state import default_state
    state = default_state()
    at = NOW.isoformat()
    state["tp_samples"] = {f"a{i}": {"route": "HKG", "price": 5000, "basis": "total", "at": at} for i in range(10)}
    state["tp_samples"]["old"] = {"route": "HKG", "price": 5000, "at": at}   # 舊樣本不算
    baseline = next(r for r in build_summary(cfg, state, NOW)["routes"] if r["id"] == "HKG")["baseline"]
    assert (baseline["samples"], baseline["min_samples"], baseline["value"]) == (10, 15, None)
