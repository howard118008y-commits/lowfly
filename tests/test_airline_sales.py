"""廉航促銷消息：Google 新聞 RSS／PTT 搜尋／香港快運首頁解析，與「新的、近期的、像促銷的才推」。"""
from datetime import timedelta

import pytest

from lowfly.config import Secrets
from lowfly.notifier import Telegram
from lowfly.sources import airline_sales
from lowfly.state import default_state

from conftest import NOW

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>台灣虎航ITF線上旅展全航線單程未稅999元起 - UDN</title><link>https://news.google.com/rss/articles/a</link>
<guid>CBMi-a</guid><pubDate>Mon, 02 Nov 2026 10:14:22 GMT</pubDate></item>
</channel></rss>"""
PTT = """<div class="r-ent"><div class="title">
<a href="/bbs/Japan_Travel/M.1793613790.A.1F2.html">[資訊] 台灣虎航 27夏 第二波開賣（11/3 ~ 11/4</a></div></div>
<div class="r-ent"><div class="title"><a href="/bbs/Japan_Travel/M.1793613800.A.1F3.html">Re: [資訊] 台灣虎航 27夏</a></div></div>"""
HKX = '<a href="/zh-tw/offers/promotions/twinbound_flashsale_20261020">x</a><a href="/zh-tw/offers/promotions/cathay-member-limited-bonus-miles-offer">'


class FakeResponse:
    def __init__(self, text):
        self.body = text.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        return (self.body[i:i + size] for i in range(0, len(self.body), size))


def test_parsers(monkeypatch):
    pages = {"news.google.com": RSS, "www.ptt.cc": PTT, "www.hkexpress.com": HKX}
    monkeypatch.setattr(airline_sales.requests, "get", lambda url, **k: FakeResponse(next(v for h, v in pages.items() if h in url)))
    [news] = airline_sales.fetch("news:虎航")
    assert news == {"id": "news:CBMi-a", "title": "台灣虎航ITF線上旅展全航線單程未稅999元起 - UDN", "url": "https://news.google.com/rss/articles/a",
                    "at": "2026-11-02T10:14:22+00:00", "source": "Google 新聞"}
    [post] = airline_sales.fetch("ptt:Japan_Travel:虎航")   # 回文不算
    assert post["title"] == "[資訊] 台灣虎航 27夏 第二波開賣（11/3 ~ 11/4" and post["at"].startswith("2026-11-02")
    assert post["url"] == "https://www.ptt.cc/bbs/Japan_Travel/M.1793613790.A.1F2.html"
    slugs = airline_sales.fetch("hkexpress")
    assert [s["title"] for s in slugs] == ["cathay member limited bonus miles offer", "twinbound flashsale 20261020"]
    assert all(s["official"] and s["at"] is None for s in slugs)


@pytest.fixture
def secrets():
    return Secrets("", "")   # 不抓票價，只看促銷消息


@pytest.fixture
def cfg(cfg):
    cfg["airline_sales"]["enabled"] = True
    return cfg


def item(id, title, hours_ago=1, **extra):
    return {"id": id, "title": title, "url": f"https://example.test/{id}", "at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "source": "Google 新聞", **extra}


def feed(by_source):
    def fetch(source):
        value = by_source.get(source, [])
        if isinstance(value, Exception):
            raise value
        return value
    return fetch


def sales_messages(scanner):
    return [text for text in scanner.tg.sent if text.startswith("🏷️")]


def test_new_recent_sales_push_once(run_scan):
    state = default_state()
    first = run_scan(state, sales_fn=feed({"news:虎航": [item("a", "虎航 1599 元起限時開賣")]}))
    assert sales_messages(first)[0].startswith("🏷️ <b>廉航促銷消息</b>\n<b>台灣虎航</b>\n• 虎航 1599 元起限時開賣") and "a" in state["sales_seen"]
    second = run_scan(state, sales_fn=feed({
        "news:虎航": [item("a", "虎航 1599 元起限時開賣"), item("b", "台灣虎航旅展單程 999 元起 - UDN", hours_ago=2),
                     item("c", "虎航促銷報喜 股價漲"), item("d", "虎航 999 元起", hours_ago=60), item("e", "虎航新增航點")],
        "hkexpress": [{"id": "hkexpress:x", "title": "twinbound flashsale 20261020", "official": True, "at": None,
                       "url": "https://www.hkexpress.com/zh-tw/offers/promotions/x", "source": "香港快運官網"},
                      {"id": "hkexpress:y", "title": "cathay member bonus miles offer", "official": True, "at": None,
                       "url": "https://www.hkexpress.com/zh-tw/offers/promotions/y", "source": "香港快運官網"}],
        "news:酷航": RuntimeError("blocked")}))
    [text] = sales_messages(second)
    assert text.startswith("🏷️ <b>廉航促銷消息</b>\n<b>台灣虎航</b>\n• 台灣虎航旅展單程 999 元起 - UDN（Google 新聞，11/02 07:30）")
    assert "<b>香港快運</b>\n• twinbound flashsale 20261020（香港快運官網）" in text
    for skipped in ("1599", "股價", "新增航點", "miles"):   # 已推過、排除字、沒有促銷字眼、官網非促銷
        assert skipped not in text
    assert second.summary["sales_news"] == 2
    assert run_scan(state, sales_fn=feed({"news:虎航": [item("b", "台灣虎航旅展單程 999 元起")]})).summary["sales_news"] == 0


def test_more_than_three_items_are_folded(run_scan):
    state = default_state()
    news = [item(str(i), f"虎航全航線 999 元起開搶 第 {i} 家媒體", hours_ago=i) for i in range(1, 6)]
    [text] = sales_messages(run_scan(state, sales_fn=feed({"news:虎航": news})))
    assert text.count("\n• ") == 3 and "第 1 家" in text and "第 4 家" not in text and "　另有 2 則" in text


def test_seen_entries_expire_after_keep_days(run_scan, cfg):
    state = default_state()
    state["sales_seen"] = {"old": (NOW - timedelta(days=31)).isoformat(), "new": (NOW - timedelta(days=29)).isoformat()}
    run_scan(state, sales_fn=feed({}))
    assert list(state["sales_seen"]) == ["new"]


def test_failed_send_retries_next_run(run_scan):
    class Down(Telegram):
        def send(self, text_html):
            self.sent.append(text_html)
            return False
    state = default_state()
    run_scan(state, sales_fn=feed({"news:虎航": [item("a", "虎航限時開賣")]}), tg=Down("", "", dry_run=True))
    assert state["sales_seen"] == {}
    assert sales_messages(run_scan(state, sales_fn=feed({"news:虎航": [item("a", "虎航限時開賣")]})))


def test_same_story_listed_once_and_timeless_pages_do_not_expire(run_scan):
    state = default_state()
    story = item("s", "虎航、樂桃旅展開賣 999 元起")
    [text] = sales_messages(run_scan(state, sales_fn=feed({"news:虎航": [story], "news:樂桃": [story]})))
    assert text.count("旅展開賣") == 1
    page = {"id": "hkexpress:p", "title": "flash sale page", "official": True, "at": None, "url": "https://example.test/p", "source": "香港快運官網"}
    state["sales_seen"] = {"hkexpress:p": (NOW - timedelta(days=29)).isoformat()}
    run_scan(state, sales_fn=feed({"hkexpress": [page]}))
    assert state["sales_seen"]["hkexpress:p"] == NOW.isoformat(timespec="seconds")   # 還掛著就續期
    assert sales_messages(run_scan(state, sales_fn=feed({"hkexpress": [page]}), now=NOW + timedelta(days=2))) == []


def test_long_message_drops_items_to_fit(run_scan):
    long = lambda code, i: {**item(f"{code}{i}", f"{code} 限時開賣 999 元起 " + "很長的標題" * 30, hours_ago=i),
                            "url": "https://news.google.com/rss/articles/" + "x" * 300}
    by_source = {src: [long(name, i) for i in range(1, 4)] for src, name in
                 (("news:虎航", "虎航"), ("news:香港快運", "香港快運"), ("news:酷航", "酷航"), ("news:樂桃", "樂桃"), ("news:捷星", "捷星"))}
    [text] = sales_messages(run_scan(default_state(), sales_fn=feed(by_source)))
    assert len(text) <= 4096 and "另有" in text


def test_oversized_response_is_rejected(monkeypatch):
    monkeypatch.setattr(airline_sales.requests, "get", lambda url, **k: FakeResponse("x" * (airline_sales.MAX_BYTES + 1)))
    with pytest.raises(ValueError, match="回應超過"):
        airline_sales.fetch("hkexpress")
