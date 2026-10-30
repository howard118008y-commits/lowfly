"""驗收以外的額度邊界、失敗備援、歷史與 CLI 防回歸。"""
import copy
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import yaml

from lowfly.baseline import compute_baseline
from lowfly.config import Secrets
from lowfly.export import build_alerts, build_history, build_pairs
from lowfly.main import main
from lowfly.notifier import Telegram, esc, fmt_pct
from lowfly.sources.serpapi_flights import Insights, SearchResult, SerpApiError, search_round_trip
from lowfly.sources.travelpayouts import fetch_month
from lowfly.state import default_state, load_state, save_state

from conftest import KEY, KEY2, NOW, make_serp, make_tp, state_with_baseline


def test_round_half_away_from_zero():
    assert fmt_pct(.665) == "-34%"
    assert fmt_pct(1.335) == "+34%"


def test_html_attribute_escaping():
    assert esc('NX & "quoted" <tag>') == 'NX &amp; &quot;quoted&quot; &lt;tag&gt;'


def test_daily_budget_across_four_runs(run_scan):
    state = default_state()
    calls = []
    counts = []
    for hour in (3, 9, 15, 21):
        scanner = run_scan(state, serp=make_serp({}, calls), now=NOW.replace(hour=hour), render_images=False)
        counts.append(scanner.summary["serpapi_calls"])
    assert counts == [3, 3, 2, 0]
    assert len(calls) == state["serpapi"]["used_day"] == 8


def test_final_monthly_success_stops_exactly_at_240(run_scan):
    state = default_state()
    state["serpapi"].update(month="2026-11", used_month=239, day="2026-11-02", used_day=0)
    assert run_scan(state).summary["serpapi_calls"] == 1
    assert state["serpapi"]["used_month"] == 240


def test_month_and_day_rollover(run_scan):
    state = default_state()
    state["serpapi"].update(month="2026-10", used_month=240, day="2026-10-31", used_day=8)
    assert run_scan(state).summary["serpapi_calls"] == 3
    assert state["serpapi"] == {"month":"2026-11", "used_month":3, "day":"2026-11-02", "used_day":3}


def test_recent_candidate_not_readded_via_round_robin(run_scan):
    state = state_with_baseline()
    state["pairs"][KEY] = {"last_serpapi":NOW.isoformat(), "last_price":3980, "last_source":"serpapi"}
    scanner = run_scan(state, make_tp({KEY: 3900}), now=NOW + timedelta(hours=1))
    assert KEY not in scanner.summary["candidates"]


@pytest.mark.parametrize("hours,price,expected", [(48,3980,False),(48.01,3980,True),(1,3860.6,True),(1,3861,False)])
def test_dedupe_exact_boundaries(run_scan, hours, price, expected):
    state = state_with_baseline()
    state["alerts"][KEY] = {"at": NOW.isoformat(), "price":3980}
    scanner = run_scan(state, now=NOW + timedelta(hours=hours), render_images=False)
    assert scanner._should_alert(KEY, price) == expected


def test_digest_once_and_force_override(run_scan):
    state = state_with_baseline()
    first = run_scan(state, render_images=False)
    second = run_scan(state, now=NOW + timedelta(hours=6), render_images=False)
    forced = run_scan(state, now=NOW + timedelta(hours=7), force_digest=True, render_images=False)
    assert first.summary["digest_sent"] and not second.summary["digest_sent"] and forced.summary["digest_sent"]


def test_pool_pruned_even_without_baseline(run_scan):
    state = default_state()
    state["digest_pool"]["items"][KEY] = {"price":5500, "at":NOW.isoformat(), "verified":False}
    scanner = run_scan(state)
    # 精查若仍取得典型區間會重建基準，但失蹤的 TP 項仍必須移除。
    assert KEY not in scanner.state["digest_pool"]["items"]


def test_pool_old_verified_and_baseline_reclassification(run_scan):
    state = state_with_baseline()
    state["digest_pool"]["items"] = {
        KEY:{"price":4000, "at":(NOW-timedelta(days=8)).isoformat(), "verified":True},
        KEY2:{"price":7000, "at":NOW.isoformat(), "verified":True}}
    run_scan(state)
    assert not state["digest_pool"]["items"]


def test_empty_success_clears_stale_cheap_price(run_scan):
    state = state_with_baseline()
    state["pairs"][KEY] = {"last_price":3980, "last_serpapi":(NOW-timedelta(days=2)).isoformat(), "last_source":"serpapi"}
    state["digest_pool"]["items"][KEY] = {"price":3980, "at":NOW.isoformat(), "verified":True}
    def empty(*args):
        return SearchResult([], Insights(None,None,7200,10000), "", 0)
    scanner = run_scan(state, make_tp({KEY:3900}), empty)
    assert KEY not in state["digest_pool"]["items"]
    assert state["pairs"][KEY].get("last_price") is None
    assert scanner.summary["instant_alerts"] == 0


