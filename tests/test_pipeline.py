import unittest

import pandas as pd

from pipeline import Pipeline


class FakeFetcher:
    def __init__(self):
        self._tushare_pro = object()
        self.financial_calls = []
        self.name_history_calls = []
        self.audit_calls = []

    def fetch_daily_kline(self, ts_code, start_date, end_date, adjust="none"):
        return pd.DataFrame({
            "ts_code": [ts_code, ts_code],
            "trade_date": pd.to_datetime(["2026-06-15", "2026-06-16"]),
            "open": [10.0, 11.0],
            "high": [10.5, 11.5],
            "low": [9.5, 10.5],
            "close": [10.0, 11.0],
            "vol": [1000.0, 1200.0],
            "amount": [10000.0, 13000.0],
            "adj_factor": [float("nan"), float("nan")],
        })

    def fetch_adj_factor(self, ts_code):
        return pd.DataFrame({
            "trade_date": pd.to_datetime(["2026-06-15", "2026-06-16"]),
            "adj_factor": [1.0, 2.0],
        })

    def fetch_financial_indicators(self, ts_code, start_date, end_date):
        self.financial_calls.append((ts_code, start_date, end_date))
        return pd.DataFrame({
            "ts_code": [ts_code],
            "ann_date": pd.to_datetime(["2026-04-30"]),
            "end_date": pd.to_datetime(["2026-03-31"]),
            "eps": [0.5],
            "bps": [5.0],
            "roe": [10.0],
            "roe_waa": [9.8],
            "profit_yoy": [12.0],
            "revenue_yoy": [8.0],
            "free_cashflow": [1000.0],
            "gross_margin": [35.0],
            "net_margin": [12.0],
            "dt_debt_ratio": [45.0],
        })

    def fetch_stock_name_history(self, ts_code):
        self.name_history_calls.append(ts_code)
        return pd.DataFrame({
            "ts_code": [ts_code],
            "name": ["*ST测试"],
            "start_date": pd.to_datetime(["2021-01-01"]),
            "end_date": pd.to_datetime(["2021-12-31"]),
            "change_reason": ["ST"],
            "is_st": [True],
        })

    def compare_market_sources(
        self, ts_code, start_date, end_date, tolerance_pct, secondary="sina"
    ):
        self.audit_calls.append(
            (ts_code, start_date, end_date, tolerance_pct, secondary)
        )
        return {
            "audit_date": pd.Timestamp("2026-06-16"),
            "ts_code": ts_code,
            "start_date": pd.Timestamp(start_date),
            "end_date": pd.Timestamp(end_date),
            "primary_source": "tencent",
            "secondary_source": secondary,
            "compared_rows": 2,
            "max_close_diff_pct": 0.1,
            "status": "normal",
            "error_msg": None,
        }


class FakeCleaner:
    def clean_kline(self, df, trade_cal):
        result = df.copy()
        result["flag_extreme"] = False
        result["flag_suspended"] = False
        result["flag_aligned"] = False
        result["flag_invalid_ohlc"] = False
        result["pct_chg"] = result["close"].pct_change() * 100
        return result

    def adjust_price(self, df, adj_factor_df, method):
        merged = df.merge(adj_factor_df, on="trade_date", how="left", suffixes=("", "_factor"))
        if "adj_factor_factor" in merged.columns:
            merged["adj_factor"] = merged["adj_factor_factor"]
        latest = merged["adj_factor"].iloc[-1]
        for col in ["open", "high", "low", "close"]:
            merged[f"adj_{col}"] = merged[col] * merged["adj_factor"] / latest
        return merged.drop(columns=["adj_factor_factor"], errors="ignore")


class FakeDB:
    def __init__(self):
        self.financial_batches = []
        self.name_history_batches = []
        self.audit_batches = []

    def upsert_financial(self, df):
        self.financial_batches.append(df.copy())
        return len(df)

    def upsert_stock_name_history(self, df):
        self.name_history_batches.append(df.copy())
        return len(df)

    def upsert_source_audit(self, df):
        self.audit_batches.append(df.copy())
        return len(df)


class PipelineResearchDataTest(unittest.TestCase):
    def make_pipeline(self, config):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.config = config
        pipeline.fetcher = FakeFetcher()
        pipeline.cleaner = FakeCleaner()
        pipeline.db = FakeDB()
        pipeline.stats = {
            "stocks_fetched": 0,
            "stocks_cleaned": 0,
            "stocks_failed": 0,
            "stocks_up_to_date": 0,
            "kline_rows": 0,
            "errors": [],
        }
        return pipeline

    def test_process_single_stock_adds_adj_factor_and_qfq_columns(self):
        pipeline = self.make_pipeline({
            "fetch": {"market_data": {"adj_factor": True}},
            "adjust": {"method": "none"},
        })

        result, error = pipeline._process_single_stock(
            "000001.SZ", "20260615", "20260616", pd.DatetimeIndex([])
        )

        self.assertIsNone(error)
        self.assertEqual(result["adj_factor"].tolist(), [1.0, 2.0])
        self.assertEqual(result["adj_close_qfq"].tolist(), [5.0, 11.0])

    def test_financial_step_fetches_and_upserts_enabled_batch(self):
        pipeline = self.make_pipeline({
            "fetch": {
                "start_date": "20260101",
                "financial_data": {"enabled": True, "batch_size": 2},
            }
        })

        pipeline._step_financial_indicators(
            ["000001.SZ", "600000.SH"], "2026-06-16"
        )

        self.assertEqual(
            pipeline.fetcher.financial_calls,
            [
                ("000001.SZ", "20260101", "20260616"),
                ("600000.SH", "20260101", "20260616"),
            ],
        )
        self.assertEqual(len(pipeline.db.financial_batches), 1)
        self.assertEqual(len(pipeline.db.financial_batches[0]), 2)

    def test_stock_name_history_step_fetches_and_upserts_enabled_batch(self):
        pipeline = self.make_pipeline({
            "stock_pool": {
                "st_history": {"enabled": True, "batch_size": 2}
            }
        })

        pipeline._step_stock_name_history(["000001.SZ", "600000.SH"])

        self.assertEqual(
            pipeline.fetcher.name_history_calls,
            ["000001.SZ", "600000.SH"],
        )
        self.assertEqual(len(pipeline.db.name_history_batches), 1)
        self.assertEqual(len(pipeline.db.name_history_batches[0]), 2)

    def test_source_audit_step_samples_and_upserts_results(self):
        pipeline = self.make_pipeline({
            "quality": {
                "source_audit": {
                    "enabled": True,
                    "sample_size": 1,
                    "lookback_days": 1,
                    "tolerance_pct": 1.0,
                    "secondary": "sina",
                }
            }
        })

        pipeline._step_source_audit(
            ["000001.SZ", "600000.SH"], "2026-06-16"
        )

        self.assertEqual(
            pipeline.fetcher.audit_calls,
            [("000001.SZ", "20260615", "20260616", 1.0, "sina")],
        )
        self.assertEqual(len(pipeline.db.audit_batches), 1)
        self.assertEqual(len(pipeline.db.audit_batches[0]), 1)


if __name__ == "__main__":
    unittest.main()
