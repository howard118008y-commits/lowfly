"""規格第 9 節的 1～16 項，一項一個具名測試。"""
from datetime import date, timedelta
from unittest.mock import Mock

import pytest
from PIL import Image

from lowfly.baseline import compute_baseline
from lowfly.dates import date_pairs, fmt_date, months_covering
from lowfly.export import export_all
from lowfly.models import Offer
from lowfly.notifier import Telegram, fmt_money, fmt_pct
from lowfly.render import render_alert, render_digest
from lowfly.state import default_state
from scripts.check_exports import validate

from conftest import KEY, KEY2, NOW, make_serp, make_tp, state_with_baseline


def test_01_date_window():
    pairs = date_pairs(date(2026, 11, 2), 30, 2, [3, 4, 5])
    assert len(pairs) == 87
    assert pairs[0] == (date(2026, 11, 4), date(2026, 11, 7))
    assert pairs[-1] == (date(2026, 12, 2), date(2026, 12, 7))
    assert months_covering(pairs) == ["2026-11", "2026-12"]


def test_02_formatting():
    assert fmt_date("2026-11-14") == "11/14（六）"
    assert fmt_money(3980) == "NT$ 3,980"
    assert fmt_pct(.46) == "-54%"


def test_03_no_baseline(cfg):
    assert compute_baseline(default_state(), cfg, NOW) is None


def test_04_median_range(cfg):
    state = default_state()
    state["typical_ranges"] = [{"at": NOW.isoformat(), "low": n, "high": 10000} for n in (7000, 7400)]
    baseline = compute_baseline(state, cfg, NOW)
    assert (baseline.google_low, baseline.google_high, baseline.value) == (7200, 10000, 8600)


def test_05_old_range_excluded(cfg):
    state = default_state()
    state["typical_ranges"] = [{"at": (NOW - timedelta(days=60)).isoformat(), "low": 7200, "high": 10000}]
    assert compute_baseline(state, cfg, NOW) is None


def test_06_mixed_weights(cfg):
    state = state_with_baseline()
    cfg["baseline"]["weights"] = {"google_typical": .5, "own_history": .5, "social": 0}
    state["pairs"] = {str(n): {"last_price": n, "last_source": "serpapi", "last_serpapi": NOW.isoformat()} for n in (7000, 9000)}
    assert compute_baseline(state, cfg, NOW).value == 8300


def test_07_bootstrap(run_scan):
    calls = []
    third = "2026-11-10_2026-11-13"
    scanner = run_scan(tp=make_tp({KEY: 5200, KEY2: 6100, third: 8900}), serp=make_serp({}, calls))
    assert calls[:2] == [KEY, KEY2]
    assert scanner.summary["serpapi_calls"] == 3
    assert scanner.summary["baseline"] == 8600
    assert scanner.summary["digest_sent"] is True
    assert scanner.state["serpapi"]["used_day"] == 3


def test_08_google_verification_required(run_scan):
    scanner = run_scan(state_with_baseline(), make_tp({KEY: 3900}), make_serp({KEY: 8500}))
    assert scanner.summary["instant_alerts"] == 0
    assert KEY not in scanner.state["digest_pool"]["items"]


def test_09_dedupe_and_price_drop(run_scan):
    scanner = run_scan(state_with_baseline(), make_tp({KEY: 3900}), make_serp({KEY: 3980}))
    assert scanner.summary["instant_alerts"] == 1
    assert all(part in scanner.tg.sent[0] for part in ("神票", "NT$ 3,980", "-54%", "長榮航空"))
    second = run_scan(scanner.state, make_tp({KEY: 3900}), make_serp({KEY: 3980}), now=NOW + timedelta(hours=1))
    assert second.summary["instant_alerts"] == 0
    third = run_scan(second.state, make_tp({KEY: 3700}), make_serp({KEY: 3700}), now=NOW + timedelta(hours=2))
    assert third.summary["instant_alerts"] == 1


def test_10_unverified_digest_and_disappearing_cache(run_scan):
    state = state_with_baseline()
    state["serpapi"].update(month="2026-11", used_month=8, day="2026-11-02", used_day=8)
    scanner = run_scan(state, make_tp({KEY: 5500, KEY2: 5900}), force_digest=True)
    assert scanner.summary["serpapi_calls"] == 0
    assert set(state["digest_pool"]["items"]) == {KEY, KEY2}
    assert all(not item["verified"] for item in state["digest_pool"]["items"].values())
    assert "待驗證" in scanner.tg.sent[-1] and "目前好價" in scanner.tg.sent[-1]
    run_scan(state, make_tp({}), now=NOW + timedelta(hours=1))
    assert state["digest_pool"]["items"] == {}


