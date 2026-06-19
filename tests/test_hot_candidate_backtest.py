import unittest
import os
import tempfile

import pandas as pd

from core.backtest.config import BacktestConfig
from core.backtest.hot_candidate import (
    load_scored_candidates_csv,
    query_kline_for_backtest,
    run_hot_candidate_backtest,
)
from core.data_storage import QuantDB


class HotCandidateBacktestTest(unittest.TestCase):
    def test_runs_backtest_from_scored_candidates_and_filters_rejected_rows(self):
        scored = pd.DataFrame({
            "ts_code": ["A", "B", "C", "A", "B", "C"],
            "trade_date": pd.to_datetime([
                "2024-01-02", "2024-01-02", "2024-01-02",
                "2024-01-03", "2024-01-03", "2024-01-03",
            ]),
            "total_score": [90, 70, 95, 60, 92, 40],
            "is_rejected": [False, False, True, False, False, False],
        })
        kline = pd.DataFrame({
            "ts_code": ["A", "B", "C", "A", "B", "C"],
            "trade_date": pd.to_datetime([
                "2024-01-03", "2024-01-03", "2024-01-03",
                "2024-01-04", "2024-01-04", "2024-01-04",
            ]),
            "open": [10.0, 20.0, 30.0, 11.0, 22.0, 29.0],
            "close": [10.5, 20.5, 30.5, 11.5, 22.5, 29.5],
        })
        config = BacktestConfig(
            start_date="2024-01-02",
            end_date="2024-01-04",
            top_n=1,
            max_positions=1,
            initial_capital=100_000,
            factor_columns=["total_score"],
        )

        result = run_hot_candidate_backtest(
            scored,
            kline,
            config=config,
            min_score=50,
        )

        self.assertGreater(len(result["daily_returns"]), 0)
        self.assertEqual(result["selected_factors"]["ts_code"].tolist(), ["A", "B", "B", "A"])
        self.assertNotIn("C", result["selected_factors"]["ts_code"].tolist())
        self.assertEqual(result["selected_count"], 4)
        self.assertIn("total_return", result)

    def test_empty_after_filter_returns_empty_report_with_selected_count(self):
        scored = pd.DataFrame({
            "ts_code": ["A"],
            "trade_date": pd.to_datetime(["2024-01-02"]),
            "total_score": [20],
            "is_rejected": [False],
        })

        result = run_hot_candidate_backtest(
            scored,
            pd.DataFrame(),
            config=BacktestConfig(start_date="2024-01-02", end_date="2024-01-03"),
            min_score=50,
        )

        self.assertEqual(result["selected_count"], 0)
        self.assertEqual(result["total_return"], 0.0)
        self.assertEqual(result["daily_returns"], [])

    def test_load_scored_candidates_csv_parses_dates_and_rejected_flags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "scores.csv")
            pd.DataFrame({
                "ts_code": ["A", "B"],
                "trade_date": ["2024-01-02", "20240103"],
                "total_score": [90, 80],
                "is_rejected": ["false", "1"],
            }).to_csv(path, index=False)

            loaded = load_scored_candidates_csv(path)

        self.assertEqual(loaded["trade_date"].dt.strftime("%Y-%m-%d").tolist(), [
            "2024-01-02",
            "2024-01-03",
        ])
        self.assertEqual(loaded["is_rejected"].tolist(), [False, True])

    def test_query_kline_for_backtest_filters_to_candidate_codes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = QuantDB(os.path.join(temp_dir, "test.duckdb"))
            db.init_schema()
            try:
                db.upsert_daily_kline_batch(pd.DataFrame({
                    "ts_code": ["A", "B", "C"],
                    "trade_date": pd.to_datetime(["2024-01-03"] * 3),
                    "open": [10.0, 20.0, 30.0],
                    "high": [11.0, 21.0, 31.0],
                    "low": [9.0, 19.0, 29.0],
                    "close": [10.5, 20.5, 30.5],
                    "vol": [1000.0, 2000.0, 3000.0],
                    "amount": [10000.0, 20000.0, 30000.0],
                }))

                kline = query_kline_for_backtest(
                    db,
                    "2024-01-01",
                    "2024-01-05",
                    ts_codes=["A", "C"],
                )
            finally:
                db.close()

        self.assertEqual(kline["ts_code"].tolist(), ["A", "C"])

    def test_script_loads_scored_candidates_from_db(self):
        from argparse import Namespace

        from scripts.run_hot_candidate_backtest import load_scores_for_backtest

        with tempfile.TemporaryDirectory() as temp_dir:
            db = QuantDB(os.path.join(temp_dir, "test.duckdb"))
            db.init_schema()
            try:
                db.upsert_hot_candidate_scores(pd.DataFrame({
                    "ts_code": ["A", "B", "C"],
                    "trade_date": pd.to_datetime(["2024-01-02"] * 3),
                    "total_score": [90, 70, 40],
                    "score_level": ["S", "B", "D"],
                    "is_rejected": [False, False, False],
                }))
                args = Namespace(
                    scores_csv=None,
                    from_db=True,
                    strategy_name="hot_candidate_v2_stable",
                    start="2024-01-01",
                    end="2024-01-05",
                    min_score=60,
                )

                loaded = load_scores_for_backtest(db, args)
            finally:
                db.close()

        self.assertEqual(loaded["ts_code"].tolist(), ["A", "B"])
        self.assertEqual(loaded["total_score"].tolist(), [90, 70])


if __name__ == "__main__":
    unittest.main()
