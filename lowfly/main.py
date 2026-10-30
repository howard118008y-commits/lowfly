from __future__ import annotations

import argparse
import logging
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ROOT, Secrets, load_config
from .dates import now_local
from .export import export_all
from .notifier import Telegram, esc
from .scanner import Scanner
from .state import append_history, load_state, read_history, save_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="低飛 LowFly — 直飛來回機票雷達")
    parser.add_argument("--config", help="設定檔路徑")
    parser.add_argument("--dry-run", action="store_true", help="可打價格 API，但不傳通知、不寫任何資料或圖片")
    parser.add_argument("--mock", action="store_true", help="使用假資料；輸出隔離至 out/mock，絕不連線")
    parser.add_argument("--force-digest", action="store_true", help="強制送每日摘要")
    parser.add_argument("--test-telegram", action="store_true", help="只送一則測試文字")
    parser.add_argument("--output-root", type=Path, help="自訂資料輸出根目錄")
    parser.add_argument("--now", help="只供 --mock 重現測試的含時區 ISO8601 時間")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.now and not args.mock:
        parser.error("--now 只可與 --mock 使用，避免正式額度日期被重置")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    cfg = load_config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else now_local(cfg["timezone"])
    if now.tzinfo is None:
        parser.error("--now 必須包含時區")
    now = now.astimezone(ZoneInfo(cfg["timezone"]))
    secrets = Secrets.from_env()
    tg = Telegram(secrets.telegram_token, secrets.telegram_chat_id, dry_run=args.dry_run or args.mock)
    if args.test_telegram:
        text = (f"✈️ <b>{esc(cfg['app_name'])}</b> 測試訊息\n{esc(cfg['route']['label'])}｜{now:%Y-%m-%d %H:%M}\n"
                "bot 設定正確，之後的通知會出現在這裡。")
        return 0 if tg.send(text) else 1
    target = args.output_root or (ROOT / "out/mock" if args.mock else ROOT)
    target = target.resolve()
    serp_fn = tp_fn = None
    if args.mock:
        if target == ROOT:
            parser.error("模擬輸出不可覆寫正式專案")
        from .mock import make_sources
        serp_fn, tp_fn = make_sources(now, cfg)
        secrets = Secrets(serpapi_key="mock", travelpayouts_token="mock")
    elif secrets.missing():
        logging.warning("缺少環境變數：%s；對應來源跳過，Telegram 僅預覽", ", ".join(secrets.missing()))
    try:
        state = load_state(target / "data/state.json")
    except (ValueError, OSError) as exc:
        logging.error("狀態無法讀取（%s）；保留原檔並停止，避免額度歸零", type(exc).__name__)
        return 1
    if args.mock:
        state["demo"] = True
    scanner = Scanner(cfg, secrets, state, tg, now, serpapi_fn=serp_fn, tp_fn=tp_fn,
                      force_digest=args.force_digest, output_dir=target / "out", render_images=not args.dry_run)
    summary = scanner.run()
    logging.info("掃描完成：SerpAPI %d 次、Travelpayouts %d 組、推播 %d 則、基準 %s",
                 summary["serpapi_calls"], summary["tp_offers"], summary["instant_alerts"], summary["baseline"])
    if not args.dry_run:
        save_state(state, target / "data/state.json")
        append_history(scanner.history_rows, target / "data/history.jsonl")
        if args.mock:
            shutil.copytree(ROOT / "docs", target / "docs", dirs_exist_ok=True, ignore=shutil.ignore_patterns("data"))
        export_all(cfg, state, now, read_history(target / "data/history.jsonl"), target / "docs/data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
