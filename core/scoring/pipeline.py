"""Pipeline helpers for building and persisting hot-candidate scores."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.scoring.enrich import (
    enrich_daily_kline_features,
    enrich_fund_flow,
    enrich_sector_info,
)
from core.scoring.hot_candidate import score_hot_candidates


def build_hot_candidate_scores(
    db: Any,
    target_date: str,
    strategy_name: str = "hot_candidate_v1",
    min_pct_chg: float = 9.0,
    lookback_days: int = 10,
    persist: bool = True,
) -> pd.DataFrame:
    """Build, score, and optionally persist daily hot candidates."""
    trade_date = pd.Timestamp(str(target_date).replace("-", "")[:8])
    candidates = _query_base_candidates(db, trade_date, min_pct_chg)
    if candidates.empty:
        return _empty_scored()

    ts_codes = candidates["ts_code"].dropna().astype(str).unique().tolist()
    lookback_start = trade_date - pd.Timedelta(days=lookback_days)
    kline = _query_kline(db, lookback_start, trade_date, ts_codes)
    fund_flow = _query_table_by_date(db, "stock_fund_flow_daily", trade_date, ts_codes)
    hot_themes = _query_table_by_date(db, "hot_theme_daily", trade_date)
    theme_stocks = _query_table_by_date(db, "hot_theme_stocks", trade_date)

    enriched = enrich_daily_kline_features(candidates, kline)
    enriched = enrich_fund_flow(enriched, fund_flow)
    enriched = enrich_sector_info(enriched, pd.DataFrame(), hot_themes, theme_stocks)
    enriched = _add_scoring_defaults(enriched, kline)

    scored = score_hot_candidates(enriched)
    scored["strategy_name"] = strategy_name
    scored["source"] = "hot_candidate_pipeline"
    if persist and not scored.empty:
        db.upsert_hot_candidate_scores(scored, strategy_name=strategy_name)
    return scored


def _query_base_candidates(
    db: Any,
    trade_date: pd.Timestamp,
    min_pct_chg: float,
) -> pd.DataFrame:
    df = db.query_sql(
        """
        SELECT
            k.ts_code, k.trade_date, k.open, k.high, k.low, k.close,
            k.vol, k.amount, k.pct_chg,
            b.turnover_rate, b.volume_ratio, b.circ_mv, b.total_mv
        FROM daily_kline k
        LEFT JOIN daily_basic b
          ON k.ts_code = b.ts_code
         AND k.trade_date = b.trade_date
        WHERE k.trade_date = ?::DATE
          AND COALESCE(k.flag_suspended, FALSE) = FALSE
          AND COALESCE(k.flag_invalid_ohlc, FALSE) = FALSE
          AND k.close > 0
          AND k.pct_chg >= ?
        ORDER BY k.pct_chg DESC, k.amount DESC, k.ts_code
        """,
        [trade_date.strftime("%Y-%m-%d"), float(min_pct_chg)],
    )
    if df.empty:
        return df

    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df = df[df["pct_chg"] >= min_pct_chg]
    if df.empty:
        return df.reset_index(drop=True)
    if "amount" in df.columns:
        df["amount"] = df["amount"].map(_to_yi)
    if "circ_mv" in df.columns:
        df["circ_mv"] = df["circ_mv"].map(_to_yi)
    if "total_mv" in df.columns:
        df["total_mv"] = df["total_mv"].map(_to_yi)
    if {"open", "high", "low", "close"}.issubset(df.columns):
        df["is_one_price_limit_up"] = (
            (df["open"] == df["high"])
            & (df["high"] == df["low"])
            & (df["low"] == df["close"])
        )
    return df.reset_index(drop=True)


def _query_kline(
    db: Any,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    ts_codes: list[str],
) -> pd.DataFrame:
    if not ts_codes:
        return pd.DataFrame()
    placeholders = ", ".join(["?"] * len(ts_codes))
    return db.query_sql(
        f"""
        SELECT ts_code, trade_date, open, close, vol, pct_chg
        FROM daily_kline
        WHERE trade_date BETWEEN ?::DATE AND ?::DATE
          AND ts_code IN ({placeholders})
        ORDER BY ts_code, trade_date
        """,
        [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), *ts_codes],
    )


def _query_table_by_date(
    db: Any,
    table_name: str,
    trade_date: pd.Timestamp,
    ts_codes: list[str] | None = None,
) -> pd.DataFrame:
    params: list[Any] = [trade_date.strftime("%Y-%m-%d")]
    code_filter = ""
    if ts_codes and table_name != "hot_theme_daily":
        placeholders = ", ".join(["?"] * len(ts_codes))
        code_filter = f"AND ts_code IN ({placeholders})"
        params.extend(ts_codes)
    return db.query_sql(
        f"""
        SELECT *
        FROM {table_name}
        WHERE trade_date = ?::DATE
          {code_filter}
        """,
        params,
    )


def _add_scoring_defaults(candidates: pd.DataFrame, kline: pd.DataFrame) -> pd.DataFrame:
    df = candidates.copy()
    if "main_net_ratio" in df.columns:
        main_net_ratio = pd.to_numeric(df["main_net_ratio"], errors="coerce").fillna(0.0)
        df["main_buy_ratio"] = (main_net_ratio / 100).clip(lower=0)
        df["main_direction_5d"] = main_net_ratio / 10
    else:
        df["main_buy_ratio"] = 0.0
        df["main_direction_5d"] = 0.0

    if "sector_pct_chg" in df.columns:
        sector_pct = pd.to_numeric(df["sector_pct_chg"], errors="coerce").fillna(0.0)
        df["sector_main_direction"] = (sector_pct > 0).astype(float)
    else:
        df["sector_main_direction"] = 0.0

    df["limit_up_streak"] = _limit_up_streaks(kline, df)
    df["safety_score"] = df.get("safety_score", 90.0)
    df["is_st"] = df.get("is_st", False)
    df["is_delisted"] = df.get("is_delisted", False)
    return df


def _limit_up_streaks(kline: pd.DataFrame, candidates: pd.DataFrame) -> list[int]:
    if kline.empty or "pct_chg" not in kline.columns:
        return [1] * len(candidates)
    kl = kline.copy()
    kl["trade_date"] = pd.to_datetime(kl["trade_date"], errors="coerce")
    kl["is_limit"] = pd.to_numeric(kl["pct_chg"], errors="coerce").fillna(0.0) >= 9.0
    streak_by_code = {}
    for code, group in kl.sort_values("trade_date").groupby("ts_code"):
        streak = 0
        for is_limit in group["is_limit"]:
            streak = streak + 1 if is_limit else 0
        streak_by_code[code] = max(streak, 1)
    return [int(streak_by_code.get(code, 1)) for code in candidates["ts_code"]]


def _to_yi(value: Any) -> Any:
    if pd.isna(value):
        return value
    value = float(value)
    return value / 100000000 if abs(value) > 1000000 else value


def _empty_scored() -> pd.DataFrame:
    return score_hot_candidates(pd.DataFrame())
