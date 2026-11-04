"""兩張單程拼來回：補上來回快取沒有的日期、比來回便宜才取代、行李費依各段航空公司計算。"""
import pytest

from lowfly.config import Secrets
from lowfly.export import build_pairs
from lowfly.models import Offer
from lowfly.state import default_state

from conftest import NOW

NAMES = {"UO": "香港快運", "HX": "香港航空", "CX": "國泰航空"}


@pytest.fixture
def secrets():
    return Secrets("", "fake-tp")   # 無 SerpApi：TP 快取價直接判斷


@pytest.fixture
def cfg(cfg):
    cfg["sources"]["travelpayouts"]["one_way"] = True
    return cfg


def leg(day, price, code, number):
    return Offer("travelpayouts", day, day, price, "TWD", NAMES[code], True, "https://www.aviasales.com/x", NOW.isoformat(), "",
                 airline_code=code, flight_no=f"{code} {number}", depart_time="08:00", arrive_time="10:00", destination_airport="HKG")


def make_fetch(round_trips, legs, fail=None):
    """round_trips：{pair_key: (price, code)}；legs：{(origin, day): Offer}。fail：要丟例外的 (origin, month)。"""
    def fetch(origin, destination, month, token, currency="TWD", direct_only=True, one_way=False):
        if (origin, month) == fail:
            raise RuntimeError("down")
        if one_way:
            return [o for (o_origin, day), o in legs.items() if o_origin == origin and day.startswith(month)]
        out = []
        for key, (price, code) in round_trips.items():
            rid, dates = key.split(":")
            if rid == destination and dates.startswith(month):
                out.append(Offer("travelpayouts", *dates.split("_"), price, currency, NAMES[code], True,
                                 "https://www.aviasales.com/x", NOW.isoformat(), airline_code=code))
        return out
    return fetch


LEGS = {("TPE", "2026-11-14"): leg("2026-11-14", 2000, "UO", 117), ("HKG", "2026-11-17"): leg("2026-11-17", 2500, "HX", 255),
        ("TPE", "2026-11-20"): leg("2026-11-20", 3000, "UO", 119), ("HKG", "2026-11-23"): leg("2026-11-23", 3000, "UO", 118),
        ("TPE", "2026-11-25"): leg("2026-11-25", 2500, "UO", 117), ("HKG", "2026-11-28"): leg("2026-11-28", 2500, "UO", 118)}
ROUND_TRIPS = {"HKG:2026-11-14_2026-11-17": (9000, "CX"), "HKG:2026-11-25_2026-11-28": (4000, "CX")}


def test_splice_fills_gaps_and_only_replaces_pricier_round_trips(run_scan):
    pairs = run_scan(default_state(), tp=make_fetch(ROUND_TRIPS, LEGS)).state["pairs"]
    mixed = pairs["HKG:2026-11-14_2026-11-17"]          # 2,000＋2,500 比來回 9,000 便宜
    assert mixed["tp_price"] == 4500 and mixed["tp_airline"] == "香港快運／香港航空"
    assert mixed["tp_flight"]["split"] is True and mixed["tp_flight"]["flight_no"] == "UO 117／HX 255"
    assert pairs["HKG:2026-11-20_2026-11-23"]["tp_price"] == 6000          # 來回快取沒有這組
    kept = pairs["HKG:2026-11-25_2026-11-28"]          # 單程 5,000 比來回 4,000 貴：保留來回
    assert kept["tp_price"] == 4000 and kept["tp_flight"]["split"] is None
    assert "HKG:2026-11-14_2026-11-23" not in pairs     # 9 晚不在住宿晚數


def test_bag_fee_follows_each_leg_airline(run_scan, cfg):
    cfg["baggage"]["checked_kg"] = 20                    # UO 香港單程 1,400；HX 未查證走估算 1,500
    pair = run_scan(default_state(), tp=make_fetch(ROUND_TRIPS, LEGS)).state["pairs"]["HKG:2026-11-14_2026-11-17"]
    assert (pair["tp_fare"], pair["tp_bag_fee"], pair["tp_bag_estimated"], pair["tp_price"]) == (4500, 2900, True, 7400)


def test_split_alert_says_book_two_one_ways(run_scan, cfg):
    cfg["routes"][0]["good_price_twd"] = 4600   # HKG
    sent = run_scan(default_state(), tp=make_fetch(ROUND_TRIPS, LEGS)).tg.sent   # 第一則是更便宜的 4,000 來回
    alert = next(text for text in sent if "香港快運／香港航空 UO 117／HX 255" in text)
    assert "NT$ 4,500" in alert and "兩張單程" not in sent[0]
    assert "✂️ 兩張單程拼成：去回分開訂，退改與行李各依該航空規定\n" in alert and "Aviasales（去程）" in alert


def test_export_marks_split_pairs(run_scan, cfg):
    scanner = run_scan(default_state(), tp=make_fetch(ROUND_TRIPS, LEGS))
    pairs = {p["pair_key"]: p for p in build_pairs(cfg, scanner.state, NOW)["pairs"]}
    assert pairs["HKG:2026-11-14_2026-11-17"]["split"] is True
    assert pairs["HKG:2026-11-25_2026-11-28"]["split"] is None and pairs["HKG:2026-11-04_2026-11-05"]["split"] is None


def test_one_leg_failure_keeps_round_trips_and_other_legs(run_scan):
    scanner = run_scan(default_state(), tp=make_fetch(ROUND_TRIPS, LEGS, fail=("HKG", "2026-11")))
    assert scanner.state["pairs"]["HKG:2026-11-14_2026-11-17"]["tp_price"] == 9000   # 回程抓不到：維持來回
    assert any(e.startswith("Travelpayouts 單程 HKG HKG→TPE 2026-11 失敗") for e in scanner.summary["errors"])
