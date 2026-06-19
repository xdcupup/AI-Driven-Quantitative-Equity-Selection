"""Backtest adapter for hot-candidate scoring results."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.backtest.config import BacktestConfig
from core.backtest.engine import BacktestEngine
from core.backtest.analytics import _empty_report


def load_scored_candidates_csv(path: str) -> pd.DataFrame:
    """Load scored hot candidates from a CSV file."""
    df = pd.read_csv(path)
    if "trade_date" in df.columns:
        df["trade_date"] = _parse_trade_date_series(df["trade_date"])
    if "is_rejected" in df.columns:
        df["is_rejected"] = df["is_rejected"].map(_to_bool)
    return df


def query_kline_for_backtest(
    db: Any,
    start_date: str,
    end_date: str,
    ts_codes: list[str] | None = None,
) -> pd.DataFrame:
    """Query K-line rows used by BacktestEngine."""
    params: list[Any] = [start_date, end_date]
    code_filter = ""
    if ts_codes:
        placeholders = ", ".join(["?"] * len(ts_codes))
        code_filter = f"AND ts_code IN ({placeholders})"
        params.extend(ts_codes)

    return db.conn.execute(
        f"""
        SELECT ts_code, trade_date, open, close, high, low, vol, amount
        FROM daily_kline
        WHERE trade_date BETWEEN ?::DATE AND ?::DATE
          {code_filter}
        ORDER BY trade_date, ts_code
        """,
        params,
    ).df()


def prepare_hot_candidate_factors(
    scored_candidates: pd.DataFrame,
    min_score: float = 0.0,
    score_column: str = "total_score",
) -> pd.DataFrame:
    """Convert scored hot candidates to factor rows consumable by BacktestEngine."""
    columns = ["ts_code", "trade_date", score_column]
    if scored_candidates.empty:
        return pd.DataFrame(columns=columns)

    df = scored_candidates.copy()
    for required in ["ts_code", "trade_date", score_column]:
        if required not in df.columns:
            return pd.DataFrame(columns=columns)

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df[score_column] = pd.to_numeric(df[score_column], errors="coerce")
    if "is_rejected" in df.columns:
        df = df[~df["is_rejected"].fillna(False).astype(bool)]
    df = df.dropna(subset=["ts_code", "trade_date", score_column])
    df = df[df[score_column] >= min_score]
    if df.empty:
        return pd.DataFrame(columns=columns)

    return (
        df[columns]
        .sort_values(["trade_date", score_column, "ts_code"], ascending=[True, False, True])
        .reset_index(drop=True)
    )


def run_hot_candidate_backtest(
    scored_candidates: pd.DataFrame,
    kline: pd.DataFrame,
    config: BacktestConfig | None = None,
    min_score: float = 0.0,
    score_column: str = "total_score",
) -> dict[str, Any]:
    """Run BacktestEngine using hot-candidate total_score as the ranking factor."""
    factors = prepare_hot_candidate_factors(
        scored_candidates,
        min_score=min_score,
        score_column=score_column,
    )
    if config is None:
        config = BacktestConfig(factor_columns=[score_column])
    else:
        config.factor_columns = [score_column]

    if factors.empty or kline.empty:
        report = _empty_report()
        report["selected_count"] = len(factors)
        report["selected_factors"] = factors
        return report

    engine = BacktestEngine(config)
    report = engine.run(factors=factors, labels=pd.DataFrame(), kline=kline)
    report["selected_count"] = len(factors)
    report["selected_factors"] = factors
    return report


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _parse_trade_date_series(values: pd.Series) -> pd.Series:
    raw = values.astype(str).str.strip()
    compact = raw.str.fullmatch(r"\d{8}")
    parsed = pd.to_datetime(raw.where(~compact), errors="coerce")
    parsed_compact = pd.to_datetime(raw.where(compact), format="%Y%m%d", errors="coerce")
    return parsed.fillna(parsed_compact)
