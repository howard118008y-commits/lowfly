"""JSON 狀態以原子取代寫入；毀損檔案不自動歸零，以免重置額度。"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from .config import ROOT, deep_merge

STATE_PATH = ROOT / "data/state.json"
HISTORY_PATH = ROOT / "data/history.jsonl"
log = logging.getLogger(__name__)


def default_state() -> dict:
    return {"version": 1, "serpapi": {"month": "", "used_month": 0, "day": "", "used_day": 0},
            "pairs": {}, "typical_ranges": [], "alerts": {}, "alert_history": [],
            "digest_pool": {"items": {}}, "last_digest_date": "",
            "stats": {"alerts_sent": 0, "digests_sent": 0, "runs": 0}}


def load_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return default_state()
    return deep_merge(default_state(), json.loads(path.read_text(encoding="utf-8")))


def write_json(value: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_state(st: dict, path: Path = STATE_PATH) -> None:
    write_json(st, path)


def append_history(rows: list[dict], path: Path = HISTORY_PATH) -> None:
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def read_history(path: Path = HISTORY_PATH) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except ValueError:
            log.warning("忽略 history.jsonl 第 %d 行毀損紀錄", line_number)
    return rows


def prune_typical_ranges(st: dict, keep: int = 400) -> None:
    st["typical_ranges"] = st.get("typical_ranges", [])[-keep:]
