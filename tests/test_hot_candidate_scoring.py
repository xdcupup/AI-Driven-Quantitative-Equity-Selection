import unittest

import pandas as pd

from core.scoring.hot_candidate import score_hot_candidates


class HotCandidateScoringTest(unittest.TestCase):
    def test_scores_full_strength_candidate_to_100_without_theme_in_total(self):
        candidates = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-19"]),
            "open_gap_pct": [3.0],
            "is_one_price_limit_up": [False],
            "ddx": [0.8],
            "ddy": [0.6],
            "main_direction_5d": [1.0],
            "seal_ratio": [5.2],
            "seal_float_mv_ratio": [2.1],
            "main_buy_ratio": [0.35],
            "volume_ratio": [2.0],
            "turnover_rate": [12.0],
            "is_st": [False],
            "is_delisted": [False],
            "safety_score": [95.0],
            "circ_mv": [80.0],
            "amount": [4.0],
            "sector_limit_up_count": [8],
            "sector_pct_chg": [3.5],
            "sector_main_direction": [1.0],
            "sector_rank": [1],
            "limit_up_streak": [2],
            "theme_score": [6.0],
            "theme_evidence": ["AI+算力"],
            "theme_suspicious": [False],
        })

        scored = score_hot_candidates(candidates)
        row = scored.iloc[0]

        self.assertEqual(row["buyability_score"], 20)
        self.assertEqual(row["capital_persistence_score"], 18)
        self.assertEqual(row["seal_quality_score"], 15)
        self.assertEqual(row["support_quality_score"], 15)
        self.assertEqual(row["safety_filter_score"], 10)
        self.assertEqual(row["liquidity_structure_score"], 10)
        self.assertEqual(row["sector_resonance_score"], 8)
        self.assertEqual(row["leader_status_score"], 4)
        self.assertEqual(row["theme_validation_score"], 6.0)
        self.assertEqual(row["total_score"], 100)
        self.assertEqual(row["score_level"], "S")
        self.assertFalse(bool(row["is_rejected"]))

    def test_uses_conservative_low_scores_for_missing_fields(self):
        candidates = pd.DataFrame({
            "ts_code": ["000002.SZ"],
            "trade_date": pd.to_datetime(["2026-06-19"]),
        })

        row = score_hot_candidates(candidates).iloc[0]

        self.assertEqual(row["buyability_score"], 0)
        self.assertEqual(row["capital_persistence_score"], 1)
        self.assertEqual(row["seal_quality_score"], 2)
        self.assertEqual(row["support_quality_score"], 2)
        self.assertEqual(row["safety_filter_score"], 1)
        self.assertEqual(row["liquidity_structure_score"], 2)
        self.assertEqual(row["sector_resonance_score"], 0)
        self.assertEqual(row["leader_status_score"], 1)
        self.assertEqual(row["total_score"], 9)
        self.assertIn("missing:open_gap_pct", row["score_reason"])

    def test_rejects_st_or_delisted_candidates(self):
        candidates = pd.DataFrame({
            "ts_code": ["000003.SZ", "000004.SZ"],
            "trade_date": pd.to_datetime(["2026-06-19"] * 2),
            "open_gap_pct": [2.0, 2.0],
            "is_st": [True, False],
            "is_delisted": [False, True],
        })

        scored = score_hot_candidates(candidates)

        self.assertTrue(scored["is_rejected"].all())
        self.assertEqual(scored["safety_filter_score"].tolist(), [0, 0])
        self.assertTrue(all("safety_reject" in r for r in scored["score_reason"]))

    def test_open_gap_and_one_price_limit_up_thresholds(self):
        candidates = pd.DataFrame({
            "ts_code": ["A", "B", "C", "D", "E", "F"],
            "trade_date": pd.to_datetime(["2026-06-19"] * 6),
            "open_gap_pct": [3.0, 0.5, -1.0, 6.0, 9.6, 10.0],
            "is_one_price_limit_up": [False, False, False, False, False, True],
        })

        scored = score_hot_candidates(candidates)

        self.assertEqual(
            scored["buyability_score"].tolist(),
            [20, 17, 14, 10, 0, 0],
        )

    def test_enrich_adds_sector_counts_from_theme_stocks(self):
        from core.scoring.enrich import enrich_sector_info

        candidates = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-19"]),
        })
        theme_stocks = pd.DataFrame({
            "theme_code": ["T1", "T1", "T1"],
            "trade_date": pd.to_datetime(["2026-06-19"] * 3),
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
        })
        result = enrich_sector_info(candidates, pd.DataFrame(), pd.DataFrame(), theme_stocks)
        self.assertEqual(result.iloc[0]["sector_limit_up_count"], 3)

    def test_enrich_fund_flow_adds_ddx_ddy(self):
        from core.scoring.enrich import enrich_fund_flow
        candidates = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-19"]),
        })
        ff = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-19"]),
            "ddx": [0.75],
            "ddy": [0.62],
        })
        result = enrich_fund_flow(candidates, ff)
        self.assertAlmostEqual(result.iloc[0]["ddx"], 0.75)

    def test_build_hot_candidate_scores_from_db_sources(self):
        from core.scoring.pipeline import build_hot_candidate_scores

        class FakeScoreDB:
            def __init__(self):
                self.saved = []

            def query_sql(self, sql, params=None):
                if "FROM daily_kline k" in sql:
                    return pd.DataFrame({
                        "ts_code": ["000001.SZ", "000002.SZ"],
                        "trade_date": pd.to_datetime(["2026-06-19"] * 2),
                        "open": [10.5, 20.0],
                        "high": [11.0, 20.5],
                        "low": [10.3, 19.8],
                        "close": [11.0, 20.5],
                        "vol": [2000.0, 1500.0],
                        "amount": [420000000.0, 180000000.0],
                        "pct_chg": [10.0, 4.0],
                        "turnover_rate": [12.0, 8.0],
                        "volume_ratio": [2.0, 1.1],
                        "circ_mv": [8000000000.0, 12000000000.0],
                        "total_mv": [12000000000.0, 15000000000.0],
                    })
                if "FROM daily_kline" in sql:
                    return pd.DataFrame({
                        "ts_code": ["000001.SZ", "000001.SZ"],
                        "trade_date": pd.to_datetime(["2026-06-18", "2026-06-19"]),
                        "open": [10.0, 10.5],
                        "close": [10.0, 11.0],
                        "vol": [1000.0, 2000.0],
                        "pct_chg": [1.0, 10.0],
                    })
                if "FROM stock_fund_flow_daily" in sql:
                    return pd.DataFrame({
                        "ts_code": ["000001.SZ"],
                        "trade_date": pd.to_datetime(["2026-06-19"]),
                        "ddx": [0.8],
                        "ddy": [0.7],
                        "main_net_ratio": [6.0],
                    })
                if "FROM hot_theme_daily" in sql:
                    return pd.DataFrame({
                        "theme_code": ["T1"],
                        "trade_date": pd.to_datetime(["2026-06-19"]),
                        "theme_name": ["AI"],
                        "rank": [1],
                        "pct_chg": [3.2],
                    })
                if "FROM hot_theme_stocks" in sql:
                    return pd.DataFrame({
                        "theme_code": ["T1", "T1", "T1"],
                        "trade_date": pd.to_datetime(["2026-06-19"] * 3),
                        "ts_code": ["000001.SZ", "000003.SZ", "000004.SZ"],
                    })
                return pd.DataFrame()

            def upsert_hot_candidate_scores(self, df, strategy_name="hot_candidate_v1"):
                self.saved.append(df.copy())
                return len(df)

        db = FakeScoreDB()
        scored = build_hot_candidate_scores(db, "2026-06-19", min_pct_chg=9.0)

        self.assertEqual(scored["ts_code"].tolist(), ["000001.SZ"])
        row = scored.iloc[0]
        self.assertEqual(row["source"], "hot_candidate_pipeline")
        self.assertGreater(row["total_score"], 60)
        self.assertEqual(len(db.saved), 1)
        self.assertEqual(db.saved[0].iloc[0]["ts_code"], "000001.SZ")


if __name__ == "__main__":
    unittest.main()
