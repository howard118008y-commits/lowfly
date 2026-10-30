"""重製原創紙飛機圖示；不需要 SVG 轉檔額外依賴。"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    scale = 4
    image = Image.new("RGB", (512 * scale, 512 * scale), "#56463b")
    draw = ImageDraw.Draw(image)
    def polygon(points, fill):
        draw.polygon([(x * scale, y * scale) for x, y in points], fill=fill)
    polygon([(112, 156), (394, 120), (284, 306), (248, 239)], "#f7f0e4")
    polygon([(248, 239), (394, 120), (209, 214)], "#c6a781")
    for points in ([(169, 302), (169, 389)], [(133, 353), (169, 389), (205, 353)]):
        draw.line([(x * scale, y * scale) for x, y in points], fill="#c6a781", width=22 * scale, joint="curve")
    folder = ROOT / "docs/icons"
    folder.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        image.resize((size, size), Image.Resampling.LANCZOS).save(folder / f"icon-{size}.png")


if __name__ == "__main__":
    main()
