from urllib.parse import parse_qs, urlparse

from lowfly.config import load_config
from lowfly.dates import google_url
from lowfly.mock import make_sources
from lowfly.notifier import Telegram
from lowfly.scanner import Scanner
from lowfly.state import default_state
from conftest import NOW


def test_four_routes_and_mixed_airport_pairing(secrets, tmp_path):
    cfg = load_config()
    routes = {r["id"]: r for r in cfg["routes"]}
    assert list(routes) == ["HKG", "MFM", "HKG_MFM", "MFM_HKG"]
    cfg["market"]["months_ahead"] = 0
    cfg["airline_sales"]["enabled"] = False
    cfg["team_report"]["enabled"] = False
    serp, mock_tp = make_sources(NOW, cfg)
    calls = []

    def tp(origin, destination, month, *args, one_way=False):
        calls.append((origin, destination, month, one_way))
        return mock_tp(origin, destination, month, *args, one_way=one_way)

    scanner = Scanner(cfg, secrets, default_state(), Telegram("", "", dry_run=True), NOW,
                      serpapi_fn=serp, tp_fn=tp, output_dir=tmp_path, render_images=False)
    summary = scanner.run()
    assert len(calls) == len(set(calls))
    assert all("TYO" not in call[:2] for call in calls)
    assert all(key.split(":")[0] in ("HKG", "MFM") for key in summary["candidates"])
    for route_id, origin in [("HKG_MFM", "MFM"), ("MFM_HKG", "HKG")]:
        route = routes[route_id]
        assert any(a == origin and b == "TPE" and single for a, b, _, single in calls)
        assert any(key.startswith(route_id + ":") and pair.get("tp_price")
                   for key, pair in scanner.state["pairs"].items())
        url = google_url(cfg, route, "2026-11-14", "2026-11-17")
        assert f"{origin} to TPE 2026-11-17" in parse_qs(urlparse(url).query)["q"][0]
