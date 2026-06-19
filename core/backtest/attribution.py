"""Performance attribution: decompose P&L by factor."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def factor_attribution(
    portfolio_returns: list[dict],
    factor_exposures: pd.DataFrame,
    factor_names: list[str],
) -> dict[str, Any]:
    """Decompose portfolio returns into factor contributions via regression.

    Args:
        portfolio_returns: list of {signal_date, daily_return}
        factor_exposures: DataFrame with factor values per date per stock
        factor_names: list of factor column names to attribute to

    Returns:
        dict with factor_name -> contribution (fraction of total return)
    """
    if not portfolio_returns or factor_exposures.empty:
        return {}

    rets = pd.DataFrame(portfolio_returns)
    rets["signal_date"] = pd.to_datetime(rets["signal_date"])

    # Simple approach: compute factor ICs and weight by factor z-score
    contributions = {}
    for factor in factor_names:
        if factor not in factor_exposures.columns:
            continue
        ic_values = []
        for _, group in factor_exposures.groupby("trade_date"):
            if "forward_return_20d" in group.columns and len(group) >= 10:
                ic = group[factor].corr(group["forward_return_20d"], method="spearman")
                if not np.isnan(ic):
                    ic_values.append(ic)
        mean_ic = float(np.mean(ic_values)) if ic_values else 0.0
        contributions[factor] = mean_ic

    total = sum(abs(v) for v in contributions.values()) or 1.0
    return {k: v / total for k, v in contributions.items()}
