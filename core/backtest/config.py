"""Backtest configuration types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class BacktestConfig:
    """Complete backtest configuration."""
    # Date range
    start_date: date | str = "2024-01-01"
    end_date: date | str = "2026-06-01"

    # Factor selection
    factor_columns: list[str] = field(default_factory=lambda: [
        "return_20d", "return_60d", "volatility_20d",
        "ma20_bias", "ma60_bias", "max_drawdown_60d",
        "volume_ratio_20d", "liquidity_20d",
    ])
    label_column: str = "forward_return_20d"
    top_n: int = 50
    bottom_n: int = 50

    # Portfolio
    initial_capital: float = 1_000_000.0
    max_positions: int = 20
    position_sizing: str = "equal_weight"
    rebalance_frequency: str = "daily"
    turnover_limit: float = 0.5

    # Execution
    execution_model: str = "next_open"
    slippage_bps: float = 5.0
    commission_bps: float = 2.5
    stamp_duty_bps: float = 10.0
    block_limit_up_buys: bool = True
    limit_up_threshold: float = 0.095

    # Neutralization
    industry_neutral: bool = False
    market_cap_neutral: bool = False

    # Parameter scan
    scan_enabled: bool = False
    scan_params: dict[str, list[Any]] = field(default_factory=dict)

    # Signal decay
    decay_enabled: bool = False
    decay_half_life: int = 5

    # Attribution
    attribution_enabled: bool = False

    # Output
    output_dir: str = "data/backtest"

    @classmethod
    def from_dict(cls, d: dict) -> BacktestConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
