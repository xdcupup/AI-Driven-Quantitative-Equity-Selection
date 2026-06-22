import unittest

import pandas as pd

from scripts.build_hot_candidate_scores import build_scores_for_dates, select_trade_dates


class HotCandidateScoreBatchTest(unittest.TestCase):
    def test_select_trade_dates_filters_by_min_pct_chg(self):
        class FakeDB:
            def query_sql(self, sql, params=None):
                self.sql = sql
                self.params = params
                return pd.DataFrame({
                    "trade_date": pd.to_datetime(["2026-06-17", "2026-06-18"]),
                    "candidate_count": [3, 5],
                })

        db = FakeDB()

        result = select_trade_dates(db, "2026-06-01", "2026-06-18", 9.0)

        self.assertEqual(result, ["2026-06-17", "2026-06-18"])
        self.assertEqual(db.params, ["2026-06-01", "2026-06-18", 9.0])
        self.assertIn("pct_chg >= ?", db.sql)

    def test_build_scores_for_dates_returns_daily_summary(self):
        calls = []

        def scorer(db, trade_date, strategy_name, min_pct_chg, lookback_days, persist):
            calls.append((trade_date, strategy_name, min_pct_chg, lookback_days, persist))
            return pd.DataFrame({
                "total_score": [90, 75],
                "score_level": ["S", "A"],
            })

        summary = build_scores_for_dates(
            db=object(),
            trade_dates=["2026-06-17", "2026-06-18"],
            strategy_name="hot_candidate_v2_stable",
            min_pct_chg=9.0,
            lookback_days=10,
            persist=True,
            scorer=scorer,
        )

        self.assertEqual(len(summary), 2)
        self.assertEqual(summary[0]["rows"], 2)
        self.assertEqual(summary[0]["max_score"], 90.0)
        self.assertEqual(summary[0]["level_counts"], {"A": 1, "S": 1})
        self.assertEqual(calls[0], ("2026-06-17", "hot_candidate_v2_stable", 9.0, 10, True))


if __name__ == "__main__":
    unittest.main()
