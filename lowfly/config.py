"""載入唯讀設定與環境變數；前端不接觸金鑰。"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        result[key] = deep_merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def load_config(path: str | Path | None = None, overrides_path: str | Path | None = None) -> dict:
    cfg = yaml.safe_load(Path(path or ROOT / "config.yaml").read_text(encoding="utf-8"))
    # 僅供本機相容附錄 A；PWA 不提供覆寫或 PAT 寫入功能。
    if overrides_path and Path(overrides_path).exists():
        cfg = deep_merge(cfg, json.loads(Path(overrides_path).read_text(encoding="utf-8")))
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict) -> None:
    win, thr, sc = cfg["window"], cfg["thresholds"], cfg["sources"]["serpapi"]
    if not 1 <= int(win["min_lead_days"]) <= int(win["days_ahead"]):
        raise ValueError("掃描天數與最早出發日無效")
    if not win["stay_nights"] or any(int(n) < 1 for n in win["stay_nights"]):
        raise ValueError("住宿晚數必須大於零")
    if len(set(win["stay_nights"])) != len(win["stay_nights"]):
        raise ValueError("住宿晚數不可重複")
    if not 0 < float(thr["instant"]) <= float(thr["digest"]) <= 1:
        raise ValueError("通知門檻須為 0 < instant ≤ digest ≤ 1")
    for name in ("monthly_quota", "monthly_safety", "daily_budget", "reserve_for_candidates"):
        if int(sc[name]) < 0:
            raise ValueError(f"{name} 不得為負數")
    if not 1 <= int(cfg["schedule"]["runs_per_day"]):
        raise ValueError("每日執行次數須大於零")
    if not 0 <= int(cfg["digest"]["hour_local"]) <= 23:
        raise ValueError("摘要時間須介於 0～23")
    if int(cfg["digest"]["top_n"]) < 1:
        raise ValueError("摘要筆數須大於零")
    if cfg["baseline"]["google_stat"] not in ("low", "mid", "high"):
        raise ValueError("google_stat 須為 low、mid 或 high")
    for value in cfg["baseline"]["weights"].values():
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError("基準權重須為有限非負數")


@dataclass
class Secrets:
    serpapi_key: str = ""
    travelpayouts_token: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""

    @classmethod
    def from_env(cls) -> "Secrets":
        names = ("SERPAPI_API_KEY", "TRAVELPAYOUTS_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
        return cls(*(os.environ.get(name, "").strip() for name in names))

    def missing(self) -> list[str]:
        return [name for name, value in zip(
            ("SERPAPI_API_KEY", "TRAVELPAYOUTS_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
            (self.serpapi_key, self.travelpayouts_token, self.telegram_token, self.telegram_chat_id),
        ) if not value]
