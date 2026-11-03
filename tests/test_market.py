"""行情分頁：未來各出發月份 TP 均價（每天抓一次）、LowFly 每日紀錄的過去均價、外部參考。"""
from lowfly.export import build_summary
from lowfly.state import default_state

from conftest import NOW, make_tp


def test_market_averages_next_months_once_a_day(run_scan, cfg):
    cfg["market"]["months_ahead"] = 3
    tp, calls = make_tp({"HKG:2026-11-20_2026-11-23": 4000, "HKG:2026-11-21_2026-11-24": 5000,
                         "HKG:2026-11-21_2026-11-30": 3000,    # 9 晚：不在住宿晚數
                         "HKG:2026-11-01_2026-11-04": 2000,    # 已出發
                         "HKG:2027-01-10_2027-01-13": 6000}), []
    def counting(*args, **kwargs):
        calls.append(args[2])
        return tp(*args, **kwargs)
    scanner = run_scan(tp=counting)
    market = scanner.state["market"]
    assert market["date"] == "2026-11-02" and market["months"] == ["2026-11", "2026-12", "2027-01"]
    assert market["routes"]["HKG"] == {"2026-11": {"n": 2, "sum": 9000, "fare_sum": 9000, "min": 4000},
                                       "2027-01": {"n": 1, "sum": 6000, "fare_sum": 6000, "min": 6000}}
    assert len(calls) == 3 * 2 + 3 * 3           # 窗口 2 個月＋行情 3 個月，三條航線
    calls.clear()
    run_scan(scanner.state, tp=counting)
    assert len(calls) == 3 * 2                   # 同一天不再抓行情


def test_market_failure_keeps_previous_and_retries(run_scan, cfg):
    cfg["market"]["months_ahead"] = 2
    state = default_state()
    state["market"] = {"date": "2026-11-01", "at": "2026-11-01T09:00:00+08:00", "months": ["2026-11"], "routes": {}}
    def broken(origin, destination, month, *args, **kwargs):
        if destination == "TYO" and month == "2026-12":
            raise RuntimeError("down")
        return []
    scanner = run_scan(state, tp=broken)
    assert scanner.state["market"]["date"] == "2026-11-01"
    assert any(error.startswith("行情 Travelpayouts TYO 2026-12 失敗") for error in scanner.summary["errors"])


def test_daily_record_rebuilt_from_samples_and_kept_190_days(run_scan):
    state = default_state()
    state["market_daily"] = {"2026-09-01": {"HKG": {"n": 1, "sum": 7000}}, "2026-04-01": {"HKG": {"n": 1, "sum": 1}}}
    scanner = run_scan(state, tp=make_tp({"HKG:2026-11-20_2026-11-23": 4000, "HKG:2026-11-21_2026-11-24": 5000}))
    daily = scanner.state["market_daily"]
    assert daily["2026-11-02"]["HKG"] == {"n": 2, "sum": 9000}
    assert "2026-09-01" in daily and "2026-04-01" not in daily


def test_export_market_pools_by_count(cfg):
    state = default_state()
    state["market"] = {"date": "2026-11-02", "at": NOW.isoformat(), "months": ["2026-11", "2026-12", "2027-01", "2027-02"],
                       "routes": {"HKG": {"2026-11": {"n": 2, "sum": 9000, "fare_sum": 7000, "min": 4000},
                                          "2027-02": {"n": 1, "sum": 6000, "fare_sum": 5000, "min": 6000}}}}
    state["market_daily"] = {"2026-11-01": {"HKG": {"n": 2, "sum": 8000}}, "2026-06-01": {"HKG": {"n": 2, "sum": 12000}},
                             "2026-01-01": {"HKG": {"n": 1, "sum": 1}}}
    routes = {r["id"]: r for r in build_summary(cfg, state, NOW)["routes"]}
    market = routes["HKG"]["market"]
    assert market["next_3m"] == {"total": 4500, "fare": 3500, "n": 2}
    assert market["next_6m"] == {"total": 5000, "fare": 4000, "n": 3}
    assert market["months"][1] == {"month": "2026-12", "total": None, "fare": None, "min": None, "n": 0}
    assert market["past_3m"] == {"total": 4000, "n": 2, "days": 1}
    assert market["past_6m"] == {"total": 5000, "n": 4, "days": 2}
    assert routes["MFM"]["market"]["next_3m"] == {"total": None, "fare": None, "n": 0}
    assert routes["TYO"]["market"]["reference"][0]["source"] == "Kayak"
