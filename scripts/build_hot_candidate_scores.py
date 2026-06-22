#!/usr/bin/env python3
"""Build and persist hot-candidate scores for a date range."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable

import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data_storage import QuantDB
from core.scoring.hot_candidate import DEFAULT_STRATEGY_NAME
from core.scoring.pipeline import build_hot_candidate_scores


Scorer = Callable[[Any, str, str, float, int, bool], pd.DataFrame]


def select_trade_dates(
    db: Any,
    start: str,
    end: str,
    min_pct_chg: float,
) -> list[str]:
    """Return trade dates that have at least one hot-candidate base row."""
    rows = db.query_sql(
        """
        SELECT trade_date, COUNT(*) AS candidate_count
        FROM daily_kline
        WHERE trade_date BETWEEN ?::DATE AND ?::DATE
          AND COALESCE(flag_suspended, FALSE) = FALSE
          AND COALESCE(flag_invalid_ohlc, FALSE) = FALSE
          AND close > 0
          AND pct_chg >= ?
        GROUP BY trade_date
        ORDER BY trade_date
        """,
        [start, end, float(min_pct_chg)],
    )
    if rows.empty:
        return []
    return pd.to_datetime(rows["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d").dropna().tolist()


def build_scores_for_dates(
    db: Any,
    trade_dates: list[str],
    strategy_name: str,
    min_pct_chg: float,
    lookback_days: int,
    persist: bool = True,
    scorer: Scorer = build_hot_candidate_scores,
) -> list[dict[str, Any]]:
    """Build scores for each date and return a compact daily summary."""
    summary = []
    for trade_date in trade_dates:
        scored = scorer(
            db,
            trade_date,
            strategy_name,
            float(min_pct_chg),
            int(lookback_days),
            bool(persist),
        )
        level_counts = {}
        max_score = 0.0
        if not scored.empty:
            level_counts = {
                str(k): int(v)
                for k, v in scored["score_level"].value_counts().sort_index().items()
            }
            max_score = float(pd.to_numeric(scored["total_score"], errors="coerce").max())
        item = {
            "trade_date": trade_date,
            "rows": int(len(scored)),
            "max_score": max_score,
            "level_counts": level_counts,
        }
        summary.append(item)
        print(
            f"{trade_date} rows={item['rows']} max_score={item['max_score']:.0f} "
            f"levels={item['level_counts']}"
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build hot-candidate scores for a date range")
    parser.add_argument("--start", required=True, help="Start date, e.g. 2026-01-01")
    parser.add_argument("--end", required=True, help="End date, e.g. 2026-06-18")
    parser.add_argument("--config", default="config.yaml", help="Config YAML path")
    parser.add_argument("--strategy-name", default=DEFAULT_STRATEGY_NAME)
    parser.add_argument("--min-pct-chg", type=float, default=9.0)
    parser.add_argument("--lookback-days", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="Build scores without writing to DB")
    parser.add_argument("--output", default=None, help="Optional JSON summary path")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    db = QuantDB(cfg["storage"]["db_path"], cfg)
    db.init_schema()
    try:
        trade_dates = select_trade_dates(db, args.start, args.end, args.min_pct_chg)
        print(f"selected_trade_dates={len(trade_dates)}")
        summary = build_scores_for_dates(
            db,
            trade_dates=trade_dates,
            strategy_name=args.strategy_name,
            min_pct_chg=args.min_pct_chg,
            lookback_days=args.lookback_days,
            persist=not args.dry_run,
        )
    finally:
        db.close()

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"summary_saved={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
