"""航線新低：本輪最低價比近 30 天該航線看過的最低價再低 3% 以上就推播，不論基準與好價線。"""
from datetime import timedelta

import pytest

from lowfly.config import Secrets
from lowfly.state import default_state

from conftest import NOW, make_tp


@pytest.fixture
def secrets():
    return Secrets("", "fake-tp")   # 無 SerpApi：TP 快取價直接判斷


@pytest.fixture
def cfg(cfg):
    cfg["new_low"]["days"] = 30
    return cfg


def state_with_samples(days=7, price=7000, route="HKG"):
    state = default_state()
    for i in range(1, days + 1):
        at = NOW - timedelta(days=i)
        state["tp_samples"][f"{route}:2026-11-20_2026-11-24|{at.date().isoformat()}"] = {
            "route": route, "price": price, "basis": "total", "at": at.isoformat()}
    return state


def test_new_low_alerts_without_good_line(run_scan):
    scanner = run_scan(state_with_samples(), tp=make_tp({"HKG:2026-11-14_2026-11-17": 6700}))
    assert scanner.summary["instant_alerts"] == 1
    alert = scanner.tg.sent[0]
    assert alert.startswith("✈️ <b>新低｜桃園 ⇄ 香港 NT$ 6,700</b>\n")
    assert "📉 近 30 天（目前累積 7 天紀錄）新低：前低 NT$ 7,000，再便宜 NT$ 300\n" in alert


def test_small_drop_or_short_history_stays_quiet(run_scan):
    tp = make_tp({"HKG:2026-11-14_2026-11-17": 6800})   # 只比前低便宜 2.9%
    assert run_scan(state_with_samples(), tp=tp).summary["instant_alerts"] == 0
    tp = make_tp({"HKG:2026-11-14_2026-11-17": 6000})
    assert run_scan(state_with_samples(days=6), tp=tp).summary["instant_alerts"] == 0   # 紀錄未滿 7 天
    assert run_scan(state_with_samples(route="MFM"), tp=tp).summary["instant_alerts"] == 0   # 別條航線的紀錄不算


def test_only_route_cheapest_alerts_once(run_scan):
    tp = make_tp({"HKG:2026-11-14_2026-11-17": 6700, "HKG:2026-11-20_2026-11-23": 6600, "HKG:2026-11-21_2026-11-24": 6600})
    scanner = run_scan(state_with_samples(), tp=tp)
    assert scanner.summary["instant_alerts"] == 1 and "NT$ 6,600</b>" in scanner.tg.sent[0]


def test_full_history_says_plain_30_days(run_scan):
    scanner = run_scan(state_with_samples(days=30), tp=make_tp({"HKG:2026-11-14_2026-11-17": 6700}))
    assert "📉 近 30 天新低：前低 NT$ 7,000，再便宜 NT$ 300\n" in scanner.tg.sent[0]


def test_pushed_low_is_remembered_and_blocked_low_retries(run_scan, cfg):
    state = state_with_samples()
    run_scan(state, tp=make_tp({"HKG:2026-11-14_2026-11-17": 6700}))
    assert state["new_low_sent"]["HKG"]["price"] == 6700
    later = NOW + timedelta(hours=6)   # 同一天稍晚：另一組同價不再推，前低改成剛推過的 6,700
    scanner = run_scan(state, tp=make_tp({"HKG:2026-11-20_2026-11-23": 6700}), now=later)
    assert scanner.summary["instant_alerts"] == 0
    scanner = run_scan(state, tp=make_tp({"HKG:2026-11-21_2026-11-24": 6400}), now=later + timedelta(hours=6))
    assert "前低 NT$ 6,700，再便宜 NT$ 300" in scanner.tg.sent[0]
    cfg["thresholds"]["max_instant_per_run"] = 1
    state = state_with_samples()
    tp = make_tp({"HKG:2026-11-14_2026-11-17": 6700, "MFM:2026-11-14_2026-11-17": 3000})
    cfg["routes"][1]["good_price_twd"] = 5000   # MFM 好價較深，先佔掉本輪唯一一則
    assert "新低" not in run_scan(state, tp=tp).tg.sent[0]
    assert "新低｜桃園 ⇄ 香港" in run_scan(state, tp=tp, now=NOW + timedelta(hours=3)).tg.sent[0]   # 今天的樣本不當前低
