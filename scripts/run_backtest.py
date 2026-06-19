#!/usr/bin/env python3
"""Run factor backtest with real data and output results.

Usage: python scripts/run_backtest.py [--start 2024-01-01] [--end 2026-06-19]
"""

import argparse
import json
import os
import sys
from datetime import datetime

import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.backtest.config import BacktestConfig
from core.backtest.engine import BacktestEngine
from core.backtest.analytics import compute_layer_returns
from core.data_storage import QuantDB
from core.factors.technical import derive_technical_factors
from core.factors.labels import derive_forward_return_labels


def main():
    parser = argparse.ArgumentParser(description="Factor backtest runner")
    parser.add_argument("--start", default="2024-01-01", help="Start date")
    parser.add_argument("--end", default=None, help="End date (default: today)")
    args = parser.parse_args()

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    db = QuantDB(cfg["storage"]["db_path"], cfg)

    # Ensure schema is initialized
    db.init_schema()

    end_date = args.end or datetime.now().strftime("%Y-%m-%d")
    print(f"回测区间: {args.start} → {end_date}")

    # ── Auto-generate factors and labels if missing ──
    n_factors = (db.conn.execute("SELECT COUNT(*) FROM technical_factors").fetchone() or [0])[0]
    n_labels = (db.conn.execute("SELECT COUNT(*) FROM factor_labels").fetchone() or [0])[0]

    if n_factors == 0 or n_labels == 0:
        print("因子/标签数据缺失，正在从 K 线自动生成...")

        # Fetch all kline data for factor derivation
        lookback_start = pd.Timestamp(args.start) - pd.Timedelta(days=365)
        kline_all = db.conn.execute(
            "SELECT ts_code, trade_date, open, close, high, low, vol, amount "
            "FROM daily_kline ORDER BY ts_code, trade_date"
        ).df()

        if kline_all.empty:
            print("ERROR: daily_kline 表无数据，无法生成因子")
            sys.exit(1)

        print(f"  从 {len(kline_all)} 条 K 线记录派生因子...")

        if n_factors == 0:
            factors_df = derive_technical_factors(kline_all)
            factors_df = factors_df.dropna(subset=["return_20d", "return_60d", "volatility_20d"])
            if not factors_df.empty:
                db.upsert_technical_factors(factors_df)
                print(f"  已生成 {len(factors_df)} 条技术因子")
            else:
                print("  WARNING: 生成的因子数据为空（可能需要更长历史数据）")

        if n_labels == 0:
            labels_df = derive_forward_return_labels(kline_all)
            labels_df = labels_df.dropna(subset=["forward_return_20d"])
            if not labels_df.empty:
                db.upsert_factor_labels(labels_df)
                print(f"  已生成 {len(labels_df)} 条标签")
            else:
                print("  WARNING: 生成的标签数据为空（未来窗口不足）")

        print()

    # ── Load config ──
    bt_cfg_dict = cfg.get("backtest", {})
    bt_config = BacktestConfig.from_dict(bt_cfg_dict)

    # ── Query factor dataset ──
    factors = db.query_factor_dataset(
        args.start.replace("-", ""),
        end_date.replace("-", ""),
        factor_columns=bt_config.factor_columns,
        label_column=bt_config.label_column,
    )
    print(f"因子数据: {len(factors)} 行, {factors['ts_code'].nunique()} 只股票")

    # ── Query labels ──
    labels = db.conn.execute(
        "SELECT * FROM factor_labels WHERE trade_date BETWEEN ? AND ?",
        [args.start, end_date],
    ).df()
    print(f"标签数据: {len(labels)} 行")

    # ── Query kline ──
    kline = db.conn.execute(
        "SELECT ts_code, trade_date, open, close, high, low, vol, amount "
        "FROM daily_kline WHERE trade_date BETWEEN ? AND ?",
        [args.start, end_date],
    ).df()
    print(f"K线数据: {len(kline)} 行")

    print()

    # ── Run backtest ──
    engine = BacktestEngine(bt_config)
    report = engine.run(factors, labels, kline)

    print(f"========== 回测结果 ==========")
    print(f"区间:      {args.start} → {end_date}")
    print(f"交易天数:  {report.get('n_days', 0)}")
    print(f"总收益:    {report['total_return']:.2%}")
    print(f"年化收益:  {report['annual_return']:.2%}")
    print(f"Sharpe:   {report['sharpe_ratio']:.2f}")
    print(f"最大回撤:  {report['max_drawdown']:.2%}")
    print(f"Calmar:   {report['calmar_ratio']:.2f}")
    print(f"Sortino:  {report['sortino_ratio']:.2f}")
    print(f"胜率:      {report['win_rate']:.2%}")

    # ── Layer analysis for each factor ──
    print(f"\n========== 因子分层分析 (5分位) ==========")
    for factor in bt_config.factor_columns:
        layer = compute_layer_returns(
            factors, labels, factor, bt_config.label_column, n_groups=5
        )
        spread = layer.get("spread", 0)
        ic_mean = layer.get("ic_mean", 0)
        print(f"  {factor:20s} | spread={spread:+.4f}  ic_mean={ic_mean:+.4f}")

    # ── Save report ──
    os.makedirs(bt_config.output_dir, exist_ok=True)
    report_path = os.path.join(bt_config.output_dir, f"backtest_{end_date}.json")
    report_save = {
        k: v
        for k, v in report.items()
        if k not in ("daily_returns", "trades", "nav_series")
    }
    with open(report_path, "w") as f:
        json.dump(report_save, f, indent=2, default=str)
    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()
