"""推播附「改一天」：去或回前後挪一天，列出最便宜的組合與差價。"""
import pytest

from lowfly.config import Secrets
from lowfly.dates import fmt_date
from lowfly.state import default_state

from conftest import make_tp


@pytest.fixture
def secrets():
    return Secrets("", "fake-tp")   # 無 SerpApi：TP 快取價直接判斷


@pytest.fixture
def cfg(cfg):
    cfg["routes"][0]["good_price_twd"] = 4500   # HKG
    return cfg


def alert_for(scanner, price):
    return next(text for text in scanner.tg.sent if f"NT$ {price:,}</b>" in text)


def test_cheaper_neighbor_shows_saving(run_scan):
    tp = make_tp({"HKG:2026-11-14_2026-11-17": 4200, "HKG:2026-11-15_2026-11-17": 3900, "HKG:2026-11-13_2026-11-16": 4400,
                  "HKG:2026-11-25_2026-11-28": 4100})
    scanner = run_scan(default_state(), tp=tp)
    assert (f"🔁 改一天：晚一天出發（{fmt_date('2026-11-15')}→{fmt_date('2026-11-17')}）NT$ 3,900，省 NT$ 300\n"
            in alert_for(scanner, 4200))
    assert (f"🔁 改一天最便宜：早一天出發（{fmt_date('2026-11-14')}→{fmt_date('2026-11-17')}）NT$ 4,200，多 NT$ 300\n"
            in alert_for(scanner, 3900))
    assert "🔁" not in alert_for(scanner, 4100)   # 前後一天都沒有價格就不列
