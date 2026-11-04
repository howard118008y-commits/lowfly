"""團隊週報：週一 09:00 後第一輪送一次，依四個角色整理過去 7 天；送失敗下一輪再試。"""
from datetime import timedelta

import pytest

from lowfly.config import Secrets
from lowfly.notifier import Telegram
from lowfly.state import default_state

from conftest import NOW, make_tp


@pytest.fixture
def secrets():
    return Secrets("", "fake-tp")


@pytest.fixture
def cfg(cfg):
    cfg["team_report"]["enabled"] = True
    cfg["routes"][0]["good_price_twd"] = 4500   # HKG
    return cfg


def report(scanner):
    return next((text for text in scanner.tg.sent if "團隊週報" in text), None)


def alert(route, price, ratio, hours_ago):
    return {"pair_key": f"{route}:2026-11-20_2026-11-24", "route_id": route, "price": price, "ratio": ratio,
            "outbound": "2026-11-20", "inbound": "2026-11-24", "at": (NOW - timedelta(hours=hours_ago)).isoformat()}


TP = make_tp({"HKG:2026-11-14_2026-11-17": 6000, "TYO:2026-11-20_2026-11-24": 9500})


def test_first_report_lists_four_roles_and_saves_snapshot(run_scan):
    state = default_state()
    state["alert_history"] = [alert("HKG", 3000, .45, 5), alert("HKG", 4400, .8, 30), alert("TYO", 8000, .7, 50),
                              alert("HKG", 4000, .5, 24 * 8)]   # 最後一則超過 7 天
    state["sales_log"] = [{"at": (NOW - timedelta(days=1)).isoformat(), "count": 4},
                          {"at": (NOW - timedelta(days=9)).isoformat(), "count": 9}]
    state["stats"]["runs"] = 20
    scanner = run_scan(state, tp=TP)
    text = report(scanner)
    assert text.startswith("🗼 <b>LowFly 團隊週報</b> 11/2（一）\n\n🧭 <b>領航員｜票價</b>\n• 本週推播 3 則（神票 1、好價 1、新低 1）\n")
    assert "• 香港最低 NT$ 6,000\n" in text and "• 澳門：本輪沒有快取價\n" in text
    assert "🔭 <b>瞭望員｜促銷</b>\n• 本週推出促銷消息 4 則" in text
    assert "第一份週報，下週起比較掃描輪數（排程每週約 28 輪）" in text   # conftest 拿掉促銷月：每天 4 輪
    assert "🗼 <b>塔台</b>\n• 航線新低：已累積 1 天紀錄，滿 7 天後啟動" in text
    assert state["team_report"] == {"date": "2026-11-02", "runs": 20, "lows": {"HKG": 6000, "TYO": 9500}}
    assert report(run_scan(state, tp=TP, now=NOW + timedelta(hours=6))) is None   # 同一天不再送


def test_next_week_compares_with_snapshot(run_scan):
    state = default_state()
    state["stats"]["runs"] = 40
    state["team_report"] = {"date": "2026-10-26", "runs": 30, "lows": {"HKG": 6500}}
    text = report(run_scan(state, tp=TP))
    assert "• 香港最低 NT$ 6,000（上週 NT$ 6,500）\n" in text and "• 東京最低 NT$ 9,500\n" in text
    assert "• 本週成功掃描 10 輪（排程應有約 28 輪）　⚠️ 偏少，可能是 GitHub 排程延遲或掃描失敗" in text


def test_only_on_report_day_after_hour_and_retries_after_failure(run_scan):
    assert report(run_scan(default_state(), tp=TP, now=NOW + timedelta(days=1))) is None   # 週二
    assert report(run_scan(default_state(), tp=TP, now=NOW - timedelta(hours=1))) is None   # 週一 08:30

    class Down(Telegram):
        def send(self, text_html):
            self.sent.append(text_html)
            return False
    state = default_state()
    run_scan(state, tp=TP, tg=Down("", "", dry_run=True))
    assert "team_report" not in state
    assert report(run_scan(state, tp=TP, now=NOW + timedelta(hours=3)))
