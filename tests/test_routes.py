"""多航線：設定、狀態 key 隔離、SerpApi 額度分配、請求參數、匯出與摘要。"""
import copy
import json
from datetime import timedelta
from unittest.mock import Mock

import pytest

from lowfly.baseline import compute_baseline
from lowfly.config import load_config, normalize_routes, validate_config
from lowfly.export import build_alerts, build_summary
from lowfly.notifier import Telegram
from lowfly.scanner import Scanner
from lowfly.state import default_state

from conftest import KEY, NOW, make_serp, make_tp, state_with_baseline

SAME_DATES = "2026-11-14_2026-11-17"


def test_a_config_loads_three_routes_in_priority_order(cfg):
    assert [r["id"] for r in cfg["routes"]] == ["HKG", "TYO", "MFM"]
    assert {r["id"]: r["stay_nights"] for r in cfg["routes"]} == {"HKG": [3, 4, 5], "TYO": [4, 5, 6], "MFM": [3, 4, 5]}
    tyo = cfg["routes"][1]
    assert (tyo["destination"], tyo["serpapi_arrival"]) == ("TYO", "NRT,HND")
    assert all(r["direct_only"] and r["adults"] == 1 and r["origin"] == "TPE" for r in cfg["routes"])
    assert [r["label"] for r in cfg["routes"]] == ["桃園 ⇄ 香港", "桃園 ⇄ 東京", "桃園 ⇄ 澳門"]


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(routes=[]),
    lambda c: c["routes"].append(dict(c["routes"][0])),
    lambda c: c["routes"][0].pop("label"),
    lambda c: c["routes"][1].update(stay_nights=[4, 4]),
])
def test_a_config_validates_routes(cfg, mutate):
    bad = copy.deepcopy(cfg)
    mutate(bad)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_a_route_defaults_fall_back_to_window():
    cfg = {"window": {"stay_nights": [2]}, "routes": [{"id": "X", "origin": "TPE", "destination": "XXX", "label": "x"}]}
    normalize_routes(cfg)
    assert cfg["routes"][0] == {"id": "X", "origin": "TPE", "destination": "XXX", "label": "x", "stay_nights": [2],
                                "serpapi_arrival": "XXX", "direct_only": True, "adults": 1}


def test_b_same_dates_on_two_routes_do_not_collide(run_scan):
    hkg, mfm = f"HKG:{SAME_DATES}", f"MFM:{SAME_DATES}"
    scanner = run_scan(state_with_baseline(), make_tp({hkg: 3900, mfm: 6000}), make_serp({hkg: 3950, mfm: 6100}))
    pairs = scanner.state["pairs"]
    assert pairs[hkg]["tp_price"] == 3900 and pairs[mfm]["tp_price"] == 6000
    assert pairs[hkg]["last_price"] == 3950 and pairs[mfm]["last_price"] == 6100
    assert {r["pair_key"] for r in scanner.history_rows} >= {hkg, mfm}
    assert {r["route_id"] for r in scanner.history_rows} == {"HKG", "MFM"}


def test_b_baselines_are_per_route(cfg):
    state = default_state()
    state["typical_ranges"] = [{"at": NOW.isoformat(), "route": "HKG", "low": 4000, "high": 6000},
                               {"at": NOW.isoformat(), "route": "MFM", "low": 7200, "high": 10000}]
    assert compute_baseline(state, cfg, NOW, "HKG").value == 5000
    assert compute_baseline(state, cfg, NOW, "MFM").value == 8600
    assert compute_baseline(state, cfg, NOW, "TYO") is None


def make_scanner(cfg, secrets, state, tmp_path, **sc):
    cfg = copy.deepcopy(cfg)
    cfg["sources"]["serpapi"].update(sc)
    return Scanner(cfg, secrets, state, Telegram("", "", dry_run=True), NOW, output_dir=tmp_path), cfg


def all_keys(scanner):
    from lowfly.dates import date_pairs, pair_key
    return [pair_key(rid, o, b) for rid, r in scanner.routes.items()
            for o, b in date_pairs(NOW.date(), 30, 2, r["stay_nights"])]


def test_c_pass1_macau_candidate_before_hongkong_non_candidate(cfg, secrets, tmp_path):
    state = state_with_baseline()
    scanner, cfg = make_scanner(cfg, secrets, state, tmp_path, reserve_for_candidates=1)
    hkg_dear = f"HKG:{SAME_DATES}"
    mfm_cheap = "MFM:2026-11-20_2026-11-24"
    tp_best = {}
    for key, price in ((hkg_dear, 9000), (mfm_cheap, 3000)):
        from lowfly.models import Offer
        out, back = key.split(":")[1].split("_")
        tp_best[key] = Offer("travelpayouts", out, back, price, "TWD", route_id=key.split(":")[0])
    baselines = {rid: compute_baseline(state, cfg, NOW, rid) for rid in scanner.routes}
    chosen = scanner._select_pairs(all_keys(scanner), tp_best, baselines)
    assert chosen[0] == mfm_cheap
    assert hkg_dear not in chosen[:1]
    assert [k.split(":")[0] for k in chosen[1:]] == ["HKG", "TYO"]   # 其餘額度走輪流，從香港開始


