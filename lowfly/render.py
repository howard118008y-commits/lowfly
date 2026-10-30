"""以 Pillow 產生 1200×675 卡片；字體失敗時仍可完成圖片。"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .dates import date_pairs, fmt_date, pair_key
from .notifier import fmt_money, fmt_pct

log = logging.getLogger(__name__)
FONT_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
BOLD_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
DEJAVU_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
SIZE = (1200, 675)
INK, MUTED, GREEN = "#173B34", "#657971", "#168261"


def load_font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(str(BOLD_PATH if bold else FONT_PATH), size)
    except OSError:
        log.warning("Noto Sans CJK 字體不存在；退回 DejaVu，部分中文字可能無法顯示")
        try:
            return ImageFont.truetype(str(DEJAVU_PATH), size)
        except OSError:
            return ImageFont.load_default(size=size)


def fitted(draw, text: str, size: int, max_width: int, bold: bool = False):
    font = load_font(size, bold)
    while size > 12 and draw.textlength(text, font=font) > max_width:
        size -= 2
        font = load_font(size, bold)
    return font


def draw_text(draw, xy, text: str, size: int, color=INK, width: int = 1060, bold=False):
    draw.text(xy, text, fill=color, font=fitted(draw, text, size, width, bold))


def ratio_color(ratio: float | None) -> str:
    if ratio is None:
        return "#FFFFFF"
    if ratio <= 0.5:
        return "#116246"
    if ratio <= 0.7:
        return "#58B990"
    if ratio <= 0.85:
        return "#C5E8D3"
    if ratio <= 1:
        return "#E7EBE8"
    return "#F7DCD9"


def sparkline(draw, points: list, box: tuple[int, int, int, int]):
    values = [float(point[1]) for point in points if isinstance(point, (list, tuple)) and len(point) >= 2 and isinstance(point[1], (int, float))]
    if len(values) < 2:
        return
    x0, y0, x1, y1 = box
    low, high = min(values), max(values)
    coords = [(x0 + i * (x1 - x0) / (len(values) - 1), y1 - (v - low) / (high - low or 1) * (y1 - y0)) for i, v in enumerate(values)]
    draw.line(coords, fill=GREEN, width=4)
    x, y = coords[-1]
    draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=GREEN)


def render_alert(offer, baseline, cfg: dict, state: dict, output_dir: Path) -> Path:
    image = Image.new("RGB", SIZE, "#F5F8F3")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, 1172, 647), 28, fill="white", outline="#DFE8DF", width=2)
    draw_text(draw, (65, 56), cfg["app_name"], 36, bold=True, width=850)
    draw.rounded_rectangle((1003, 58, 1127, 110), 16, fill=GREEN)
    draw_text(draw, (1030, 61), "神票", 30, "white", width=100)
    draw_text(draw, (65, 148), f"{cfg['route']['label']} 直飛來回 · {offer.nights} 晚", 36)
    draw_text(draw, (65, 207), f"{fmt_date(offer.outbound)} → {fmt_date(offer.inbound)}", 36)
    draw_text(draw, (60, 282), fmt_money(offer.price), 120, width=810, bold=True)
    draw_text(draw, (875, 325), fmt_pct(baseline.ratio(offer.price)), 72, GREEN, width=270, bold=True)
    draw_text(draw, (65, 447), f"基準 {fmt_money(baseline.value)} · {offer.airline}", 32, MUTED)
    history = state.get("pairs", {}).get(offer.pair_key, {}).get("price_history", [])
    sparkline(draw, history, (68, 525, 1128, 600))
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"alert_{offer.pair_key}.png"
    image.save(path, "PNG")
    return path


def dashed_box(draw, box, color="#C7D2CA"):
    x0, y0, x1, y1 = box
    for x in range(x0, x1, 8):
        draw.line((x, y0, min(x + 4, x1), y0), fill=color)
        draw.line((x, y1, min(x + 4, x1), y1), fill=color)
    for y in range(y0, y1, 8):
        draw.line((x0, y, x0, min(y + 4, y1)), fill=color)
        draw.line((x1, y, x1, min(y + 4, y1)), fill=color)


def render_digest(cfg: dict, state: dict, now: datetime, baseline, tp_count: int, output_dir: Path) -> Path:
    image = Image.new("RGB", SIZE, "#FAFCF8")
    draw = ImageDraw.Draw(image)
    draw_text(draw, (40, 26), f"{cfg['app_name']} · 每日摘要 {fmt_date(now.date())}", 34, bold=True)
    draw_text(draw, (40, 85), f"基準 {fmt_money(baseline.value)}" if baseline else "基準：尚未取得 Google 典型區間", 28, MUTED)
    win = cfg["window"]
    pairs = date_pairs(now.date(), win["days_ahead"], win["min_lead_days"], win["stay_nights"])
    dates = list(dict.fromkeys(out for out, _ in pairs))
    cw, ch, left, top = 1080 / len(dates), 90, 76, 223
    nights = win["stay_nights"]
    for column, out in enumerate(dates):
        x = left + column * cw
        if out.weekday() >= 5:
            draw.rectangle((int(x), 169, int(x + cw), int(top + ch * len(nights))), fill="#FFF3CB")
        label = f"{out.month}/{out.day}"
        draw_text(draw, (x + 1, 185), label, 14, MUTED, width=int(cw - 2))
        for row, stay in enumerate(nights):
            back = next(b for o, b in pairs if o == out and (b - o).days == stay)
            p = state.get("pairs", {}).get(pair_key(out, back), {})
            verified = p.get("last_price") is not None
            price = p.get("last_price") if verified else p.get("tp_price")
            ratio = baseline.ratio(price) if baseline and price is not None else None
            box = (int(x + 2), int(top + row * ch + 2), int(x + cw - 2), int(top + (row + 1) * ch - 4))
            draw.rectangle(box, fill=ratio_color(ratio))
            if price is None:
                dashed_box(draw, box)
            else:
                color = "white" if ratio is not None and ratio <= 0.5 else INK
                draw_text(draw, (x + 4, top + row * ch + 25), f"{price / 1000:.1f}k", 14, color, width=int(cw - 6), bold=True)
                if verified:
                    draw_text(draw, (x + cw / 2 - 5, top + row * ch + 50), "✓", 14, color, width=20)
    for row, stay in enumerate(nights):
        draw_text(draw, (16, top + row * ch + 28), f"{stay}晚", 20, MUTED, width=52)
    labels = [("≤50%", .5), ("≤70%", .7), ("≤85%", .85), ("≤100%", 1), (">100%", 1.1), ("無資料", None)]
    for i, (label, ratio) in enumerate(labels):
        x = 70 + i * 179
        draw.rectangle((x, 542, x + 24, 566), fill=ratio_color(ratio), outline="#C7D2CA")
        draw_text(draw, (x + 33, 540), label, 19, MUTED, width=140)
    quota = cfg["sources"]["serpapi"]["monthly_quota"]
    footer = f"SerpAPI 本月 {state['serpapi']['used_month']}/{quota} · Travelpayouts {tp_count} 組 · 更新 {now.month}/{now.day} {now:%H:%M}"
    draw_text(draw, (40, 610), footer, 22, MUTED)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"digest_{now.date().isoformat()}.png"
    image.save(path, "PNG")
    return path
