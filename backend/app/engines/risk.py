"""Risk engine: entry, stop loss, target, R:R and position sizing for a long swing setup.

Planning aid only. Levels are derived from ATR and swing structure; they are not predictions.
"""
from __future__ import annotations

import math

DISCLAIMER = ("Levels are computed from historical price structure and volatility. They are planning aids, "
              "not predictions or guaranteed returns. This app does not place orders.")


def plan_long(technical: dict, price: float, *, capital: float, risk_pct: float, max_position_pct: float) -> dict:
    warnings: list[str] = []
    atr = technical.get("atr14")
    supports = technical.get("support") or []
    resistances = technical.get("resistance") or []
    if not price or not atr:
        return {"side": "LONG", "entry": None, "stop_loss": None, "target": None, "target_2": None, "risk_per_share": None,
                "reward_per_share": None, "risk_reward": None, "stop_method": None, "target_method": None,
                "position": None, "warnings": ["Insufficient daily history to compute ATR-based levels."],
                "disclaimer": DISCLAIMER}

    entry = round(price, 2)
    stop_method = "2 x ATR below entry"
    stop = entry - 2 * atr
    below = [s for s in supports if s < entry]
    if below:
        candidate = below[0] - 0.25 * atr
        if atr <= entry - candidate <= 3 * atr:
            stop, stop_method = candidate, "nearest swing support - 0.25 x ATR"
    stop = round(stop, 2)
    risk = round(entry - stop, 2)

    target_method = "2R projection"
    target = entry + 2 * risk
    above = sorted(r for r in resistances if r > entry)
    far_enough = [r for r in above if r - entry >= 1.5 * risk]
    if far_enough:
        target, target_method = far_enough[0], "first swing resistance at least 1.5R away"
    if above and above[0] - entry < 1.5 * risk:
        warnings.append(f"Overhead resistance at {above[0]} is closer than 1.5R; target assumes it is cleared.")
    target = round(target, 2)
    target_2 = round(entry + 3 * risk, 2)
    reward = round(target - entry, 2)
    rr = round(reward / risk, 2) if risk > 0 else None

    stop_pct = risk / entry * 100
    if stop_pct > 8:
        warnings.append(f"Stop is {stop_pct:.1f}% away - wide for a swing trade; consider smaller size.")
    if rr is not None and rr < 1.5:
        warnings.append(f"Risk:reward {rr} is below the 1.5 minimum.")

    position = None
    if capital > 0 and 0 < risk_pct and risk > 0:
        risk_amount = capital * risk_pct / 100
        qty = math.floor(risk_amount / risk)
        cap_qty = math.floor(capital * max_position_pct / 100 / entry)
        capped = qty > cap_qty
        qty = min(qty, cap_qty)
        position = {"capital": capital, "risk_pct": risk_pct, "max_position_pct": max_position_pct,
                    "risk_amount": round(risk_amount, 2), "quantity": qty, "position_value": round(qty * entry, 2),
                    "max_loss_at_stop": round(qty * risk, 2), "capped_by_max_position": capped}
        if qty == 0:
            warnings.append("Capital/risk settings allow 0 shares at this stop distance.")

    return {"side": "LONG", "entry": entry, "stop_loss": stop, "target": target, "target_2": target_2,
            "risk_per_share": risk, "reward_per_share": reward, "risk_reward": rr, "stop_pct": round(stop_pct, 2),
            "stop_method": stop_method, "target_method": target_method, "atr14": atr, "position": position,
            "warnings": warnings, "disclaimer": DISCLAIMER}


def exit_levels(technical: dict, price: float) -> dict:
    """For HOLD/SELL signals: a protective trailing level for existing holders, no new entry."""
    atr = technical.get("atr14")
    supports = [s for s in (technical.get("support") or []) if s < price]
    trail = None
    if atr and price:
        trail = round(max(price - 2 * atr, supports[0] - 0.25 * atr) if supports else price - 2 * atr, 2)
    return {"trailing_stop": trail, "method": "max(2 x ATR below price, nearest support - 0.25 x ATR)" if trail else None}
