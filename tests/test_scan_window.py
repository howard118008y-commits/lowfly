"""60 天掃描窗口、促銷月加跑、同價位還有幾個出發日、疑似錯價提醒。"""
import pytest
from PIL import Image

from lowfly.config import Secrets, load_config, runs_per_day
from lowfly.export import build_pairs
from lowfly.notices import deal_notes
from lowfly.render import render_digest
from lowfly.state import default_state

from conftest import KEY, NOW, make_tp, state_with_baseline

SUSPECT = "疑似錯價：可能被航空公司取消（只退票款），先別訂飯店與不可退的行程"


@pytest.fixture
def secrets():
    return Secrets("", "fake-tp")   # 無 SerpApi：TP 快取價直接判斷


def test_real_config_scans_60_days_and_runs_8_times_in_promo_months():
    real = load_config()
    assert real["window"]["days_ahead"] == 60
    assert runs_per_day(real, 5) == runs_per_day(real, 6) == runs_per_day(real, 11) == runs_per_day(real, 12) == 8
    assert runs_per_day(real, 3) == runs_per_day(real, 10) == 4


def test_promo_month_spreads_serpapi_budget_over_more_runs(run_scan, cfg):
    scanner = run_scan()
    scanner.secrets = Secrets("fake-serp", "fake-tp")
    assert scanner._run_budget() == 3          # 每天 4 次：ceil(8/4)+1
    cfg["schedule"]["promo_months"] = [11]     # NOW 是 11 月
    assert scanner._run_budget() == 2          # 每天 8 次：ceil(8/8)+1


def test_60_day_digest_image_splits_into_two_bands(cfg, tmp_path):
    cfg["window"]["days_ahead"] = 60
    path = render_digest(cfg, state_with_baseline(), NOW, None, 0, tmp_path)
    assert Image.open(path).size == (1200, 819)   # 30 天仍是 1200×675（test_14）


def test_alert_lists_other_departure_days_at_same_price(run_scan, cfg):
    cfg["routes"][0]["good_price_twd"] = 4500      # HKG
    scanner = run_scan(default_state(), tp=make_tp({
        "HKG:2026-11-14_2026-11-17": 4200,
        "HKG:2026-11-14_2026-11-18": 4250,         # 同一出發日：不算
        "HKG:2026-11-21_2026-11-24": 4400,         # +4.8%：算
        "HKG:2026-11-21_2026-11-25": 4300,         # 同一天另一種晚數：只算一次
        "HKG:2026-11-28_2026-12-01": 4500}))       # +7.1%：不算
    assert "\n📅 同價位（≤NT$ 4,410）還有 1 個出發日：11/21（六）\n" in scanner.tg.sent[0]


def test_suspect_error_note_only_far_below_baseline(cfg):
    assert deal_notes(cfg, "IT", None, None, 0.18) == [SUSPECT, *cfg["notices"]["airlines"]["IT"]]
    assert SUSPECT not in deal_notes(cfg, "IT", None, None, 0.21)
    assert deal_notes(cfg, None, None, None) == []


def test_suspect_error_reaches_push_digest_and_export(run_scan, cfg):
    scanner = run_scan(state_with_baseline(), tp=make_tp({KEY: 1500}))   # 基準 8,600 → 17%
    assert f"⚠️ 須知\n• {SUSPECT}\n" in scanner.tg.sent[0]
    assert f"　⚠️ {SUSPECT}" in scanner.tg.sent[-1]
    pair = next(p for p in build_pairs(cfg, scanner.state, NOW)["pairs"] if p["pair_key"] == KEY)
    assert pair["notes"] == [SUSPECT]
