"""託運行李費：所有費用與「已含託運」航空清單都來自 config.yaml 的 baggage，程式不寫死任何數字。"""
from __future__ import annotations

from .notifier import fmt_money


def bag_fee(cfg: dict, route_id: str, airline_code: str | None) -> tuple[float, bool]:
    """回傳 (來回行李費, 是否為估算)。checked_kg=0 或航空已含託運 → (0, False)。"""
    bag = cfg.get("baggage") or {}
    if float(bag.get("checked_kg", 0) or 0) <= 0:
        return 0.0, False
    code = (airline_code or "").upper()
    if code and code in {str(c).upper() for c in bag.get("included") or []}:
        return 0.0, False
    fee = ((bag.get("fees_twd") or {}).get(code) or {}).get(route_id) if code else None
    estimated = fee is None
    if estimated:
        fee = bag.get("unknown_fee_twd", 0)
    return float(2 * int(bag.get("pieces_each_way", 1)) * fee), estimated


def bag_line(cfg: dict, fare, fee, estimated) -> str:
    """「不含行李 NT$x｜含行李 NT$y（20kg 來回）」；含託運航空為「NT$x（已含 20kg 託運）」；checked_kg=0 或沒有票價時回傳空字串。"""
    bag = cfg.get("baggage") or {}
    if float(bag.get("checked_kg", 0) or 0) <= 0 or fare is None:
        return ""
    kg = f"{bag['checked_kg']:g}kg"
    if not fee:
        return f"{fmt_money(fare)}（已含 {kg} 託運）"
    return f"不含行李 {fmt_money(fare)}｜含行李 {fmt_money(fare + fee)}（{kg} 來回{'，行李費估算' if estimated else ''}）"
