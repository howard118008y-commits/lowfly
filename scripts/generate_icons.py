"""重製原創紙飛機圖示（登機證配色：墨藍底、紙白機身、印章紅箭頭）；不需要 SVG 轉檔額外依賴。"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    scale = 4
    image = Image.new("RGB", (512 * scale, 512 * scale), "#1B2430")
    draw = ImageDraw.Draw(image)
    def polygon(points, fill):
        draw.polygon([(x * scale, y * scale) for x, y in points], fill=fill)
    polygon([(112, 156), (394, 120), (284, 306), (248, 239)], "#FAFBFC")
    polygon([(248, 239), (394, 120), (209, 214)], "#C9CED4")
    for points in ([(169, 302), (169, 389)], [(133, 353), (169, 389), (205, 353)]):
        draw.line([(x * scale, y * scale) for x, y in points], fill="#C2361F", width=22 * scale, joint="curve")
    folder = ROOT / "docs/icons"
    folder.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        image.resize((size, size), Image.Resampling.LANCZOS).save(folder / f"icon-{size}.png")


if __name__ == "__main__":
    main()