def test_c_pass1_ranks_by_each_routes_own_baseline(cfg, secrets, tmp_path):
    state = default_state()
    state["typical_ranges"] = [{"at": NOW.isoformat(), "route": "HKG", "low": 4000, "high": 6000},
                               {"at": NOW.isoformat(), "route": "MFM", "low": 7200, "high": 10000}]
    scanner, cfg = make_scanner(cfg, secrets, state, tmp_path, reserve_for_candidates=1)
    from lowfly.models import Offer
    # 香港 4000 / 5000 = 0.8（非候選）；澳門 4300 / 8600 = 0.5（候選）：絕對價格較高的澳門仍優先。
    tp_best = {f"HKG:{SAME_DATES}": Offer("travelpayouts", *SAME_DATES.split("_"), 4000, "TWD", route_id="HKG"),
               f"MFM:{SAME_DATES}": Offer("travelpayouts", *SAME_DATES.split("_"), 4300, "TWD", route_id="MFM")}
    baselines = {rid: compute_baseline(state, cfg, NOW, rid) for rid in scanner.routes}
    assert scanner._select_pairs(all_keys(scanner), tp_best, baselines)[0] == f"MFM:{SAME_DATES}"


def test_c_pass2_rotates_and_ties_go_to_hong_kong(cfg, secrets, tmp_path):
    scanner, _ = make_scanner(cfg, secrets, default_state(), tmp_path, reserve_for_candidates=0)
    scanner.cfg["schedule"]["runs_per_day"] = 1
    scanner.cfg["sources"]["serpapi"]["daily_budget"] = 5
    chosen = scanner._select_pairs(all_keys(scanner), {}, {rid: None for rid in scanner.routes})
    assert [k.split(":")[0] for k in chosen] == ["HKG", "TYO", "MFM", "HKG", "TYO"]
    assert len(set(chosen)) == 5


def test_c_pass2_oldest_route_first_and_oldest_pair_within_route(cfg, secrets, tmp_path):
    state = default_state()
    scanner, _ = make_scanner(cfg, secrets, state, tmp_path, reserve_for_candidates=0)
    keys = all_keys(scanner)
    hkg = [k for k in keys if k.startswith("HKG:")]
    tyo = [k for k in keys if k.startswith("TYO:")]
    state["pairs"][hkg[0]] = {"last_serpapi": (NOW - timedelta(hours=1)).isoformat()}
    state["pairs"][tyo[0]] = {"last_serpapi": (NOW - timedelta(hours=3)).isoformat()}
    chosen = scanner._select_pairs(keys, {}, {rid: None for rid in scanner.routes})
    # 澳門從未驗證 → 最先；其次東京（3 小時前）；最後香港（1 小時前）。
    assert [k.split(":")[0] for k in chosen] == ["MFM", "TYO", "HKG"]
    assert chosen[1] != tyo[0] and chosen[2] != hkg[0]   # 同一航線取 last_serpapi 最舊（未驗證）者


def test_d_tyo_requests_use_city_code_and_both_airports(run_scan):
    tp_calls, serp_calls = [], []
    inner = make_serp({})
    def serp(origin, destination, *rest):
        serp_calls.append((origin, destination))
        return inner(origin, destination, *rest)
    def tp(origin, destination, month, *rest):
        tp_calls.append((origin, destination))
        return []
    run_scan(tp=tp, serp=serp)
    assert set(tp_calls) == {("TPE", "HKG"), ("TPE", "TYO"), ("TPE", "MFM")}
    assert ("TPE", "NRT,HND") in serp_calls and ("TPE", "TYO") not in serp_calls


def test_e_summary_routes_in_priority_order(cfg):
    summary = build_summary(cfg, state_with_baseline(), NOW)
    assert [r["id"] for r in summary["routes"]] == ["HKG", "TYO", "MFM"]
    assert not {"route", "baseline", "deals", "cheapest_verified"} & set(summary)
    assert summary["routes"][1]["stay_nights"] == [4, 5, 6]
    assert summary["routes"][2]["baseline"]["value"] == 8600


def test_e_alerts_carry_route_label(cfg, run_scan):
    scanner = run_scan(state_with_baseline(), make_tp({KEY: 3900}), make_serp({KEY: 3980}))
    alert = build_alerts(cfg, scanner.state, scanner.history_rows, NOW)["alerts"][0]
    assert (alert["route_id"], alert["route_label"]) == ("MFM", "桃園 ⇄ 澳門")


