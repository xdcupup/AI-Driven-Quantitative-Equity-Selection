"""Forward-return label derivation from daily kline rows."""

from __future__ import annotations

import pandas as pd


def label_columns(horizons: tuple[int, ...] = (5, 10, 20), drawdown_horizon: int = 20) -> list[str]:
    return (
        ["ts_code", "trade_date"]
        + [f"forward_return_{h}d" for h in horizons]
        + [f"max_drawdown_{drawdown_horizon}d"]
        + ["source"]
    )


def _empty_labels(
    horizons: tuple[int, ...] = (5, 10, 20),
    drawdown_horizon: int = 20,
) -> pd.DataFrame:
    return pd.DataFrame(columns=label_columns(horizons, drawdown_horizon))


def _future_max_drawdown(values: pd.Series) -> float:
    if values.empty:
        return float("nan")
    start = values.iloc[0]
    if pd.isna(start) or start == 0:
        return float("nan")
    drawdown = values / start - 1
    return float(drawdown.min() * 100)


def derive_forward_return_labels(
    kline: pd.DataFrame,
    horizons: tuple[int, ...] = (5, 10, 20),
    drawdown_horizon: int = 20,
) -> pd.DataFrame:
    """Derive future return labels from daily close prices."""
    if kline.empty:
        return _empty_labels(horizons, drawdown_horizon)

    required = {"ts_code", "trade_date", "close"}
    if required - set(kline.columns):
        return _empty_labels(horizons, drawdown_horizon)

    df = kline.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["ts_code", "trade_date", "close"]).sort_values(
        ["ts_code", "trade_date"]
    )
    if df.empty:
        return _empty_labels(horizons, drawdown_horizon)

    frames = []
    for _, group in df.groupby("ts_code", sort=False):
        g = group.copy().reset_index(drop=True)
        close = g["close"]
        for horizon in horizons:
            g[f"forward_return_{horizon}d"] = (close.shift(-horizon) / close - 1) * 100

        future_window = drawdown_horizon + 1
        g[f"max_drawdown_{drawdown_horizon}d"] = (
            close
            .rolling(future_window, min_periods=future_window)
            .apply(_future_max_drawdown, raw=False)
            .shift(-drawdown_horizon)
        )
        g["source"] = "daily_kline"
        frames.append(g)

    result = pd.concat(frames, ignore_index=True)
    columns = label_columns(horizons, drawdown_horizon)
    for col in columns:
        if col not in result.columns:
            result[col] = float("nan")
    return result[columns].reset_index(drop=True)
