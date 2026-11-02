"""社群好價線（沒有基準也能推播）與優惠須知（航空公司規則、深夜抵達）。"""
import pytest

from lowfly.config import Secrets
from lowfly.export import build_pairs, build_summary
from lowfly.models import Offer
from lowfly.notices import deal_notes
from lowfly.state import default_state

from conftest import NOW

HKG_KEY = "HKG:2026-11-14_2026-11-17"


@pytest.fixture
def secrets():
    return Secrets("", "fake-tp")   # 無 SerpApi：TP 快取價直接判斷


@pytest.fixture
def cfg(cfg):
    cfg["routes"][0]["good_price_twd"] = 4500   # HKG
    return cfg


def tp_hkg(price, code="UO", arrive="23:25"):
    out, back = HKG_KEY.split(":")[1].split("_")
    return lambda origin, destination, *a, **k: [Offer(
        "travelpayouts", out, back, price, "TWD", "香港快運", True, "https://www.aviasales.com/x", NOW.isoformat(), "HKG",
        airline_code=code, flight_no=f"{code} 117", depart_time="21:15", arrive_time=arrive, destination_airport="HKG")] if destination == "HKG" else []


def test_notes_come_from_config(cfg):
    assert deal_notes(cfg, "it", "HKG", "12:00") == cfg["notices"]["airlines"]["IT"]
    assert deal_notes(cfg, "BR", "NRT", "18:30") == []
    assert deal_notes(cfg, "BR", "NRT", "22:40")[0].startswith("22:40 深夜抵達成田")
    assert deal_notes(cfg, "BR", "HND", "23:45")[0].startswith("23:45 深夜抵達羽田")
    assert deal_notes(cfg, "BR", "HND", "03:10")[0].startswith("03:10 深夜抵達羽田")   # 05:00 前也算深夜
    assert deal_notes(cfg, "BR", "HND", "23:00") == [] and deal_notes(cfg, None, None, None) == []


def test_good_price_line_alerts_without_baseline(run_scan, cfg):
    scanner = run_scan(default_state(), tp=tp_hkg(4200))
    assert scanner.summary["baseline"]["HKG"] is None and scanner.summary["instant_alerts"] == 1
    alert = scanner.tg.sent[0]
    assert alert.startswith("✈️ <b>好價｜桃園 ⇄ 香港 NT$ 4,200</b>\n基準累積中｜好價線 NT$ 4,500\n香港快運 UO 117｜21:15 → 23:25\n")
    assert "⚠️ 須知\n• 手提＋隨身物品合計 7kg，腰包也算一件\n" in alert
    assert "11/02 09:30 掃描到｜Travelpayouts 快取價" in alert
    assert scanner.state["alerts"][HKG_KEY]["baseline_at_alert"] is None


def test_above_good_line_without_baseline_stays_quiet(run_scan, cfg):
    scanner = run_scan(default_state(), tp=tp_hkg(4600))
    assert scanner.summary["instant_alerts"] == 0 and not scanner.state["alerts"]


def test_export_carries_good_price_and_notes(run_scan, cfg):
    scanner = run_scan(default_state(), tp=tp_hkg(4600, arrive="23:25"))
    pair = next(p for p in build_pairs(cfg, scanner.state, NOW)["pairs"] if p["pair_key"] == HKG_KEY)
    assert pair["notes"] == ["手提＋隨身物品合計 7kg，腰包也算一件"]
    empty = next(p for p in build_pairs(cfg, scanner.state, NOW)["pairs"] if p["price"] is None)
    assert empty["notes"] == []
    routes = {r["id"]: r for r in build_summary(cfg, scanner.state, NOW)["routes"]}
    assert routes["HKG"]["good_price"] == 4500 and routes["TYO"]["good_price"] is None