def test_f_digest_item_lines_include_route_label(run_scan):
    hkg, mfm = f"HKG:{SAME_DATES}", "MFM:2026-11-20_2026-11-24"
    state = state_with_baseline()
    state["serpapi"].update(month="2026-11", used_month=8, day="2026-11-02", used_day=8)   # 不精查，只看快取項目
    scanner = run_scan(state, make_tp({hkg: 4000, mfm: 5000}), force_digest=True, render_images=False)
    text = scanner.tg.sent[-1]
    assert "低飛 LowFly｜每日摘要" in text.splitlines()[0] and "澳門" not in text.splitlines()[0]
    bullets = [line for line in text.splitlines() if line.startswith("• ")]
    assert bullets[0].startswith("• 桃園 ⇄ 香港 11/14") and bullets[1].startswith("• 桃園 ⇄ 澳門 11/20")


def test_c_pass1_no_baseline_routes_get_one_pair_each(cfg, secrets, tmp_path):
    from lowfly.models import Offer
    scanner, cfg = make_scanner(cfg, secrets, default_state(), tmp_path)   # 預算 3、reserve 3
    # 香港有最便宜的 3 組 TP 價；仍應三條航線各取 1 個（各取該航線 TP 最低者）。
    prices = {"HKG": (1000, 1100, 1200), "TYO": (5000, 5200), "MFM": (3000, 3100)}
    tp_best, cheapest = {}, {}
    for rid, values in prices.items():
        for i, price in enumerate(values):
            out, back = f"2026-11-{10 + i}", f"2026-11-{13 + i}"
            key = f"{rid}:{out}_{back}"
            tp_best[key] = Offer("travelpayouts", out, back, price, "TWD", route_id=rid)
            cheapest.setdefault(rid, key)
    chosen = scanner._select_pairs(all_keys(scanner), tp_best, {rid: None for rid in scanner.routes})
    assert sorted(k.split(":")[0] for k in chosen) == ["HKG", "MFM", "TYO"]
    assert {k for k in chosen} == set(cheapest.values())


def _recording_post(monkeypatch, fail_methods=()):
    calls = []
    def post(url, timeout=30, **kwargs):
        method = url.rsplit("/", 1)[1]
        calls.append({"method": method, "data": kwargs.get("data"), "json": kwargs.get("json"),
                      "files": {k: v[0] for k, v in (kwargs.get("files") or {}).items()}})
        ok = method not in fail_methods
        return Mock(status_code=200 if ok else 400, json=lambda: {"ok": ok})
    monkeypatch.setattr("lowfly.notifier.requests.post", post)
    return calls


def test_g_digest_sends_one_image_per_route_as_album(run_scan, monkeypatch):
    calls = _recording_post(monkeypatch)
    scanner = run_scan(state_with_baseline(), force_digest=True, tg=Telegram("fake", "fake"))
    albums = [c for c in calls if c["method"] == "sendMediaGroup"]
    assert len(albums) == 1 and scanner.summary["digest_sent"]
    names = list(albums[0]["files"].values())
    assert names == [f"digest_2026-11-02_{rid}.png" for rid in ("HKG", "TYO", "MFM")]
    media = json.loads(albums[0]["data"]["media"])
    assert [m["media"] for m in media] == ["attach://p0", "attach://p1", "attach://p2"]
    assert "每日摘要" in media[0]["caption"]                      # 文字摘要放第一張圖
    assert [m["caption"] for m in media[1:]] == ["桃園 ⇄ 東京", "桃園 ⇄ 澳門"]


def test_g_digest_long_text_goes_first_then_album(run_scan, monkeypatch):
    scanner = run_scan(state_with_baseline(), force_digest=True)   # 預覽模式，只為產生三張圖
    calls = _recording_post(monkeypatch)
    paths = [scanner.output_dir / f"digest_2026-11-02_{rid}.png" for rid in ("HKG", "TYO", "MFM")]
    assert Telegram("fake", "fake").send_album(paths, ["a", "b", "c"], "長" * 1100)
    assert [c["method"] for c in calls] == ["sendMessage", "sendMediaGroup"]
    assert [m["caption"] for m in json.loads(calls[1]["data"]["media"])] == ["a", "b", "c"]


def test_g_album_failure_falls_back_to_single_photos(run_scan, monkeypatch):
    calls = _recording_post(monkeypatch, fail_methods=("sendMediaGroup",))
    scanner = run_scan(state_with_baseline(), force_digest=True, tg=Telegram("fake", "fake"))
    assert scanner.summary["digest_sent"]
    photos = [c for c in calls if c["method"] == "sendPhoto"]
    assert [list(c["files"].values())[0] for c in photos] == [f"digest_2026-11-02_{rid}.png" for rid in ("HKG", "TYO", "MFM")]