def test_11_monthly_safety(run_scan):
    state = default_state()
    state["serpapi"].update(month="2026-11", used_month=240, day="2026-11-02", used_day=0)
    assert run_scan(state).summary["serpapi_calls"] == 0


def test_12_serp_error_does_not_consume_quota(run_scan):
    def broken(*args):
        raise RuntimeError("run out of searches")
    scanner = run_scan(serp=broken)
    assert scanner.summary["serpapi_calls"] == 0
    assert len(scanner.summary["errors"]) == 1
    assert scanner.state["serpapi"]["used_day"] == 0


def test_13_alert_image_and_caption(run_scan, tmp_path):
    scanner = run_scan(state_with_baseline(), make_tp({KEY: 3900}), make_serp({KEY: 3980}))
    path = tmp_path / "out" / f"alert_{KEY}.png"
    with Image.open(path) as image:
        assert image.size == (1200, 675) and image.format == "PNG"
        image.verify()
    caption = scanner.tg.sent[0]
    assert len(caption) <= 1024
    expected = ("✈️ <b>低飛 LowFly｜神票 ≤50%</b>\n桃園 ⇄ 澳門 直飛來回（3 晚）\n"
                "出發 11/14（六） → 回程 11/17（二）\n<b>NT$ 3,980</b>（基準 NT$ 8,600，-54%）\n"
                "航空：長榮航空\nGoogle 價位：low｜典型區間 NT$ 7,200～10,000\n"
                '🔗 <a href="https://www.google.com/travel/flights?q=x">Google Flights 查看／訂票</a>')
    assert caption == expected


def test_14_sparse_heatmap(cfg, tmp_path):
    state = state_with_baseline()
    pairs = date_pairs(NOW.date(), 30, 2, [3, 4, 5])
    for index, (out, back) in enumerate(pairs[:30]):
        state["pairs"][f"{out}_{back}"] = {"last_price": 3980} if index < 10 else {"tp_price": 5812}
    path = render_digest(cfg, state, NOW, compute_baseline(state, cfg, NOW), 20, tmp_path)
    with Image.open(path) as image:
        assert image.size == (1200, 675)
        image.verify()


def test_15_all_json_contracts(cfg, run_scan, tmp_path):
    scanner = run_scan(state_with_baseline(), make_tp({KEY: 3900}), make_serp({KEY: 3980}))
    target = tmp_path / "docs/data"
    payloads = export_all(cfg, scanner.state, NOW, scanner.history_rows, target)
    assert {p.name for p in target.iterdir()} == {f"{name}.json" for name in ("summary", "pairs", "history", "alerts")}
    assert all(value["generated_at"] == NOW.isoformat(timespec="seconds") for value in payloads.values())
    assert len(payloads["pairs"]["pairs"]) == 87
    validate(target)


def test_16_missing_font_and_render_failure(cfg, run_scan, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("lowfly.render.FONT_PATH", tmp_path / "missing.ttf")
    monkeypatch.setattr("lowfly.render.BOLD_PATH", tmp_path / "missing-bold.ttf")
    state = state_with_baseline()
    offer = Offer("serpapi", *KEY.split("_"), 3980, "TWD", "長榮航空")
    path = render_alert(offer, compute_baseline(state, cfg, NOW), cfg, state, tmp_path)
    assert path.is_file() and "退回 DejaVu" in caplog.text
    monkeypatch.setattr("lowfly.render.render_alert", Mock(side_effect=OSError("drawing failed")))
    monkeypatch.setattr("lowfly.render.render_digest", Mock(side_effect=OSError("drawing failed")))
    post = Mock(return_value=Mock(status_code=200, json=lambda: {"ok": True}))
    monkeypatch.setattr("lowfly.notifier.requests.post", post)
    scanner = run_scan(state, make_tp({KEY: 3900}), make_serp({KEY: 3980}), tg=Telegram("fake", "fake"))
    assert scanner.summary["instant_alerts"] == 1
    assert post.call_count == 2
    assert all(call.args[0].endswith("/sendMessage") for call in post.call_args_list)
