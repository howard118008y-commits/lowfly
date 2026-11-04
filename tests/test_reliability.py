"""失敗要看得見：TP 暫時性錯誤重試、TP 全掛不寫入、Telegram 失敗讓 workflow 標紅、state 結構錯誤不覆寫。"""
import json
from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
import requests

from lowfly import main as lowfly_main
from lowfly.models import Offer
from lowfly.sources import travelpayouts
from lowfly.state import load_state

BODY = {"success": True, "data": [{"departure_at": "2026-11-14T09:00:00+08:00", "return_at": "2026-11-17T09:00:00+08:00",
                                   "price": 3980, "airline": "NX", "transfers": 0, "return_transfers": 0, "link": "/search/x"}]}


@pytest.fixture
def no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(travelpayouts.time, "sleep", waits.append)
    return waits


def test_tp_retries_network_errors_and_5xx(monkeypatch, no_sleep):
    ok = Mock(status_code=200, json=lambda: BODY)
    get = Mock(side_effect=[requests.ConnectionError(), Mock(status_code=503), ok])
    monkeypatch.setattr(travelpayouts.requests, "get", get)
    assert len(travelpayouts.fetch_month("TPE", "MFM", "2026-11", "fake")) == 1
    assert get.call_count == 3 and no_sleep == [2, 5]


def test_tp_gives_up_after_three_tries(monkeypatch, no_sleep):
    get = Mock(side_effect=requests.Timeout())
    monkeypatch.setattr(travelpayouts.requests, "get", get)
    assert travelpayouts.fetch_month("TPE", "MFM", "2026-11", "fake") == [] and get.call_count == 3


def test_tp_does_not_retry_auth_errors(monkeypatch, no_sleep):
    response = Mock(status_code=401)
    response.raise_for_status.side_effect = requests.HTTPError()
    get = Mock(return_value=response)
    monkeypatch.setattr(travelpayouts.requests, "get", get)
    assert travelpayouts.fetch_month("TPE", "MFM", "2026-11", "fake") == [] and get.call_count == 1 and no_sleep == []


@pytest.fixture
def prod_like(monkeypatch, tmp_path):
    """正式模式跑 main：輸出到 tmp_path，時間固定在每日摘要之前（不渲染圖片），不連網（促銷消息會失敗後略過）。"""
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "fake-tp")
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setattr(lowfly_main, "now_local", lambda tz: datetime(2026, 11, 2, 3, 17, tzinfo=ZoneInfo(tz)))
    state_path = tmp_path / "data/state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"stats": {"alerts_sent": 0, "digests_sent": 0, "runs": 7}}), encoding="utf-8")
    return state_path


def test_tp_returning_nothing_fails_without_writing(monkeypatch, prod_like, tmp_path):
    monkeypatch.setattr(travelpayouts, "fetch_month", lambda *a, **k: [])
    before = prod_like.read_text(encoding="utf-8")
    assert lowfly_main.main(["--output-root", str(tmp_path)]) == 1
    assert prod_like.read_text(encoding="utf-8") == before and not (tmp_path / "docs/data").exists()


def test_telegram_failure_persists_then_returns_3(monkeypatch, prod_like, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    offer = Offer("travelpayouts", "2026-11-14", "2026-11-17", 3000, "TWD", "台灣虎航", True, "https://www.aviasales.com/x",
                  "2026-11-02T03:17:00+08:00", airline_code="IT")
    monkeypatch.setattr(travelpayouts, "fetch_month", lambda o, d, *a, **k: [offer] if d == "MFM" and not k.get("one_way") else [])
    import lowfly.scanner
    monkeypatch.setattr(lowfly.scanner.Scanner, "_deliver", lambda self, text, *a: self.tg.send(text))   # 不渲染圖片
    assert lowfly_main.main(["--output-root", str(tmp_path)]) == 3   # MFM 好價線 5,000：3,000＋行李會推播，但送不出去
    assert load_state(prod_like)["stats"]["runs"] == 8 and (tmp_path / "docs/data/summary.json").exists()


def test_state_with_wrong_types_is_rejected(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"pairs": [], "stats": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="pairs"):
        load_state(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_state(path)


def workflow(name):
    import yaml
    from pathlib import Path
    return yaml.safe_load((Path(__file__).resolve().parents[1] / f".github/workflows/{name}").read_text(encoding="utf-8"))


def test_scan_workflow_alerts_on_failure_and_retries_push():
    steps = {step.get("name"): step for step in workflow("scan.yml")["jobs"]["scan"]["steps"]}
    assert steps["失敗告警"]["if"] == "failure()" and "sendMessage" in steps["失敗告警"]["run"]
    assert "for attempt in 1 2 3" in steps["儲存狀態與公開資料"]["run"]
    assert "telegram_failed=true" in steps["執行掃描"]["run"] and steps["Telegram 推播失敗時標紅"]["run"] == "exit 1"
    names = list(steps)
    assert names.index("儲存狀態與公開資料") < names.index("Telegram 推播失敗時標紅") < names.index("失敗告警")


def test_watchdog_is_least_privilege_and_has_no_inline_expressions():
    wd = workflow("watchdog.yml")
    assert wd["permissions"] == {"actions": "write", "contents": "read"}
    assert wd[True]["schedule"] == [{"cron": "43 */2 * * *"}]   # PyYAML 把 on 讀成 True
    for name in ("scan.yml", "watchdog.yml"):
        for job in workflow(name)["jobs"].values():
            for step in job["steps"]:
                assert "${{" not in step.get("run", ""), f"{name}「{step.get('name')}」的 run 內不可直接插入表達式，改用 env"
