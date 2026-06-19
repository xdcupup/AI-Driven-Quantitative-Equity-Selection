"""ParameterScanner: grid search over backtest parameters."""

from __future__ import annotations

import itertools
from copy import deepcopy
from typing import Any

import pandas as pd

from core.backtest.config import BacktestConfig


class ParameterScanner:
    """Scan parameter combinations and rank results."""

    def __init__(self, base_config: BacktestConfig):
        self.base_config = base_config

    def build_combinations(self, scan_params: dict[str, list[Any]]) -> list[dict]:
        """Generate all parameter combinations (cartesian product)."""
        keys = list(scan_params.keys())
        values = list(scan_params.values())
        combos = []
        for combo in itertools.product(*values):
            combos.append(dict(zip(keys, combo)))
        return combos

    def apply_combo(self, config: BacktestConfig, combo: dict) -> BacktestConfig:
        """Create a new config with overridden parameters."""
        new_cfg = deepcopy(config)
        for key, value in combo.items():
            setattr(new_cfg, key, value)
        return new_cfg

    def scan(
        self,
        factors: pd.DataFrame,
        labels: pd.DataFrame,
        kline: pd.DataFrame,
        daily_basic: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Run all combinations and return ranked results."""
        from core.backtest.engine import BacktestEngine

        combos = self.build_combinations(self.base_config.scan_params)
        results = []
        for combo in combos:
            cfg = self.apply_combo(self.base_config, combo)
            engine = BacktestEngine(cfg)
            report = engine.run(factors, labels, kline, daily_basic)
            results.append({**combo, **{
                "sharpe": report["sharpe_ratio"],
                "total_return": report["total_return"],
                "max_drawdown": report["max_drawdown"],
                "calmar": report["calmar_ratio"],
            }})
        return pd.DataFrame(results).sort_values("sharpe", ascending=False)
