import unittest

import pandas as pd

from pipeline import Pipeline


class FakeFetcher:
    def __init__(self):
        self._tushare_pro = object()
        self.supports_financial_statements = True
        self.financial_calls = []
        self.statement_calls = []
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

    def fetch_financial_statement(self, ts_code, statement_type, start_date, end_date):
        self.statement_calls.append((ts_code, statement_type, start_date, end_date))
        return pd.DataFrame({
            "ts_code": [ts_code],
            "report_type": [statement_type],
            "end_date": pd.to_datetime(["2026-03-31"]),
            "ann_date": [pd.NaT],
            "item_order": [1],
            "item": ["营业总收入"],
            "value": [100.5],
            "item_yoy": [8.2],
            "source": ["sina_finance"],
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


class CapabilityFetcher(FakeFetcher):
    def __init__(self):
        super().__init__()
        self._tushare_pro = None
        self.supports_financial_indicators = True
        self.supports_financial_statements = True
        self.supports_daily_basic = True
        self.daily_basic_calls = []

    def fetch_daily_basic(self, trade_date):
        self.daily_basic_calls.append(trade_date)
        return pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime([trade_date]),
            "pe": [6.5],
            "pe_ttm": [6.6],
            "pb": [0.7],
            "turnover_rate": [1.2],
            "volume_ratio": [0.9],
            "circ_mv": [100.0],
            "total_mv": [120.0],
        })


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
        self.statement_batches = []
        self.factor_batches = []
        self.technical_factor_batches = []
        self.label_batches = []
        self.ic_batches = []
        self.name_history_batches = []
        self.audit_batches = []
        self.daily_basic_batches = []

    def upsert_financial(self, df):
        self.financial_batches.append(df.copy())
        return len(df)

    def upsert_financial_statements(self, df):
        self.statement_batches.append(df.copy())
        return len(df)

    def query_financial_statements(self, start_date=None, end_date=None):
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * 12,
            "report_type": [
                "income_statement",
                "income_statement",
                "balance_sheet",
                "balance_sheet",
                "balance_sheet",
                "cash_flow",
            ] * 2,
            "end_date": pd.to_datetime(["2026-03-31"] * 6 + ["2025-03-31"] * 6),
            "ann_date": pd.to_datetime(["2026-04-30"] * 6 + ["2025-04-30"] * 6),
            "item_order": list(range(1, 7)) * 2,
            "item": [
                "营业总收入",
                "净利润",
                "资产总计",
                "负债合计",
                "所有者权益合计",
                "经营活动产生的现金流量净额",
                "营业总收入",
                "净利润",
                "资产总计",
                "负债合计",
                "所有者权益合计",
                "经营活动产生的现金流量净额",
            ],
            "value": [
                120.0,
                24.0,
                500.0,
                300.0,
                200.0,
                30.0,
                100.0,
                20.0,
                400.0,
                260.0,
                140.0,
                15.0,
            ],
        })

    def upsert_financial_factors(self, df):
        self.factor_batches.append(df.copy())
        return len(df)

    def query_daily_range(self, ts_code, start_date, end_date, columns="*"):
        dates = pd.date_range("2026-01-01", periods=70, freq="B")
        close = [100.0 + i for i in range(70)]
        vol = [1000.0 + i * 10 for i in range(70)]
        return pd.DataFrame({
            "ts_code": [ts_code] * 70,
            "trade_date": dates,
            "close": close,
            "vol": vol,
            "amount": [close[i] * vol[i] for i in range(70)],
        })

    def upsert_technical_factors(self, df):
        self.technical_factor_batches.append(df.copy())
        return len(df)

    def upsert_factor_labels(self, df):
        self.label_batches.append(df.copy())
        return len(df)

    def query_factor_dataset(
        self,
        start_date,
        end_date,
        factor_columns,
        label_column,
    ):
        return pd.DataFrame({
            "trade_date": pd.to_datetime(["2026-06-01"] * 4 + ["2026-06-02"] * 4),
            "ts_code": ["A", "B", "C", "D"] * 2,
            "return_20d": [1.0, 2.0, 3.0, 4.0, 2.0, 4.0, 6.0, 8.0],
            "ma20_bias": [4.0, 3.0, 2.0, 1.0, 8.0, 6.0, 4.0, 2.0],
            "forward_return_20d": [2.0, 4.0, 6.0, 8.0, 1.0, 2.0, 3.0, 4.0],
        })

    def upsert_factor_ic(self, detail, summary):
        self.ic_batches.append((detail.copy(), summary.copy()))
        return len(detail) + len(summary)

    def upsert_daily_basic(self, df):
        self.daily_basic_batches.append(df.copy())
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

    def test_financial_step_uses_capability_flag_without_tushare(self):
        pipeline = self.make_pipeline({
            "fetch": {
                "start_date": "20260101",
                "financial_data": {"enabled": True, "batch_size": 2},
            }
        })
        pipeline.fetcher = CapabilityFetcher()

        pipeline._step_financial_indicators(["000001.SZ"], "2026-06-16")

        self.assertEqual(
            pipeline.fetcher.financial_calls,
            [("000001.SZ", "20260101", "20260616")],
        )
        self.assertEqual(len(pipeline.db.financial_batches), 1)

    def test_financial_statement_step_fetches_three_reports_and_upserts_batch(self):
        pipeline = self.make_pipeline({
            "fetch": {
                "start_date": "20260101",
                "financial_statements": {
                    "enabled": True,
                    "batch_size": 3,
                    "statement_types": ["income_statement", "balance_sheet", "cash_flow"],
                    "full_refresh_only": False,
                },
            }
        })

        pipeline._step_financial_statements(
            ["000001.SZ", "600000.SH"], "2026-06-16", full_refresh=False
        )

        self.assertEqual(
            pipeline.fetcher.statement_calls,
            [
                ("000001.SZ", "income_statement", "20260101", "20260616"),
                ("000001.SZ", "balance_sheet", "20260101", "20260616"),
                ("000001.SZ", "cash_flow", "20260101", "20260616"),
                ("600000.SH", "income_statement", "20260101", "20260616"),
                ("600000.SH", "balance_sheet", "20260101", "20260616"),
                ("600000.SH", "cash_flow", "20260101", "20260616"),
            ],
        )
        self.assertEqual(len(pipeline.db.statement_batches), 2)
        self.assertEqual(sum(len(df) for df in pipeline.db.statement_batches), 6)

    def test_financial_statement_step_respects_full_refresh_only(self):
        pipeline = self.make_pipeline({
            "fetch": {
                "financial_statements": {
                    "enabled": True,
                    "full_refresh_only": True,
                }
            }
        })

        pipeline._step_financial_statements(
            ["000001.SZ"], "2026-06-16", full_refresh=False
        )

        self.assertEqual(pipeline.fetcher.statement_calls, [])
        self.assertEqual(pipeline.db.statement_batches, [])

    def test_financial_factor_step_derives_and_upserts_factors(self):
        pipeline = self.make_pipeline({
            "fetch": {
                "start_date": "20250101",
                "factor_derivation": {"enabled": True}
            }
        })

        pipeline._step_financial_factors("2026-06-16")

        self.assertEqual(len(pipeline.db.factor_batches), 1)
        factors = pipeline.db.factor_batches[0]
        current = factors[factors["end_date"] == pd.Timestamp("2026-03-31")].iloc[0]
        self.assertEqual(current["revenue_yoy"], 20.0)
        self.assertEqual(current["debt_to_assets"], 60.0)

    def test_daily_basic_step_uses_capability_flag_without_tushare(self):
        pipeline = self.make_pipeline({
            "fetch": {"market_data": {"daily_basic": True}}
        })
        pipeline.fetcher = CapabilityFetcher()

        pipeline._step_daily_basic("2026-06-16")

        self.assertEqual(pipeline.fetcher.daily_basic_calls, ["20260616"])
        self.assertEqual(len(pipeline.db.daily_basic_batches), 1)

    def test_technical_factor_step_derives_and_upserts_for_codes(self):
        pipeline = self.make_pipeline({
            "fetch": {
                "technical_factors": {"enabled": True, "lookback_days": 120}
            }
        })

        pipeline._step_technical_factors(["000001.SZ"], "2026-06-18")

        self.assertEqual(len(pipeline.db.technical_factor_batches), 1)
        factors = pipeline.db.technical_factor_batches[0]
        self.assertFalse(factors.empty)
        self.assertIn("return_20d", factors.columns)
        self.assertEqual(factors.iloc[-1]["source"], "daily_kline")

    def test_factor_label_step_derives_and_upserts_for_codes(self):
        pipeline = self.make_pipeline({
            "fetch": {
                "factor_labels": {
                    "enabled": True,
                    "lookback_days": 120,
                    "horizons": [5, 10, 20],
                    "drawdown_horizon": 20,
                }
            }
        })

        pipeline._step_factor_labels(["000001.SZ"], "2026-06-18")

        self.assertEqual(len(pipeline.db.label_batches), 1)
        labels = pipeline.db.label_batches[0]
        self.assertFalse(labels.empty)
        self.assertIn("forward_return_20d", labels.columns)
        self.assertEqual(labels.iloc[0]["source"], "daily_kline")

    def test_factor_ic_step_evaluates_and_upserts_results(self):
        pipeline = self.make_pipeline({
            "evaluation": {
                "factor_ic": {
                    "enabled": True,
                    "lookback_days": 30,
                    "factor_columns": ["return_20d", "ma20_bias"],
                    "label_column": "forward_return_20d",
                }
            }
        })

        pipeline._step_factor_ic("2026-06-18")

        self.assertEqual(len(pipeline.db.ic_batches), 1)
        detail, summary = pipeline.db.ic_batches[0]
        self.assertEqual(len(detail), 4)
        self.assertEqual(set(summary["factor_name"]), {"return_20d", "ma20_bias"})

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


class PipelineSourceSelectionTest(unittest.TestCase):
    def test_select_fetcher_class_returns_astock_gateway_when_configured(self):
        from pipeline import select_fetcher_class
        from core.astock.gateway import AStockDataGateway

        self.assertIs(
            select_fetcher_class({"data_source": {"engine": "astock"}}),
            AStockDataGateway,
        )


if __name__ == "__main__":
    unittest.main()