def test_tp_exception_does_not_stop_round_robin(run_scan):
    def broken(*args):
        raise requests.Timeout()
    scanner = run_scan(tp=broken)
    assert scanner.summary["serpapi_calls"] == 3
    assert scanner.summary["tp_offers"] == 0


def test_tp_only_records_price_changes(run_scan):
    scanner = run_scan(state_with_baseline(), make_tp({KEY:5500}))
    second = run_scan(scanner.state, make_tp({KEY:5500}), now=NOW + timedelta(hours=1))
    assert not [row for row in second.history_rows if row["source"] == "travelpayouts"]


def test_no_token_does_not_mark_real_delivery(run_scan):
    tg = Telegram("", "")
    scanner = run_scan(state_with_baseline(), make_tp({KEY:3900}), make_serp({KEY:3980}), tg=tg)
    assert scanner.summary["instant_alerts"] == 0 and not scanner.summary["digest_sent"]
    assert not scanner.state["alerts"]


@pytest.mark.parametrize("failure", ["http", "body", "exception"])
def test_telegram_failure_does_not_mark_alert(run_scan, monkeypatch, failure):
    if failure == "exception":
        post = Mock(side_effect=requests.Timeout())
    else:
        post = Mock(return_value=Mock(status_code=500 if failure == "http" else 200, json=lambda:{"ok":False}))
    monkeypatch.setattr("lowfly.notifier.requests.post", post)
    scanner = run_scan(state_with_baseline(), make_tp({KEY:3900}), make_serp({KEY:3980}), tg=Telegram("fake", "fake"))
    assert not scanner.summary["instant_alerts"] and not scanner.state["alerts"]
    assert scanner.state["last_digest_date"] == ""


def test_caption_overflow_sends_photo_then_full_text(tmp_path, monkeypatch):
    png = tmp_path / "image.png"
    png.write_bytes(b"png")
    post = Mock(return_value=Mock(status_code=200, json=lambda:{"ok":True}))
    monkeypatch.setattr("lowfly.notifier.requests.post", post)
    caption = "<b>低飛</b>\n" + "機票價格 " * 300
    assert Telegram("fake", "fake").send_photo(png, caption)
    assert len(post.call_args_list) == 2
    assert post.call_args_list[0].args[0].endswith("sendPhoto")
    assert len(post.call_args_list[0].kwargs["data"]["caption"]) <= 1024
    assert post.call_args_list[1].kwargs["json"]["text"] == caption


def test_failed_photo_uses_message(tmp_path, monkeypatch):
    png = tmp_path / "image.png"
    png.write_bytes(b"png")
    post = Mock(side_effect=[Mock(status_code=400, json=lambda:{"ok":False}), Mock(status_code=200, json=lambda:{"ok":True})])
    monkeypatch.setattr("lowfly.notifier.requests.post", post)
    assert Telegram("fake", "fake").send_photo(png, "完整文字")
    assert post.call_args.args[0].endswith("sendMessage")


@pytest.mark.parametrize("body", [{"error":"run out of searches"}, [], None])
def test_serp_200_error_body_is_failure(monkeypatch, body):
    response = Mock(status_code=200, json=lambda:body)
    monkeypatch.setattr("lowfly.sources.serpapi_flights.requests.get", Mock(return_value=response))
    with pytest.raises(SerpApiError):
        search_round_trip("TPE", "MFM", *KEY.split("_"), "fake")


def test_serp_contract_and_history(monkeypatch):
    body = {"search_metadata":{"google_flights_url":"https://www.google.com/travel/flights?q=x"},
            "best_flights":[{"price":3980,"flights":[{"airline":"長榮航空"}]}],
            "other_flights":[{"price":3000,"flights":[{},{}]}, {"price":"NaN","flights":[{}]}],
            "price_insights":{"typical_price_range":[7200,10000],"price_history":[[1,5000],[2,3980]]}}
    get = Mock(return_value=Mock(json=lambda:body))
    monkeypatch.setattr("lowfly.sources.serpapi_flights.requests.get", get)
    result = search_round_trip("TPE", "MFM", *KEY.split("_"), "fake")
    assert len(result.offers) == 1 and result.offers[0].price == 3980
    assert result.insights.price_history == [[1,5000],[2,3980]]
    params = get.call_args.kwargs["params"]
    assert params["stops"] == 1 and params["type"] == 1 and params["currency"] == "TWD"


