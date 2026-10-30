from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from lowfly.config import Secrets, load_config
from lowfly.models import Offer
from lowfly.notifier import Telegram
from lowfly.scanner import Scanner
from lowfly.sources.serpapi_flights import Insights, SearchResult
from lowfly.state import default_state

NOW = datetime(2026, 11, 2, 9, 30, tzinfo=ZoneInfo("Asia/Taipei"))
KEY = "2026-11-14_2026-11-17"
KEY2 = "2026-11-20_2026-11-24"


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("離線驗收不得連線")
    monkeypatch.setattr("requests.sessions.Session.request", blocked)


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def secrets():
    return Secrets("fake-serp", "fake-tp")


def state_with_baseline():
    state = default_state()
    state["typical_ranges"] = [{"at": NOW.isoformat(), "low": 7200, "high": 10000}]
    return state


def make_tp(prices):
    def fetch(origin, destination, month, token, currency="TWD", direct_only=True):
        return [Offer("travelpayouts", *key.split("_"), price, currency, "台灣虎航", True, "https://www.aviasales.com/x", NOW.isoformat())
                for key, price in prices.items() if key.startswith(month)]
    return fetch


def make_serp(prices, calls=None, typical=(7200, 10000)):
    def fetch(origin, destination, outbound, inbound, api_key, currency="TWD", direct_only=True, adults=1):
        key = f"{outbound}_{inbound}"
        if calls is not None:
            calls.append(key)
        price = prices.get(key, 8700)
        offers = [Offer("serpapi", outbound, inbound, price, currency, "長榮航空", True,
                        "https://www.google.com/travel/flights?q=x", NOW.isoformat())]
        return SearchResult(offers, Insights(price, "low", *typical, [[1, 6000], [2, price]]), offers[0].url, 1)
    return fetch


@pytest.fixture
def run_scan(cfg, secrets, tmp_path):
    def run(state=None, tp=None, serp=None, now=NOW, **kwargs):
        tg = kwargs.pop("tg", Telegram("", "", dry_run=True))
        scanner = Scanner(cfg, secrets, state if state is not None else default_state(), tg, now,
                          tp_fn=tp or make_tp({}), serpapi_fn=serp or make_serp({}),
                          output_dir=tmp_path / "out", **kwargs)
        scanner.run()
        return scanner
    return run
