"""Performance analytics: metrics, layer analysis, and decay."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def compute_metrics(
    daily_returns: list[dict],
    trades: list[dict],
    config: Any,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Compute full performance report from daily returns and trades."""
    if not daily_returns:
        return _empty_report()

    rets = np.array([d["daily_return"] for d in daily_returns], dtype=float)
    navs = np.array([d["nav"] for d in daily_returns], dtype=float)

    total_return = float(
        (navs[-1] / getattr(config, "initial_capital", navs[0]) - 1)
        if navs[0] > 0
        else 0.0
    )

    n_days = len(rets)
    trading_days_per_year = 252
    if n_days > 0 and total_return > -1:
        ann_return = float((1 + total_return) ** (trading_days_per_year / n_days) - 1)
    else:
        ann_return = 0.0

    mean_ret = float(np.mean(rets))
    std_ret = float(np.std(rets, ddof=1))
    sharpe = float((mean_ret / std_ret * math.sqrt(trading_days_per_year)) if std_ret > 0 else 0.0)

    cummax = np.maximum.accumulate(navs)
    drawdowns = (navs - cummax) / cummax
    max_dd = float(np.min(drawdowns))

    wins = int(np.sum(rets > 0))
    win_rate = float(wins / n_days if n_days > 0 else 0.0)

    calmar = float(ann_return / abs(max_dd) if max_dd != 0 else 0.0)

    downside = rets[rets < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = float((mean_ret / downside_std * math.sqrt(trading_days_per_year)) if downside_std > 0 else 0.0)

    return {
        "total_return": total_return,
        "annual_return": ann_return,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
        "sortino_ratio": sortino,
        "win_rate": win_rate,
        "n_days": n_days,
        "n_trades": len(trades),
        "daily_returns": daily_returns,
        "trades": trades,
        "nav_series": navs.tolist(),
        "attribution": {},
    }


def compute_layer_returns(
    factors: pd.DataFrame,
    labels: pd.DataFrame,
    factor_column: str,
    label_column: str = "forward_return_20d",
    n_groups: int = 5,
) -> dict[str, Any]:
    """Split stocks into n_groups by factor value and compute mean forward return per group."""
    if factors.empty or labels.empty:
        return {"groups": [], "spread": 0.0, "ic_mean": 0.0}

    merged = factors[["ts_code", "trade_date", factor_column]].merge(
        labels[["ts_code", "trade_date", label_column]],
        on=["ts_code", "trade_date"],
        how="inner",
    )
    if merged.empty:
        return {"groups": [], "spread": 0.0, "ic_mean": 0.0}

    merged = merged.dropna(subset=[factor_column, label_column])
    if merged.empty:
        return {"groups": [], "spread": 0.0, "ic_mean": 0.0}

    results = []
    for date, group in merged.groupby("trade_date"):
        if len(group) < n_groups:
            continue
        try:
            group["_quantile"] = pd.qcut(
                group[factor_column], n_groups, labels=False, duplicates="drop"
            )
        except ValueError:
            continue
        for q in range(n_groups):
            q_data = group[group["_quantile"] == q]
            if not q_data.empty:
                results.append({
                    "trade_date": date,
                    "group": q,
                    "mean_return": float(q_data[label_column].mean()),
                    "count": len(q_data),
                })

    if not results:
        return {"groups": [], "spread": 0.0, "ic_mean": 0.0}

    layer_df = pd.DataFrame(results)
    group_means = layer_df.groupby("group")["mean_return"].mean().to_dict()
    spread = group_means.get(n_groups - 1, 0) - group_means.get(0, 0)

    ic_values = []
    for _, group in merged.groupby("trade_date"):
        if len(group) < 10:
            continue
        ic = group[factor_column].corr(group[label_column], method="spearman")
        if not math.isnan(ic):
            ic_values.append(ic)
    ic_mean = float(np.mean(ic_values)) if ic_values else 0.0

    return {
        "groups": [
            {"group": g, "mean_return": v} for g, v in sorted(group_means.items())
        ],
        "spread": spread,
        "ic_mean": ic_mean,
    }


def _empty_report() -> dict[str, Any]:
    return {
        "total_return": 0.0, "annual_return": 0.0,
        "sharpe_ratio": 0.0, "max_drawdown": 0.0,
        "calmar_ratio": 0.0, "sortino_ratio": 0.0,
        "win_rate": 0.0, "n_days": 0, "n_trades": 0,
        "daily_returns": [], "trades": [],
        "nav_series": [], "attribution": {},
    }
