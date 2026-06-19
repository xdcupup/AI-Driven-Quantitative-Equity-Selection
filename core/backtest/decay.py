"""Signal decay: model diminishing signal strength over time."""

from __future__ import annotations

import numpy as np
import pandas as pd


def exponential_decay(
    scores: pd.Series,
    ages_days: pd.Series,
    half_life: int = 5,
) -> pd.Series:
    """Apply exponential decay: score * 0.5^(age/half_life)."""
    decay_factor = np.power(0.5, ages_days.astype(float) / half_life)
    return scores * decay_factor


def apply_decay_to_signals(
    signals: pd.DataFrame,
    half_life: int = 5,
    signal_col: str = "_score",
    output_col: str = "_score_decayed",
) -> pd.DataFrame:
    """Age signals by days since first appearance and apply decay."""
    if signals.empty:
        signals[output_col] = 0.0
        return signals

    df = signals.sort_values(["ts_code", "trade_date"]).copy()
    df["_first_seen"] = df.groupby("ts_code")["trade_date"].transform("min")
    df["_age_days"] = (df["trade_date"] - df["_first_seen"]).dt.days
    df[output_col] = exponential_decay(
        df[signal_col].fillna(0), df["_age_days"].fillna(0), half_life
    )
    return df.drop(columns=["_first_seen", "_age_days"])
