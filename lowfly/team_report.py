"""團隊週報：每週一次，以 AI 團隊四個角色的分工整理過去 7 天，Sir 不用再開對話問「現在狀況」。"""
from __future__ import annotations

from datetime import datetime, timedelta

from .config import runs_per_day
from .dates import fmt_date, parse_time
from .notices import good_price
from .notifier import esc, fmt_money


def build_team_report(cfg: dict, state: dict, now: datetime, lows: dict[str, float]) -> tuple[str, dict]:
    """回傳（訊息, 本週快照）。快照存進 state["team_report"]，下週拿來比較。lows＝本輪各航線含行李最低價。"""
    routes = {route["id"]: route for route in cfg["routes"]}
    week_ago = now - timedelta(days=7)
    last = state.get("team_report") or {}
    city = lambda rid: routes[rid]["label"].split("⇄")[-1].strip()

    # 🧭 領航員：推播分類與各航線最低價
    instant, kinds = cfg["thresholds"]["instant"], {"神票": 0, "好價": 0, "新低": 0}
    for alert in state.get("alert_history", []):
        if parse_time(alert["at"]) >= week_ago and alert["route_id"] in routes:
            good = good_price(routes[alert["route_id"]])
            ratio = alert.get("ratio")
            kind = "神票" if ratio is not None and ratio <= instant else "好價" if good is not None and alert["price"] <= good else "新低"
            kinds[kind] += 1
    pushed = sum(kinds.values())
    lines = [f"🗼 <b>LowFly 團隊週報</b> {fmt_date(now.date())}", "", "🧭 <b>領航員｜票價</b>",
             f"• 本週推播 {pushed} 則" + (f"（{'、'.join(f'{k} {n}' for k, n in kinds.items() if n)}）" if pushed else "")]
    for rid, route in routes.items():
        if rid not in lows:
            lines.append(f"• {esc(city(rid))}：本輪沒有快取價")
            continue
        before = (last.get("lows") or {}).get(rid)
        change = "" if before is None else f"（上週 {fmt_money(before)}）"
        lines.append(f"• {esc(city(rid))}最低 {fmt_money(lows[rid])}{change}")

    # 🔭 瞭望員：本週推出的促銷消息
    sales = sum(row["count"] for row in state.get("sales_log", []) if parse_time(row["at"]) >= week_ago)
    lines += ["", "🔭 <b>瞭望員｜促銷</b>", f"• 本週推出促銷消息 {sales} 則"]

    # 🛠️ 地勤：成功掃描輪數對照排程應有輪數
    runs = state["stats"]["runs"]
    expected = sum(runs_per_day(cfg, (now - timedelta(days=d)).month) for d in range(1, 8))
    lines += ["", "🛠️ <b>地勤｜維運</b>"]
    if "runs" in last:
        done = runs - last["runs"]
        flag = "" if done >= expected * 0.8 else "　⚠️ 偏少，可能是 GitHub 排程延遲或掃描失敗"
        lines.append(f"• 本週成功掃描 {done} 輪（排程應有約 {expected} 輪）{flag}")
    else:
        lines.append(f"• 第一份週報，下週起比較掃描輪數（排程每週約 {expected} 輪）")
    lines.append(f"• 目前有價組合 {state.get('last_tp_count', 0)} 組")

    # 🗼 塔台：還在累積中的功能
    days = len({s["at"][:10] for s in state.get("tp_samples", {}).values()})
    need = int((cfg.get("new_low") or {}).get("min_days", 7))
    lines += ["", "🗼 <b>塔台</b>",
              f"• 航線新低：已累積 {days} 天紀錄" + ("，已啟動" if days >= need else f"，滿 {need} 天後啟動"),
              f"• 行情「過去」：已累積 {len(state.get('market_daily', {}))} 天"]
    return "\n".join(lines), {"date": now.date().isoformat(), "runs": runs, "lows": lows}
