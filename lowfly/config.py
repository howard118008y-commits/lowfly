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
    normalize_routes(cfg)
    validate_config(cfg)
    return cfg


def normalize_routes(cfg: dict) -> None:
    """補上航線預設值：停留晚數取全域 window、SerpApi 抵達機場取 destination。"""
    for route in cfg.get("routes") or []:
        if isinstance(route, dict):
            route.setdefault("stay_nights", cfg["window"]["stay_nights"])
            route.setdefault("serpapi_arrival", route.get("destination"))
            route.setdefault("direct_only", True)
            route.setdefault("adults", 1)


def get_route(cfg: dict, route_id: str) -> dict:
    for route in cfg["routes"]:
        if route["id"] == route_id:
            return route
    raise KeyError(route_id)


def validate_config(cfg: dict) -> None:
    win, thr, sc = cfg["window"], cfg["thresholds"], cfg["sources"]["serpapi"]
    if not 1 <= int(win["min_lead_days"]) <= int(win["days_ahead"]):
        raise ValueError("掃描天數與最早出發日無效")
    if not win["stay_nights"] or any(int(n) < 1 for n in win["stay_nights"]):
        raise ValueError("住宿晚數必須大於零")
    if len(set(win["stay_nights"])) != len(win["stay_nights"]):
        raise ValueError("住宿晚數不可重複")
    routes = cfg.get("routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError("routes 必須是非空清單")
    for route in routes:
        for field in ("id", "origin", "destination", "label"):
            if not isinstance(route, dict) or not str(route.get(field) or "").strip():
                raise ValueError(f"航線缺少必要欄位 {field}")
        nights = route["stay_nights"]
        if not nights or any(int(n) < 1 for n in nights) or len(set(nights)) != len(nights):
            raise ValueError(f"航線 {route['id']} 的住宿晚數無效")
        if int(route["adults"]) < 1:
            raise ValueError(f"航線 {route['id']} 的成人數須大於零")
    if len({route["id"] for route in routes}) != len(routes):
        raise ValueError("航線 id 不可重複")
    if not 0 < float(thr["instant"]) <= float(thr["digest"]) <= 1:
        raise ValueError("通知門檻須為 0 < instant ≤ digest ≤ 1")
    if int(thr.get("max_instant_per_run", 5)) < 1:
        raise ValueError("max_instant_per_run 須大於零")
    bag = cfg.get("baggage") or {}
    if float(bag.get("checked_kg", 0)) < 0 or int(bag.get("pieces_each_way", 1)) < 0 or float(bag.get("unknown_fee_twd", 0)) < 0:
        raise ValueError("baggage 設定不得為負數")
    for fees in (bag.get("fees_twd") or {}).values():
        if any(float(v) < 0 for v in fees.values()):
            raise ValueError("行李費不得為負數")
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
