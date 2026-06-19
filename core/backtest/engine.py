"""Backtest engine: factor-based stock selection and simulation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from core.backtest.config import BacktestConfig
from core.backtest.portfolio import Portfolio


class BacktestEngine:
    """Config-driven factor backtest engine."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.portfolio = Portfolio(config.initial_capital)
        self.daily_returns = []

    def run(
        self,
        factors: pd.DataFrame,
        labels: pd.DataFrame,
        kline: pd.DataFrame,
        daily_basic: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Execute full backtest and return performance report."""
        if factors.empty or kline.empty:
            return {
                "total_return": 0.0, "annual_return": 0.0,
                "sharpe_ratio": 0.0, "max_drawdown": 0.0,
                "win_rate": 0.0, "daily_returns": [],
                "trades": [], "attribution": {},
            }

        start = pd.Timestamp(self.config.start_date)
        end = pd.Timestamp(self.config.end_date)

        factors["trade_date"] = pd.to_datetime(factors["trade_date"], errors="coerce")
        kline["trade_date"] = pd.to_datetime(kline["trade_date"], errors="coerce")

        trade_dates = sorted(
            factors[factors["trade_date"].between(start, end)]["trade_date"].unique()
        )
        if len(trade_dates) < 2:
            return {
                "total_return": 0.0, "annual_return": 0.0,
                "sharpe_ratio": 0.0, "max_drawdown": 0.0,
                "win_rate": 0.0, "daily_returns": [],
                "trades": [], "attribution": {},
            }

        daily_returns = []
        self._trades = []

        for i, signal_date in enumerate(trade_dates[:-1]):
            self._current_signal_date = signal_date
            next_date = trade_dates[i + 1]
            self._rebalance(factors, signal_date)
            day_return = self._mark_to_market(kline, next_date)
            daily_returns.append({
                "signal_date": signal_date,
                "exec_date": next_date,
                "daily_return": day_return,
                "nav": self.portfolio.nav,
            })

        self.daily_returns = daily_returns

        # Compute basic metrics
        rets = np.array([d["daily_return"] for d in daily_returns], dtype=float)
        navs = np.array([d["nav"] for d in daily_returns], dtype=float)
        total_return = float((navs[-1] / navs[0] - 1)) if len(navs) > 1 and navs[0] > 0 else 0.0
        mean_ret = float(np.mean(rets)) if len(rets) > 0 else 0.0
        std_ret = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
        sharpe = float(mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0
        cummax = np.maximum.accumulate(navs) if len(navs) > 0 else np.array([1.0])
        drawdowns = (navs - cummax) / cummax
        max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
        wins = int(np.sum(rets > 0))
        win_rate = float(wins / len(rets)) if len(rets) > 0 else 0.0

        return {
            "total_return": total_return,
            "annual_return": 0.0,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "daily_returns": daily_returns,
            "trades": self._trades,
            "attribution": {},
        }

    def _rebalance(self, factors: pd.DataFrame, signal_date: pd.Timestamp):
        """Select top-N stocks and rebalance portfolio."""
        day_factors = factors[factors["trade_date"] == signal_date]
        if day_factors.empty:
            return
        scored = self._score_stocks(day_factors)
        top_stocks = scored.head(self.config.top_n)["ts_code"].tolist()
        self.portfolio.rebalance(
            target_stocks=top_stocks,
            signal_date=signal_date,
            max_positions=self.config.max_positions,
            position_sizing=self.config.position_sizing,
            turnover_limit=self.config.turnover_limit,
        )

    def _score_stocks(self, day_factors: pd.DataFrame) -> pd.DataFrame:
        """Compute composite factor score for one day's cross-section."""
        factor_cols = [
            c for c in self.config.factor_columns if c in day_factors.columns
        ]
        if not factor_cols:
            df = day_factors.copy()
            df["_score"] = 0
            return df.sort_values("_score", ascending=False)

        df = day_factors.copy()
        for col in factor_cols:
            vals = df[col].astype(float)
            mean_val = vals.mean()
            std_val = vals.std()
            if std_val and std_val > 0:
                df[f"{col}_z"] = (vals - mean_val) / std_val
            else:
                df[f"{col}_z"] = 0.0

        z_cols = [f"{c}_z" for c in factor_cols]
        df["_score"] = df[z_cols].sum(axis=1)
        return df.sort_values("_score", ascending=False)

    def _mark_to_market(self, kline: pd.DataFrame, exec_date: pd.Timestamp) -> float:
        return self.portfolio.mark_to_market(
            kline, self._current_signal_date, exec_date, self._trades,
            slippage_bps=self.config.slippage_bps,
            commission_bps=self.config.commission_bps,
            stamp_duty_bps=self.config.stamp_duty_bps,
        )
