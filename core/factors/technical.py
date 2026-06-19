"""Technical factor derivation from daily kline rows."""

from __future__ import annotations

import pandas as pd


TECHNICAL_FACTOR_COLUMNS = [
    "ts_code",
    "trade_date",
    "return_5d",
    "return_20d",
    "return_60d",
    "volatility_20d",
    "ma20_bias",
    "ma60_bias",
    "max_drawdown_60d",
    "volume_ratio_20d",
    "liquidity_20d",
    "source",
]


def _empty_factors() -> pd.DataFrame:
    return pd.DataFrame(columns=TECHNICAL_FACTOR_COLUMNS)


def _max_drawdown(values: pd.Series) -> float:
    if values.empty:
        return float("nan")
    running_max = values.cummax()
    drawdown = values / running_max - 1
    return float(drawdown.min() * 100)


def derive_technical_factors(kline: pd.DataFrame) -> pd.DataFrame:
    """Derive daily technical factors from unadjusted daily kline data."""
    if kline.empty:
        return _empty_factors()

    required = {"ts_code", "trade_date", "close", "vol"}
    if required - set(kline.columns):
        return _empty_factors()

    df = kline.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for col in ["close", "vol", "amount"]:
        if col not in df.columns:
            df[col] = float("nan")
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["ts_code", "trade_date", "close"]).sort_values(
        ["ts_code", "trade_date"]
    )
    if df.empty:
        return _empty_factors()

    frames = []
    for _, group in df.groupby("ts_code", sort=False):
        g = group.copy().reset_index(drop=True)
        close = g["close"]
        vol = g["vol"]
        amount = g["amount"]

        g["return_5d"] = close.pct_change(5) * 100
        g["return_20d"] = close.pct_change(20) * 100
        g["return_60d"] = close.pct_change(60) * 100
        g["volatility_20d"] = close.pct_change().rolling(20).std() * 100
        g["ma20_bias"] = (close / close.rolling(20).mean() - 1) * 100
        g["ma60_bias"] = (close / close.rolling(60).mean() - 1) * 100
        g["max_drawdown_60d"] = close.rolling(60).apply(_max_drawdown, raw=False)
        g["volume_ratio_20d"] = vol / vol.rolling(20).mean()
        g["liquidity_20d"] = amount.rolling(20).mean()
        g["source"] = "daily_kline"
        frames.append(g)

    result = pd.concat(frames, ignore_index=True)
    for col in TECHNICAL_FACTOR_COLUMNS:
        if col not in result.columns:
            result[col] = float("nan")
    return result[TECHNICAL_FACTOR_COLUMNS].reset_index(drop=True)
