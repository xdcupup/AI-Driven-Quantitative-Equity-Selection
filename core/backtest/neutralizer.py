"""Factor neutralization: industry and market-cap adjustments."""

from __future__ import annotations

import numpy as np
import pandas as pd


def industry_neutralize(
    df: pd.DataFrame,
    factor_col: str = "factor_value",
    industry_col: str = "industry",
    output_col: str = "factor_value_neutral",
) -> pd.DataFrame:
    """Subtract industry mean from factor values (cross-sectional per date)."""
    if df.empty or industry_col not in df.columns:
        df[output_col] = df.get(factor_col, 0)
        return df

    result = df.copy()
    result[output_col] = result[factor_col].astype(float)
    result[output_col] = result[output_col] - result.groupby(
        ["trade_date", industry_col], group_keys=False
    )[factor_col].transform("mean")
    return result


def market_cap_neutralize(
    df: pd.DataFrame,
    factor_col: str = "factor_value",
    mcap_col: str = "log_market_cap",
    output_col: str = "factor_value_neutral",
) -> pd.DataFrame:
    """Regress factor on log market cap cross-sectionally and return residuals.

    Falls back to subtracting cross-sectional mean if sklearn is not available.
    """
    if df.empty or mcap_col not in df.columns:
        df[output_col] = df.get(factor_col, 0)
        return df

    result = df.copy()

    try:
        from sklearn.linear_model import LinearRegression
        use_sklearn = True
    except ImportError:
        use_sklearn = False

    if not use_sklearn:
        # Fallback: subtract cross-sectional mean
        result[output_col] = result[factor_col].astype(float)
        result[output_col] = result[output_col] - result.groupby(
            "trade_date", group_keys=False
        )[factor_col].transform("mean")
        return result

    result[output_col] = result[factor_col].astype(float)

    for date, group in result.groupby("trade_date"):
        valid = group[[factor_col, mcap_col]].dropna()
        if len(valid) < 3:
            result.loc[group.index, output_col] = result.loc[group.index, factor_col]
            continue
        X = valid[[mcap_col]].values
        y = valid[factor_col].values
        model = LinearRegression().fit(X, y)
        predicted = model.predict(X)
        residuals = y - predicted
        result.loc[valid.index, output_col] = residuals

    return result
