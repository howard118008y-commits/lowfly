"""Telegram 圖文傳送：成功才寫通知狀態，無金鑰則只預覽。"""
from __future__ import annotations

import html
import logging
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)


def fmt_money(value: float, currency: str = "TWD") -> str:
    prefix = {"TWD": "NT$", "USD": "US$", "HKD": "HK$", "MOP": "MOP$"}.get(currency.upper(), currency)
    rounded = int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{prefix} {rounded:,}"


def fmt_range(low: float | None, high: float | None, currency: str = "TWD") -> str:
    return "—" if low is None or high is None else f"{fmt_money(low, currency)}～{fmt_money(high, currency).split(' ', 1)[1]}"


def fmt_pct(ratio: float) -> str:
    value = ((Decimal(str(ratio)) - 1) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(value):+d}%"


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def safe_url(value: str) -> str:
    parsed = urlparse(str(value))
    return str(value) if parsed.scheme == "https" and parsed.netloc else ""


def link(value: str, label: str = "連結") -> str:
    return f'<a href="{esc(safe_url(value))}">{esc(label)}</a>' if safe_url(value) else "連結暫無"


class Telegram:
    def __init__(self, token: str, chat_id: str, dry_run: bool = False):
        self.token, self.chat_id, self.dry_run = token, chat_id, dry_run
        self.sent: list[str] = []

    @property
    def preview(self) -> bool:
        return self.dry_run or not self.token or not self.chat_id

    def _post(self, method: str, **kwargs) -> bool:
        try:
            response = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", timeout=30, **kwargs)
            data = response.json()
            if response.status_code != 200 or not isinstance(data, dict) or data.get("ok") is not True:
                log.error("Telegram %s 失敗（HTTP %s）", method, response.status_code)
                return False
            return True
        except Exception as exc:
            log.error("Telegram %s 失敗（%s）", method, type(exc).__name__)
            return False

    def send(self, text_html: str) -> bool:
        self.sent.append(text_html)
        if self.preview:
            print("\n[Telegram 預覽]\n" + text_html)
            return self.dry_run
        if len(text_html) <= 4096:
            parts = [text_html]
        else:
            # 極長訊息退成完整純文字片段，避免在 HTML 標籤中間截斷。
            plain = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r'\2（\1）', text_html)
            plain = html.unescape(re.sub(r"<[^>]+>", "", plain))
            parts = [esc(plain[i:i + 3500]) for i in range(0, len(plain), 3500)]
        for part in parts:
            if not self._post("sendMessage", json={"chat_id": self.chat_id, "text": part,
                                                   "parse_mode": "HTML", "disable_web_page_preview": True}):
                return False
        return True

    def send_photo(self, png_path: str | Path | None, caption_html: str) -> bool:
        path = Path(png_path) if png_path else None
        if path is None or not path.is_file():
            return self.send(caption_html)
        if self.preview:
            print(f"圖片預覽：{path}")
            return self.send(caption_html)
        short = caption_html if len(caption_html) <= 1024 else "<b>低飛 LowFly</b>｜完整摘要見下一則訊息。"
        try:
            with path.open("rb") as photo:
                ok = self._post("sendPhoto", data={"chat_id": self.chat_id, "caption": short, "parse_mode": "HTML"},
                                files={"photo": (path.name, photo, "image/png")})
        except OSError:
            ok = False
        if not ok:
            return self.send(caption_html)
        if len(caption_html) > 1024:
            return self.send(caption_html)
        self.sent.append(caption_html)
        return True
