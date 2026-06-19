#!/usr/bin/env python3
"""Run a backtest from scored hot-candidate rows.

Usage:
  python scripts/run_hot_candidate_backtest.py \
    --scores-csv data/hot_candidates/scored.csv \
    --start 2026-06-01 --end 2026-06-19
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.backtest.config import BacktestConfig
from core.backtest.hot_candidate import (
    load_scored_candidates_csv,
    query_kline_for_backtest,
    run_hot_candidate_backtest,
)
from core.data_storage import QuantDB


def _build_backtest_config(cfg: dict, args: argparse.Namespace) -> BacktestConfig:
    bt_cfg = BacktestConfig.from_dict(cfg.get("backtest", {}))
    bt_cfg.start_date = args.start
    bt_cfg.end_date = args.end
    bt_cfg.factor_columns = [args.score_column]
    bt_cfg.top_n = args.top_n
    bt_cfg.max_positions = args.max_positions
    bt_cfg.initial_capital = args.initial_capital
    return bt_cfg


def _serializable_report(report: dict) -> dict:
    return {
        key: value
        for key, value in report.items()
        if key not in {"daily_returns", "trades", "nav_series", "selected_factors"}
    }


def load_scores_for_backtest(db: QuantDB, args: argparse.Namespace):
    if args.from_db:
        return db.query_hot_candidate_scores(
            args.start,
            args.end,
            strategy_name=args.strategy_name,
            min_score=args.min_score,
        )
    return load_scored_candidates_csv(args.scores_csv)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hot-candidate scoring backtest runner")
    score_input = parser.add_mutually_exclusive_group(required=True)
    score_input.add_argument("--scores-csv", help="CSV exported from score_hot_candidates")
    score_input.add_argument("--from-db", action="store_true", help="Read scores from hot_candidate_scores")
    parser.add_argument("--start", required=True, help="Start date, e.g. 2026-06-01")
    parser.add_argument("--end", default=None, help="End date (default: today)")
    parser.add_argument("--config", default="config.yaml", help="Config YAML path")
    parser.add_argument("--strategy-name", default="hot_candidate_v1", help="Score strategy name for DB mode")
    parser.add_argument("--min-score", type=float, default=60.0, help="Minimum total score")
    parser.add_argument("--score-column", default="total_score", help="Score column to rank by")
    parser.add_argument("--top-n", type=int, default=10, help="Daily selected candidate count")
    parser.add_argument("--max-positions", type=int, default=10, help="Portfolio max positions")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--output", default=None, help="Optional JSON report path")
    args = parser.parse_args()

    args.end = args.end or datetime.now().strftime("%Y-%m-%d")

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    db = QuantDB(cfg["storage"]["db_path"], cfg)
    db.init_schema()
    try:
        scored = load_scores_for_backtest(db, args)
        ts_codes = sorted(scored["ts_code"].dropna().astype(str).unique().tolist())
        kline = query_kline_for_backtest(db, args.start, args.end, ts_codes=ts_codes)
    finally:
        db.close()

    bt_config = _build_backtest_config(cfg, args)
    report = run_hot_candidate_backtest(
        scored,
        kline,
        config=bt_config,
        min_score=args.min_score,
        score_column=args.score_column,
    )

    print("========== 热榜候选回测结果 ==========")
    print(f"区间:        {args.start} -> {args.end}")
    score_source = "DB" if args.from_db else args.scores_csv
    print(f"评分来源:    {score_source}")
    print(f"候选行数:    {len(scored)}")
    print(f"入选信号:    {report.get('selected_count', 0)}")
    print(f"K线行数:     {len(kline)}")
    print(f"交易天数:    {report.get('n_days', 0)}")
    print(f"总收益:      {report.get('total_return', 0.0):.2%}")
    print(f"年化收益:    {report.get('annual_return', 0.0):.2%}")
    print(f"Sharpe:     {report.get('sharpe_ratio', 0.0):.2f}")
    print(f"最大回撤:    {report.get('max_drawdown', 0.0):.2%}")
    print(f"胜率:        {report.get('win_rate', 0.0):.2%}")

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(_serializable_report(report), f, indent=2, ensure_ascii=False, default=str)
        print(f"\n报告已保存: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
