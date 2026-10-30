"""產生完整專案 ZIP 與逐檔全文（PNG 以完整 Base64 保存）。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import textwrap
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"out", ".venv", "__pycache__", ".pytest_cache", ".git"}


def collect_files() -> list[Path]:
    return sorted(path for path in ROOT.rglob("*") if path.is_file()
                  and not any(part in EXCLUDED for part in path.relative_to(ROOT).parts)
                  and path.name != ".DS_Store")


def section(path: Path) -> int:
    relative = path.relative_to(ROOT).as_posix()
    if relative in ("lowfly/render.py", "lowfly/notifier.py"):
        return 1
    if relative == "lowfly/export.py":
        return 2
    if relative.startswith("docs/") and not relative.startswith("docs/data/"):
        return 3
    if relative.startswith(".github/"):
        return 4
    if relative.startswith("tests/") or relative == "pytest.ini":
        return 5
    if relative.startswith("docs/data/"):
        return 6
    if relative in ("README.md", "FILE_TREE.txt", "TEST_REPORT.md"):
        return 8
    return 0 if relative.startswith("lowfly/") or relative in ("config.yaml", "requirements.txt", "requirements-dev.txt", ".gitignore") else 7


def package(output: Path):
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("輸出目錄須在專案外，避免壓縮檔遞迴包含自身")
    output.mkdir(parents=True, exist_ok=True)
    tree = ROOT / "FILE_TREE.txt"
    tree.touch()
    files = collect_files()
    tree.write_text("lowfly/\n" + "\n".join("  " + path.relative_to(ROOT).as_posix() for path in files) + "\n", encoding="utf-8")
    archive_path = output / "lowfly-project.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "lowfly/" + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(files)
    source_path = output / "lowfly-complete-source.md"
    parts = ["# 低飛 LowFly｜完整檔案內容\n\n依核心機器人、圖片／圖文推播、JSON 匯出、PWA、Actions、測試的順序排列。所有文字檔均為完整內容；兩個 PNG 以完整 Base64 提供，ZIP 已含可直接使用的二進位檔。\n\nBase64 還原方式：將對應程式區塊存為文字，再以 Python 的 `base64.b64decode` 解碼寫入該 PNG 路徑。\n"]
    extensions = {".py":"python", ".js":"javascript", ".cjs":"javascript", ".yaml":"yaml", ".yml":"yaml", ".json":"json", ".webmanifest":"json", ".html":"html", ".css":"css", ".svg":"xml", ".md":"markdown"}
    for path in sorted(files, key=lambda p:(section(p), p.relative_to(ROOT).as_posix())):
        data = path.read_bytes()
        relative = path.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(data).hexdigest()
        parts.append(f"\n## `{relative}`\n\n位元組：{len(data)}；SHA-256：`{digest}`。\n\n")
        if path.suffix == ".png":
            content = "\n".join(textwrap.wrap(base64.b64encode(data).decode("ascii"), 76))
            language = "base64"
        else:
            content = data.decode("utf-8")
            language = extensions.get(path.suffix, "text")
        fence = "`" * max(3, max((len(segment) for segment in content.split() if segment and set(segment) == {"`"}), default=0) + 1)
        parts.append(f"{fence}{language}\n{content}" + ("" if content.endswith("\n") else "\n") + f"{fence}\n")
    source_path.write_text("".join(parts), encoding="utf-8")
    print(f"已打包 {len(files)} 個完整檔案")
    print(archive_path)
    print(source_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT.parent / "release")
    package(parser.parse_args().output)
