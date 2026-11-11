#!/usr/bin/env python3
"""YeNo volume-bot strategy (parameterised, stdlib only).

Generalises the official House Bot v1 (kit/yeno-house-bot-v1.py) so the
same decision code can be tuned in the local simulator and served over
POST /decide by bot.py. The evaluator owns cash/fills/fees/volume; this
module only returns HOLD / BUY / SELL.

Default params (PARAMS) are the tuned values from tune.py + the held-out
validation in run_simulation.py. See TEST_RESULTS.md for the numbers and
their limits (synthetic data only; the official 24h run is unseen).
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Tuned parameters (see TEST_RESULTS.md; house-bot v1 values in comments)
# Final candidate = House Bot v1 + three low-risk changes only:
#   * max_cash_headroom_usd 0.15 (house: 0) -- a fill against the LATER
#     execution book (250 ms latency) is not rejected by a 1-2 cent move.
#   * min_gap_usd 80 (house: 50) -- fewer, higher-conviction entries;
#     preserves ~$0.90 more cash per 24h path in the sim.
#   * regime filter on (house: none) -- after 8 bleeding cycles, entries
#     require a strong ($100) gap until results recover.
# Everything else is EXACTLY House Bot v1: wider windows, more cycles,
# dynamic sizing, take-profit/stop changes and trend-riding all tested
# worse or neutral in the simulator (stages A-C), so they were dropped.
# ---------------------------------------------------------------------------
PARAMS: dict[str, Any] = {
    "base_shares": 5.0,
    "max_shares": 5.0,
    "strong_gap_usd": 1e18,
    "max_cash_fraction": 1.0,
    "min_gap_usd": 80.0,
    "max_entry_price": 0.90,
    "max_immediate_loss_usd": 0.40,
    "stop_loss_per_share_usd": 0.10,
    "take_profit_per_share_usd": 0.0,
    "forced_exit_seconds": 60.0,
    "max_cycles_per_market": 2,
    "entry_window_seconds": 90.0,
    "reentry_cooldown_seconds": 2.0,
    "max_reference_age_seconds": 1.5,
    "require_book_agreement": False,
    "max_cash_headroom_usd": 0.15,
    "regime_window": 8,
    "regime_bad_avg_pnl_usd": -0.25,
    "regime_strong_gap_usd": 100.0,
}

HOUSE_PARAMS: dict[str, Any] = {
    "base_shares": 5.0,
    "max_shares": 5.0,
    "strong_gap_usd": 1e18,
    "max_cash_fraction": 1.0,
    "min_gap_usd": 50.0,
    "max_entry_price": 0.90,
    "max_immediate_loss_usd": 0.40,
    "stop_loss_per_share_usd": 0.10,
    "take_profit_per_share_usd": 0.0,
    "forced_exit_seconds": 60.0,
    "max_cycles_per_market": 2,
    "entry_window_seconds": 90.0,
    "reentry_cooldown_seconds": 2.0,
    "max_reference_age_seconds": 1.5,
    "require_book_agreement": False,
    "max_cash_headroom_usd": 0.0,
    "regime_window": 0,
    "regime_bad_avg_pnl_usd": -1e18,
    "regime_strong_gap_usd": 1e18,
}


def _levels(rows: Any, *, reverse: bool) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            price, size = float(row[0]), float(row[1])
        except (IndexError, TypeError, ValueError):
            continue
        if 0 < price < 1 and size > 0:
            out.append((price, size))
    return sorted(out, reverse=reverse)


def _fees(fills: list[tuple[float, float]]) -> float:
    gross = sum(price * shares for price, shares in fills)
    protocol = sum(0.07 * shares * price * (1 - price) for price, shares in fills)
    return round(protocol + 1e-12, 5) + round(gross * 0.01 + 1e-12, 5)


def _walk_cost(levels: list[tuple[float, float]], shares: float) -> tuple[float, float] | None:
    """(gross, fees) to buy/sell `shares` walking sorted levels, else None."""
    remaining = shares
    fills: list[tuple[float, float]] = []
    for price, available in levels:
        qty = min(remaining, available)
        fills.append((price, qty))
        remaining -= qty
        if remaining <= 1e-9:
            break
    if remaining > 1e-9:
        return None
    return sum(p * q for p, q in fills), _fees(fills)


class Strategy:
    """Stateful per-evaluation-run decision maker."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.p = dict(PARAMS if params is None else params)
        self.market_id: str | None = None
        self.position_was_open = False
        self.completed_cycles = 0
        self.last_flat_at = -math.inf
        self.last_buy_attempt_at = -math.inf
        self.recent_pnls: list[float] = []  # full-cycle pnl of closed cycles
        self._last_cycle_pnl: float | None = None

    # -- helpers ---------------------------------------------------------
    def _shares_for(self, gap: float, price: float, cash: float,
                    asks: Any, side: str) -> float | None:
        p = self.p
        shares = p["base_shares"]
        if abs(gap) >= p["strong_gap_usd"]:
            shares = p["max_shares"]
        cap = min(float(cash) * p["max_cash_fraction"],
                  5.0)  # contract: $5 fee-inclusive ceiling
        while shares >= 5.0:
            cost = _walk_cost(_levels(asks, reverse=False), shares)
            if cost is not None and cost[0] + cost[1] <= cap + 1e-9:
                return shares
            shares -= 1.0
        return None

    # -- main entry ------------------------------------------------------
    def decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._decide(observation)
        except (KeyError, TypeError, ValueError, OverflowError):
            return {"action": "HOLD"}

    def _decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        p = self.p
        market = observation["market"]
        account = observation["account"]
        books = observation["books"]
        now = float(observation["timestamp"])
        seconds = float(market["secondsToClose"])
        market_id = str(market["id"])
        position = account.get("position")

        if market_id != self.market_id:
            self.market_id = market_id
            self.position_was_open = False
            self.completed_cycles = 0
            self.last_flat_at = -math.inf
            self.last_buy_attempt_at = -math.inf

        if position is None and self.position_was_open:
            self.completed_cycles += 1
            self.last_flat_at = now
            if self._last_cycle_pnl is not None:
                self.recent_pnls.append(self._last_cycle_pnl)
                self._last_cycle_pnl = None
        self.position_was_open = position is not None

        # --- exit logic: a position is open ------------------------------
        if position is not None:
            side = str(position["outcome"])
            shares = float(position["shares"])
            executable = _walk_cost(_levels(books.get(side, {}).get("bids", []),
                                          reverse=True), shares)
            if executable is None:
                return {"action": "HOLD"}
            sell_gross, sell_fees = executable
            paid = float(position["buy_gross_usd"]) + float(position["buy_fees_usd"])
            received = float(position.get("sell_gross_usd", 0)) - float(position.get("sell_fees_usd", 0))
            full_cycle_pnl = received + sell_gross - sell_fees - paid
            self._last_cycle_pnl = full_cycle_pnl
            pnl_per_share = full_cycle_pnl / shares
            tp = p["take_profit_per_share_usd"]
            if tp is not None and pnl_per_share >= tp - 1e-9:
                return {"action": "SELL"}
            sl = p["stop_loss_per_share_usd"]
            if sl is not None and pnl_per_share <= -sl + 1e-9:
                return {"action": "SELL"}
            if seconds <= p["forced_exit_seconds"] + 1e-9:
                return {"action": "SELL"}
            return {"action": "HOLD"}

        # --- entry gates --------------------------------------------------
        if self.completed_cycles >= p["max_cycles_per_market"]:
            return {"action": "HOLD"}
        if now - self.last_flat_at < p["reentry_cooldown_seconds"] - 1e-9:
            return {"action": "HOLD"}
        if now - self.last_buy_attempt_at < p["reentry_cooldown_seconds"] - 1e-9:
            return {"action": "HOLD"}
        if not (15 < seconds <= p["entry_window_seconds"]):
            return {"action": "HOLD"}

        reference = observation.get("reference")
        if not isinstance(reference, dict) or bool(reference.get("targetProvisional", True)):
            return {"action": "HOLD"}
        if now - float(reference.get("observedAt", -math.inf)) > p["max_reference_age_seconds"]:
            return {"action": "HOLD"}
        if float(reference.get("targetObservedAt", math.inf)) > now + 1e-9:
            return {"action": "HOLD"}
        gap = float(reference["btcMidUsd"]) - float(reference["openingTargetUsd"])

        min_gap = p["min_gap_usd"]
        if p["regime_window"] and len(self.recent_pnls) >= p["regime_window"]:
            recent_avg = sum(self.recent_pnls[-p["regime_window"]:]) / p["regime_window"]
            if recent_avg < p["regime_bad_avg_pnl_usd"]:
                min_gap = max(min_gap, p["regime_strong_gap_usd"])
        if abs(gap) < min_gap - 1e-9:
            return {"action": "HOLD"}

        side = "YES" if gap >= 0 else "NO"
        if p["require_book_agreement"]:
            for book_side in ("YES", "NO"):
                bids = _levels(books.get(book_side, {}).get("bids", []), reverse=True)
                asks = _levels(books.get(book_side, {}).get("asks", []), reverse=False)
                if not bids or not asks:
                    return {"action": "HOLD"}
            yes_mid = (_levels(books["YES"]["bids"], reverse=True)[0][0]
                       + _levels(books["YES"]["asks"], reverse=False)[0][0]) / 2
            book_side = "YES" if yes_mid >= 0.5 else "NO"
            if book_side != side:
                return {"action": "HOLD"}

        asks = books.get(side, {}).get("asks", [])
        best_asks = _levels(asks, reverse=False)
        if not best_asks or best_asks[0][0] > p["max_entry_price"] + 1e-9:
            return {"action": "HOLD"}
        shares = self._shares_for(gap, best_asks[0][0], float(account["cashUsd"]), asks, side)
        if shares is None:
            return {"action": "HOLD"}
        required = _walk_cost(best_asks, shares)
        immediate_exit = _walk_cost(_levels(books.get(side, {}).get("bids", []),
                                             reverse=True), shares)
        if required is None or immediate_exit is None:
            return {"action": "HOLD"}
        gross, fees = required
        sell_gross, sell_fees = immediate_exit
        if p["max_immediate_loss_usd"] is not None and \
                sell_gross - sell_fees - gross - fees < -p["max_immediate_loss_usd"] - 1e-9:
            return {"action": "HOLD"}

        cash = gross + fees
        ceiling = min(float(account["cashUsd"]), float(observation["rules"]["maximumBuyCashUsd"]))
        if cash > ceiling + 1e-9:
            return {"action": "HOLD"}
        self.last_buy_attempt_at = now
        max_cash = min(ceiling, cash + p.get("max_cash_headroom_usd", 0.0))
        return {"action": "BUY", "outcome": side, "maxCashUsd": round(max_cash, 6)}