def test_tp_contract_direct_filter_and_airline(monkeypatch):
    good = {"departure_at":"2026-11-14T09:00:00+08:00","return_at":"2026-11-17T09:00:00+08:00",
            "price":3980,"airline":"NX","transfers":0,"return_transfers":0,"link":"/search/x"}
    body = {"success":True,"data":[good,{**good,"return_transfers":1},{**good,"price":-5}]}
    get = Mock(return_value=Mock(json=lambda:body))
    monkeypatch.setattr("lowfly.sources.travelpayouts.requests.get", get)
    offers = fetch_month("TPE", "MFM", "2026-11", "fake")
    assert len(offers) == 1 and offers[0].airline == "澳門航空"
    assert offers[0].url == "https://www.aviasales.com/search/x"
    assert get.call_args.kwargs["params"]["one_way"] == "false"


@pytest.mark.parametrize("body", [{"success":False}, {"success":True,"data":{}}, []])
def test_tp_bad_body_returns_empty(monkeypatch, body):
    monkeypatch.setattr("lowfly.sources.travelpayouts.requests.get", Mock(return_value=Mock(json=lambda:body)))
    assert fetch_month("TPE", "MFM", "2026-11", "fake") == []


@pytest.mark.parametrize("latest,verdict", [(4200,"低點"),(3700,"還有更低"),(3980,"持平")])
def test_retrospective_uses_best_in_latest_search(latest, verdict):
    state = state_with_baseline()
    state["alerts"][KEY] = {"price":3980,"at":NOW.isoformat(),"ratio":3980/8600}
    at = (NOW + timedelta(hours=1)).isoformat()
    rows = [{"pair_key":KEY,"observed_at":at,"price":p,"source":"serpapi"} for p in (latest, latest+1800)]
    alert = build_alerts(state, rows, NOW + timedelta(hours=2))["alerts"][0]
    assert alert["latest_price"] == latest and alert["verdict"] == verdict
    assert alert["min_price_after"] == min(3980, latest)


def test_alerts_retained_after_departure_90_days(run_scan):
    state = default_state()
    old = "2026-10-01_2026-10-04"
    ancient = "2026-07-01_2026-07-04"
    state["alerts"] = {key:{"price":3980,"at":NOW.isoformat()} for key in (old, ancient)}
    run_scan(state)
    assert set(state["alerts"]) == {old}
    assert build_alerts(state, [], NOW)["alerts"][0]["verdict"] == "已結束"


def test_history_last_60_keeps_source():
    rows = [{"pair_key":KEY,"observed_at":(NOW+timedelta(minutes=i)).isoformat(),"price":4000+i,"source":"serpapi"} for i in range(75)]
    series = build_history(rows, NOW)["series"][KEY]
    assert len(series) == 60 and series[0][1] == 4015 and series[-1][2] == "serpapi"


def test_export_prefers_google_then_tp_then_null(cfg):
    state = default_state()
    state["pairs"][KEY] = {"last_price":6000,"tp_price":4000,"last_serpapi":NOW.isoformat()}
    state["pairs"][KEY2] = {"tp_price":5000,"tp_at":NOW.isoformat()}
    pairs = {p["pair_key"]:p for p in build_pairs(cfg,state,NOW)["pairs"]}
    assert pairs[KEY]["price"] == 6000 and pairs[KEY]["verified"]
    assert pairs[KEY2]["price"] == 5000 and not pairs[KEY2]["verified"]
    assert sum(p["price"] is None for p in pairs.values()) == 85


def test_dry_run_writes_no_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--mock","--dry-run","--force-digest","--now",NOW.isoformat(),"--output-root",str(tmp_path / "result")]) == 0
    assert list(tmp_path.iterdir()) == []


def test_mock_isolation_and_export(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "must-never-send")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "must-never-send")
    output = tmp_path / "mock"
    assert main(["--mock","--force-digest","--now",NOW.isoformat(),"--output-root",str(output)]) == 0
    assert (output / "docs/index.html").exists()
    summary = json.loads((output / "docs/data/summary.json").read_text())
    assert summary["demo"] is True
    assert (output / "out/digest_2026-11-02.png").exists()


def test_corrupted_state_never_resets_quota(tmp_path):
    path = tmp_path / "data/state.json"
    path.parent.mkdir()
    path.write_text("{broken")
    assert main(["--output-root",str(tmp_path)]) == 1
    assert path.read_text() == "{broken"


def test_state_roundtrip(tmp_path):
    state = state_with_baseline()
    path = tmp_path / "state.json"
    save_state(state, path)
    assert load_state(path) == state


def test_workflow_contract(cfg):
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github/workflows/scan.yml").read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert workflow["on"]["schedule"][0]["cron"] == "17 1,7,13,19 * * *"
    assert cfg["schedule"]["runs_per_day"] == 4
    assert workflow["permissions"] == {"contents":"write", "pages":"write"}
    assert workflow["concurrency"]["group"] == "lowfly-scan"
    options = workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["options"]
    assert options == ["normal","dry-run","test-telegram","force-digest","mock"]
    assert "git add data/ docs/data/" in text
    assert "[skip ci]" in text and "git pull --rebase --autostash origin main" in text
    assert "pages/builds" in text and "|| true" not in text
