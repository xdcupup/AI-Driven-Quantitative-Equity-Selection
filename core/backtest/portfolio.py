"""Portfolio: position tracking, rebalancing, mark-to-market."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Position:
    ts_code: str
    shares: int = 0
    avg_cost: float = 0.0
    weight: float = 0.0


class Portfolio:
    """Tracks cash, positions, and NAV throughout a backtest."""

    def __init__(self, initial_capital: float = 1_000_000.0):
        self.initial_capital = float(initial_capital)
        self.cash = self.initial_capital
        self.positions: dict[str, Position] = {}
        self._last_prices: dict[str, float] = {}

    @property
    def nav(self) -> float:
        position_value = sum(
            pos.shares * self._last_prices.get(pos.ts_code, pos.avg_cost)
            for pos in self.positions.values()
        )
        return self.cash + position_value

    def rebalance(
        self,
        target_stocks: list[str],
        signal_date: pd.Timestamp,
        max_positions: int = 20,
        position_sizing: str = "equal_weight",
        turnover_limit: float = 0.5,
    ):
        """Adjust portfolio to target weights.

        Args:
            target_stocks: ordered list of target stock codes (best first)
            max_positions: cap on number of positions
            position_sizing: "equal_weight" or "score_weighted"
            turnover_limit: max fraction of portfolio to turn over (unused in v1)
        """
        targets = target_stocks[:max_positions]
        if not targets:
            return

        n = len(targets)
        target_weight = 1.0 / n

        current_codes = set(self.positions.keys())
        target_set = set(targets)

        # Sell positions not in targets
        for code in list(self.positions.keys()):
            if code not in target_set:
                self._sell(code, signal_date)

        # Adjust existing / add new positions
        for code in targets:
            if code in self.positions:
                self.positions[code].weight = target_weight
            else:
                self.positions[code] = Position(
                    ts_code=code,
                    weight=target_weight,
                )

    def mark_to_market(
        self,
        kline: pd.DataFrame,
        signal_date: pd.Timestamp,
        exec_date: pd.Timestamp,
        trades: list,
        slippage_bps: float = 5.0,
        commission_bps: float = 2.5,
        stamp_duty_bps: float = 10.0,
    ) -> float:
        """Mark positions to execution prices and compute daily return.

        For next_open execution: use exec_date's open price.
        """
        if not self.positions:
            return 0.0

        exec_kline = kline[kline["trade_date"] == exec_date]
        if exec_kline.empty:
            return 0.0

        price_map = dict(zip(exec_kline["ts_code"], exec_kline["open"]))

        prev_nav = self.nav
        total_position_value = 0.0

        for code, pos in list(self.positions.items()):
            price = price_map.get(code)
            if price is None or price <= 0:
                continue
            self._last_prices[code] = float(price)

            # On first mark, set avg_cost and allocate cash
            if pos.avg_cost == 0.0:
                alloc = self.initial_capital * pos.weight
                # Apply slippage: buy at slightly worse price
                buy_price = price * (1 + slippage_bps / 10000)
                pos.shares = int(alloc / buy_price)
                pos.avg_cost = buy_price
                cost = pos.shares * buy_price
                self.cash -= cost
                # Commission
                comm = cost * commission_bps / 10000
                self.cash -= comm

            total_position_value += pos.shares * price

        new_nav = self.cash + total_position_value
        day_return = (new_nav - prev_nav) / prev_nav if prev_nav > 0 else 0.0
        return float(day_return)

    def _sell(self, ts_code: str, trade_date: pd.Timestamp):
        """Remove a position and return cash."""
        pos = self.positions.pop(ts_code, None)
        if pos is None:
            return
        price = self._last_prices.get(ts_code, pos.avg_cost)
        proceeds = pos.shares * price
        self.cash += proceeds
        # Stamp duty on sell
        stamp = proceeds * 10.0 / 10000
        self.cash -= stamp
