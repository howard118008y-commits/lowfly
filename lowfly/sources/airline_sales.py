"""廉航促銷消息：Google 新聞 RSS、PTT 板內搜尋、香港快運官網首頁的促銷頁連結。只取標題、時間、連結。

虎航、酷航、樂桃、捷星、ZIPAIR 官網需 JS 或擋爬蟲（2026-11-04 實測），只能靠新聞與 PTT；香港快運首頁是 SSR，可直接讀促銷頁 slug。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import quote

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LowFly/1.0; +https://github.com/howard118008y-commits/lowfly)"}
PTT_POST = re.compile(r'<div class="title">\s*<a href="(/bbs/[^"]+/M\.(\d+)\.[^"]+)">([^<]+)</a>')
HKX_SLUG = re.compile(r"/offers/promotions/([a-z0-9_-]+)")
MAX_BYTES = 3_000_000   # 香港快運首頁約 0.9MB；超過就當異常，不無限制讀進記憶體


def _get(url: str, timeout: int, **kwargs) -> bytes:
    with requests.get(url, headers=HEADERS, timeout=timeout, stream=True, **kwargs) as response:
        response.raise_for_status()
        body = b""
        for chunk in response.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                raise ValueError(f"回應超過 {MAX_BYTES:,} bytes")
    return body


def google_news(query: str, timeout: int = 20) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    items = []
    for item in ET.fromstring(_get(url, timeout)).iter("item"):
        link = item.findtext("link") or ""
        try:
            at = parsedate_to_datetime(item.findtext("pubDate")).isoformat()
        except (TypeError, ValueError):
            continue   # 沒有發布時間就無法判斷是不是舊聞，略過
        items.append({"id": "news:" + (item.findtext("guid") or link), "title": item.findtext("title") or "", "url": link,
                      "at": at, "source": "Google 新聞"})
    return items


def ptt_search(board: str, query: str, timeout: int = 20) -> list[dict]:
    """板內標題搜尋；網址的 M.<epoch> 就是發文時間。回文（Re:）與轉文（Fw:）不算。"""
    page = _get(f"https://www.ptt.cc/bbs/{board}/search", timeout, params={"q": query}, cookies={"over18": "1"}).decode("utf-8", "replace")
    return [{"id": "ptt:" + path, "title": unescape(title.strip()), "url": "https://www.ptt.cc" + path,
             "at": datetime.fromtimestamp(int(epoch), timezone.utc).isoformat(), "source": f"PTT {board}"}
            for path, epoch, title in PTT_POST.findall(page) if not title.lstrip().startswith(("Re:", "Fw:"))]


def hk_express(timeout: int = 30) -> list[dict]:
    """首頁橫幅連到的促銷頁；slug 本身就是標題（例：twinbound_flashsale_20261020），沒有發布時間。"""
    page = _get("https://www.hkexpress.com/zh-tw", timeout).decode("utf-8", "replace")
    return [{"id": "hkexpress:" + slug, "title": re.sub(r"[_-]+", " ", slug), "official": True, "at": None,
             "url": f"https://www.hkexpress.com/zh-tw/offers/promotions/{slug}", "source": "香港快運官網"}
            for slug in sorted(set(HKX_SLUG.findall(page)))]


def fetch(source: str) -> list[dict]:
    """config 的來源字串：news:<關鍵字>、ptt:<板名>:<關鍵字>、hkexpress。"""
    kind, _, arg = source.partition(":")
    if kind == "news":
        return google_news(f"{arg} (促銷 OR 開賣 OR 優惠) when:3d")
    if kind == "ptt":
        board, _, query = arg.partition(":")
        return ptt_search(board, query)
    if kind == "hkexpress":
        return hk_express()
    raise ValueError(f"未知的促銷消息來源 {source}")


def is_sale(conf: dict, airline: dict, item: dict) -> bool:
    """標題要有促銷字眼、不含排除字（信用卡、股市…），而且提到這家航空（官網來源免）。"""
    title = item["title"].lower()
    if any(word.lower() in title for word in conf.get("exclude", [])):
        return False
    if not any(word.lower() in title for word in conf["keywords"]):
        return False
    return bool(item.get("official")) or any(name.lower() in title for name in airline["match"])
