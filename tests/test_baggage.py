"""含託運行李總價：費用來自 config、判斷全用 total。"""
from datetime import timedelta

import pytest

from lowfly.baggage import bag_fee, bag_line
from lowfly.baseline import compute_baseline
from lowfly.config import Secrets, load_config
from lowfly.export import build_pairs
from lowfly.models import Offer
from lowfly.state import default_state

from conftest import KEY, NOW, state_with_baseline


@pytest.fixture
def cfg():
    cfg = load_config()
    # 測試用固定費用表，與正式 config 的查證數字脫鉤（正式數字會隨查證更新）
    cfg["baggage"].update(checked_kg=20, pieces_each_way=1, included=["CI", "BR", "JX", "CX", "NX", "JL", "NH"],
                          fees_twd={"UO": {"HKG": 1000}, "TR": {"TYO": 1500},
                                    "IT": {"HKG": 1000, "TYO": 1500, "MFM": 1000}},
                          unknown_fee_twd=1500)
    return cfg


@pytest.fixture
def secrets():
    return Secrets("", "fake-tp")   # 無 SerpApi：TP 快取價直接判斷


def tp_offer(code, price, key=KEY, route="MFM"):
    out, back = key.split(":")[1].split("_")
    return lambda *a, **k: [Offer("travelpayouts", out, back, price, "TWD", "測試航空", True, "https://www.aviasales.com/x",
                                  NOW.isoformat(), route, airline_code=code)] if a[1] == route else []


def test_a_low_cost_fee_added_both_ways(cfg):
    assert bag_fee(cfg, "HKG", "UO") == (2000.0, False)
    assert bag_fee(cfg, "TYO", "tr") == (3000.0, False)   # 代碼不分大小寫


def test_a_scan_stamps_fare_bag_total(run_scan, cfg):
    scanner = run_scan(tp=tp_offer("UO", 3000, "HKG:2026-11-14_2026-11-17", "HKG"))
    pair = next(p for p in build_pairs(cfg, scanner.state, NOW)["pairs"] if p["pair_key"] == "HKG:2026-11-14_2026-11-17")
    assert (pair["fare"], pair["bag_fee"], pair["total"], pair["price"], pair["bag_estimated"]) == (3000, 2000, 5000, 5000, False)


def test_b_included_airline_has_no_bag_fee(cfg):
    assert bag_fee(cfg, "TYO", "BR") == (0.0, False)
    assert bag_line(cfg, 6000, 0, False) == "票價 NT$ 6,000＋行李已含（20kg 來回）"


def test_c_unknown_airline_uses_estimate(cfg):
    assert bag_fee(cfg, "MFM", "ZZ") == (3000.0, True)
    assert bag_fee(cfg, "MFM", None) == (3000.0, True)
    assert bag_fee(cfg, "MFM", "UO") == (3000.0, True)   # UO 只列了 HKG，其他航線仍是估算
    assert bag_line(cfg, 4000, 3000, True) == "票價 NT$ 4,000＋行李 NT$ 3,000（20kg 來回，行李費估算）"


def test_d_zero_kg_means_total_equals_fare(cfg):
    cfg["baggage"]["checked_kg"] = 0
    assert bag_fee(cfg, "HKG", "UO") == (0.0, False)
    assert bag_line(cfg, 3000, 0, False) == ""


def test_e_ratio_uses_total_not_fare(run_scan, cfg):
    cfg["baggage"]["fees_twd"]["IT"]["MFM"] = 645   # 來回 1290：票價 3870（45%）→ 總價 5160（60%）
    state = state_with_baseline()
    scanner = run_scan(state, tp=tp_offer("IT", 3870))
    assert scanner.summary["instant_alerts"] == 0 and not any("神票" in text for text in scanner.tg.sent)
    item = state["digest_pool"]["items"][KEY]
    assert item["price"] == 5160 and item["fare"] == 3870 and abs(item["ratio"] - 0.6) < 1e-9
    assert any("票價 NT$ 3,870＋行李 NT$ 1,290" in text for text in scanner.tg.sent)   # 摘要列出票價＋行李
    # 對照：不計行李時同一張票就是半價
    cfg["baggage"]["checked_kg"] = 0
    control = run_scan(state_with_baseline(), tp=tp_offer("IT", 3870))
    assert control.summary["instant_alerts"] == 1


def test_e_instant_message_shows_fare_plus_bag(run_scan, cfg):
    cfg["baggage"]["fees_twd"]["IT"]["MFM"] = 100
    scanner = run_scan(state_with_baseline(), tp=tp_offer("IT", 3500))
    alert = scanner.tg.sent[0]
    assert "神票" in alert and "NT$ 3,700" in alert and "票價 NT$ 3,500＋行李 NT$ 200（20kg 來回）" in alert


def test_f_samples_without_basis_are_ignored(cfg):
    state = default_state()
    at = (NOW - timedelta(days=1)).isoformat()
    state["tp_samples"] = {f"HKG:{i}|d": {"route": "HKG", "price": 5000.0, "at": at} for i in range(20)}
    assert compute_baseline(state, cfg, NOW, "HKG") is None
    for sample in state["tp_samples"].values():
        sample["basis"] = "total"
    assert compute_baseline(state, cfg, NOW, "HKG").value == 5000


def test_f_new_samples_record_basis_total(run_scan):
    scanner = run_scan(tp=tp_offer("IT", 3000))
    assert scanner.state["tp_samples"] and all(s["basis"] == "total" for s in scanner.state["tp_samples"].values())


def test_old_state_without_bag_split_exports_none(cfg):
    """上線前的舊狀態只有總價、沒有票價／行李拆分：匯出留空，前端才不會誤標「行李已含」。"""
    state = default_state()
    state["pairs"]["HKG:2026-11-14_2026-11-17"] = {"tp_price": 4659.0, "tp_at": NOW.isoformat(), "tp_airline": "UO"}
    pair = next(p for p in build_pairs(cfg, state, NOW)["pairs"] if p["pair_key"] == "HKG:2026-11-14_2026-11-17")
    assert (pair["total"], pair["fare"], pair["bag_fee"]) == (4659.0, None, None)
