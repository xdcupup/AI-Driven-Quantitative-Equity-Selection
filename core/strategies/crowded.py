"""Crowded-stock strategy adapted from a JoinQuant monthly liquidity rotation."""

from __future__ import annotations

import pandas as pd


def _as_date(value) -> pd.Timestamp:
    return pd.Timestamp(str(value).replace("-", "")[:8]).normalize()


def _valid_universe(
    stock_list: pd.DataFrame,
    as_of_date: str,
    min_listing_days: int,
) -> pd.DataFrame:
    if stock_list.empty or "ts_code" not in stock_list.columns:
        return pd.DataFrame(columns=["ts_code"])

    as_of = _as_date(as_of_date)
    df = stock_list.copy()
    if "list_status" in df.columns:
        df = df[df["list_status"].fillna("L") == "L"]
    if "name" in df.columns:
        names = df["name"].fillna("")
        df = df[~names.str.contains("ST", case=False, regex=False)]
    if "list_date" in df.columns:
        list_date = pd.to_datetime(df["list_date"], errors="coerce")
        listing_age = (as_of - list_date).dt.days
        df = df[list_date.isna() | (listing_age >= min_listing_days)]
    return df[["ts_code"]].drop_duplicates()


def _tradable_kline(kline: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    if kline.empty:
        return pd.DataFrame()

    df = kline.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df = df[df["trade_date"] < _as_date(as_of_date)]
    if "flag_suspended" in df.columns:
        df = df[~df["flag_suspended"].fillna(False)]
    if "flag_invalid_ohlc" in df.columns:
        df = df[~df["flag_invalid_ohlc"].fillna(False)]
    if "close" in df.columns:
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df[df["close"] > 0]
    return df.sort_values(["ts_code", "trade_date"])


def select_crowded_stocks(
    stock_list: pd.DataFrame,
    kline: pd.DataFrame,
    as_of_date: str,
    stock_num: int = 10,
    lookback_days: int = 22,
    min_listing_days: int = 120,
) -> pd.DataFrame:
    """Select top stocks by average trading amount before the signal date."""
    universe = _valid_universe(stock_list, as_of_date, min_listing_days)
    prices = _tradable_kline(kline, as_of_date)
    if universe.empty or prices.empty:
        return pd.DataFrame(columns=["ts_code", "avg_amount", "observations", "rank"])

    df = prices.merge(universe, on="ts_code", how="inner")
    if "amount" not in df.columns:
        df["amount"] = pd.NA
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    if "vol" in df.columns and "close" in df.columns:
        vol = pd.to_numeric(df["vol"], errors="coerce")
        df["amount"] = df["amount"].fillna(df["close"] * vol)
    df = df.dropna(subset=["amount"])
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "avg_amount", "observations", "rank"])

    recent = (
        df.sort_values(["ts_code", "trade_date"])
        .groupby("ts_code", group_keys=False)
        .tail(lookback_days)
    )
    grouped = (
        recent.groupby("ts_code")
        .agg(avg_amount=("amount", "mean"), observations=("amount", "count"))
        .reset_index()
    )
    grouped = grouped[grouped["observations"] >= lookback_days]
    grouped = grouped.sort_values(
        ["avg_amount", "ts_code"], ascending=[False, True]
    ).head(stock_num)
    grouped["rank"] = range(1, len(grouped) + 1)
    return grouped.reset_index(drop=True)


def calculate_equal_weight_momentum(
    kline: pd.DataFrame,
    stocks: list[str],
    as_of_date: str,
    momentum_days: int = 25,
) -> float:
    """Calculate equal-weight momentum for selected stocks before signal date."""
    if not stocks:
        return 0.0

    prices = _tradable_kline(kline, as_of_date)
    if prices.empty:
        return 0.0

    returns = []
    prices = prices[prices["ts_code"].isin(stocks)]
    for _, group in prices.groupby("ts_code", sort=False):
        g = group.sort_values("trade_date").tail(momentum_days + 1)
        if len(g) < momentum_days + 1:
            continue
        start_price = g.iloc[0]["close"]
        end_price = g.iloc[-1]["close"]
        if pd.notna(start_price) and start_price > 0 and pd.notna(end_price):
            returns.append((end_price - start_price) / start_price)

    if not returns:
        return 0.0
    return float(pd.Series(returns).mean())


def generate_crowded_rebalance_signal(
    target_stocks: list[str],
    momentum: float,
    current_positions: list[str] | set[str] | tuple[str, ...],
) -> dict:
    """Replicate the original strategy's minimal open-or-clear state machine."""
    has_position = bool(current_positions)
    targets = list(target_stocks)

    if not targets:
        return {
            "action": "clear" if has_position else "stay_cash",
            "reason": "empty_target",
            "target_weights": {},
        }

    if momentum > 0:
        if has_position:
            return {
                "action": "hold",
                "reason": "positive_momentum_already_in_position",
                "target_weights": {},
            }
        weight = 1.0 / len(targets)
        return {
            "action": "open_equal_weight",
            "reason": "positive_momentum",
            "target_weights": {code: weight for code in targets},
        }

    return {
        "action": "clear" if has_position else "stay_cash",
        "reason": "non_positive_momentum",
        "target_weights": {},
    }
