"""沒有 SerpApi 時的 Travelpayouts 模式：TP 中位數基準、快取價即時通知、單 run 上限。"""
import pytest

from lowfly.baseline import compute_baseline
from lowfly.config import Secrets
from lowfly.dates import date_pairs, pair_key
from lowfly.export import build_summary
from lowfly.state import default_state

from conftest import NOW, make_serp, make_tp, state_with_baseline


@pytest.fixture
def secrets():
    return Secrets("", "fake-tp")


def tp_prices(route_id, prices, nights=(3, 4, 5)):
    pairs = date_pairs(NOW.date(), 30, 2, list(nights))
    return {pair_key(route_id, o, b): price for (o, b), price in zip(pairs, prices)}


def test_a_without_serpapi_key_runs_with_tp_median_baselines(run_scan, cfg):
    tp = {}
    for rid, base, nights in (("HKG", 6000, (3, 4, 5)), ("TYO", 12000, (4, 5, 6)), ("MFM", 8000, (3, 4, 5))):
        tp.update(tp_prices(rid, [base + i * 10 for i in range(21)], nights))   # 中位數 = base + 100
    calls = []
    scanner = run_scan(tp=make_tp(tp), serp=make_serp({}, calls))
    assert scanner.summary["serpapi_calls"] == 0 and calls == [] and scanner.summary["tp_only"] is True
    assert scanner.summary["baseline"] == {"HKG": 6100, "TYO": 12100, "MFM": 8100}
    baseline = compute_baseline(scanner.state, cfg, NOW, "HKG")
    assert baseline.source == "travelpayouts" and baseline.google_low is None
    routes = {r["id"]: r for r in build_summary(cfg, scanner.state, NOW)["routes"]}
    assert routes["HKG"]["baseline"]["source"] == "travelpayouts"
    assert routes["HKG"]["cheapest_cached"]["price"] == 6000 and routes["HKG"]["cheapest_verified"] is None


def test_b_fewer_than_15_tp_pairs_means_no_baseline_and_no_alerts(run_scan):
    scanner = run_scan(tp=make_tp(tp_prices("MFM", [8000] * 13 + [1000])))   # 共 14 組
    assert scanner.summary["baseline"]["MFM"] is None
    assert scanner.summary["instant_alerts"] == 0
    assert not any("神票" in text for text in scanner.tg.sent)


def test_c_tp_only_instant_alert_says_unverified(run_scan):
    scanner = run_scan(tp=make_tp(tp_prices("MFM", [8000] * 15 + [3000])))
    assert scanner.summary["instant_alerts"] == 1
    alert = scanner.tg.sent[0]
    assert "神票" in alert and "未經 Google 驗證" in alert and "Travelpayouts 快取價" in alert
    assert "桃園 ⇄ 澳門" in alert and "NT$ 3,000" in alert
    assert scanner.state["alerts"] and next(iter(scanner.state["alerts"].values()))["verified"] is False
    again = run_scan(scanner.state, tp=make_tp(tp_prices("MFM", [8000] * 15 + [3000])), now=NOW.replace(hour=15))
    assert again.summary["instant_alerts"] == 0   # 沿用 dedupe


def test_d_instant_alerts_capped_per_run_rest_go_to_pool(run_scan):
    scanner = run_scan(tp=make_tp(tp_prices("MFM", [8000] * 15 + [3000 + i for i in range(8)])))
    assert scanner.summary["instant_alerts"] == 5
    assert sum("神票" in text for text in scanner.tg.sent) == 5
    cheapest = {f"NT$ {3000 + i:,}" for i in range(5)}
    assert all(any(price in text for text in scanner.tg.sent) for price in cheapest)   # 留下比例最低的 5 則
    pool = scanner.state["digest_pool"]["items"]
    assert sum(item["price"] < 4000 for item in pool.values()) == 8     # 未即時通知的仍在摘要池


def test_e_google_typical_still_wins_when_present(run_scan, cfg):
    state = state_with_baseline()
    scanner = run_scan(state, tp=make_tp(tp_prices("MFM", [5000] * 20)))
    baseline = compute_baseline(scanner.state, cfg, NOW, "MFM")
    assert baseline.source == "google" and baseline.value == 8600
    assert scanner.summary["baseline"]["MFM"] == 8600
