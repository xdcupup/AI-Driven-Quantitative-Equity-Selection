import os
import tempfile
import unittest

import pandas as pd

from core.data_storage import QuantDB


class QuantDBTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.duckdb")
        self.db = QuantDB(self.db_path)
        self.db.init_schema()

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_batch_upsert_preserves_raw_prices_and_flags(self):
        df = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-15"]),
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "vol": [1000.0],
            "amount": [float("nan")],
            "pct_chg": [1.0],
            "adj_factor": [float("nan")],
            "raw_open": [10.0],
            "raw_high": [10.5],
            "raw_low": [9.8],
            "raw_close": [10.2],
            "flag_extreme": [False],
            "flag_suspended": [False],
            "flag_aligned": [True],
            "flag_invalid_ohlc": [False],
        })

        self.db.upsert_daily_kline_batch(df)
        saved = self.db.query_daily_range(
            "000001.SZ", "2026-06-15", "2026-06-15"
        ).iloc[0]

        self.assertEqual(saved["raw_close"], 10.2)
        self.assertTrue(bool(saved["flag_aligned"]))
        self.assertTrue(pd.isna(saved["amount"]))
        self.assertEqual(
            self.db.get_latest_trade_dates_by_stock()["000001.SZ"],
            pd.Timestamp("2026-06-15"),
        )

    def test_upsert_stock_name_history_and_source_audit(self):
        history = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "name": ["*ST平安"],
            "start_date": pd.to_datetime(["2021-01-01"]),
            "end_date": pd.to_datetime(["2021-12-31"]),
            "change_reason": ["ST"],
            "is_st": [True],
        })
        audit = pd.DataFrame({
            "audit_date": pd.to_datetime(["2026-06-16"]),
            "ts_code": ["000001.SZ"],
            "start_date": pd.to_datetime(["2026-06-15"]),
            "end_date": pd.to_datetime(["2026-06-16"]),
            "primary_source": ["tencent"],
            "secondary_source": ["sina"],
            "compared_rows": [2],
            "max_close_diff_pct": [2.0],
            "status": ["warning"],
            "error_msg": [None],
        })

        self.db.upsert_stock_name_history(history)
        self.db.upsert_source_audit(audit)

        saved_history = self.db.query_sql("SELECT * FROM stock_name_history")
        saved_audit = self.db.query_sql("SELECT * FROM data_source_audit")

        self.assertTrue(bool(saved_history.iloc[0]["is_st"]))
        self.assertEqual(saved_audit.iloc[0]["status"], "warning")

    def test_upsert_financial_statements_preserves_raw_text_and_numeric_value(self):
        statements = pd.DataFrame({
            "ts_code": ["000001.SZ", "000001.SZ"],
            "report_type": ["income_statement", "balance_sheet"],
            "end_date": pd.to_datetime(["2026-03-31", "2026-03-31"]),
            "ann_date": [pd.NaT, pd.NaT],
            "item": ["营业总收入", "审计意见"],
            "value": ["100.5", "标准无保留意见"],
            "item_yoy": ["8.2", None],
            "source": ["sina_finance", "sina_finance"],
        })

        self.db.upsert_financial_statements(statements)

        saved = self.db.query_sql("""
            SELECT report_type, item, value, value_text, item_yoy, source
            FROM financial_statements
            ORDER BY report_type DESC
        """)

        numeric = saved[saved["item"] == "营业总收入"].iloc[0]
        text = saved[saved["item"] == "审计意见"].iloc[0]
        self.assertEqual(numeric["value"], 100.5)
        self.assertEqual(numeric["value_text"], "100.5")
        self.assertEqual(numeric["item_yoy"], 8.2)
        self.assertTrue(pd.isna(text["value"]))
        self.assertEqual(text["value_text"], "标准无保留意见")

    def test_upsert_financial_factors_and_query_latest(self):
        factors = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "end_date": pd.to_datetime(["2026-03-31"]),
            "ann_date": pd.to_datetime(["2026-04-30"]),
            "revenue": [120.0],
            "net_profit": [24.0],
            "total_assets": [500.0],
            "total_liabilities": [300.0],
            "equity": [200.0],
            "operating_cashflow": [30.0],
            "revenue_yoy": [20.0],
            "net_profit_yoy": [20.0],
            "debt_to_assets": [60.0],
            "roe": [12.0],
            "operating_cashflow_to_profit": [1.25],
            "source": ["financial_statements"],
        })

        self.db.upsert_financial_factors(factors)

        saved = self.db.query_latest_financial_factors("2026-06-30")

        self.assertEqual(saved.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(saved.iloc[0]["revenue_yoy"], 20.0)
        self.assertEqual(saved.iloc[0]["roe"], 12.0)

    def test_upsert_technical_factors_and_query_latest(self):
        factors = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-18"]),
            "return_5d": [3.0],
            "return_20d": [12.0],
            "return_60d": [25.0],
            "volatility_20d": [1.5],
            "ma20_bias": [2.2],
            "ma60_bias": [6.0],
            "max_drawdown_60d": [-8.0],
            "volume_ratio_20d": [1.3],
            "liquidity_20d": [100000000.0],
            "source": ["daily_kline"],
        })

        self.db.upsert_technical_factors(factors)

        saved = self.db.query_latest_technical_factors("2026-06-18")

        self.assertEqual(saved.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(saved.iloc[0]["return_20d"], 12.0)
        self.assertEqual(saved.iloc[0]["max_drawdown_60d"], -8.0)

    def test_upsert_factor_labels_and_ic_results(self):
        technical_factors = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-18"]),
            "return_20d": [12.0],
            "ma20_bias": [2.2],
            "source": ["daily_kline"],
        })
        labels = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-18"]),
            "forward_return_5d": [3.0],
            "forward_return_10d": [5.0],
            "forward_return_20d": [8.0],
            "max_drawdown_20d": [-4.0],
            "source": ["daily_kline"],
        })
        ic_detail = pd.DataFrame({
            "factor_name": ["return_20d"],
            "trade_date": pd.to_datetime(["2026-06-18"]),
            "label_name": ["forward_return_20d"],
            "ic": [0.25],
            "sample_count": [100],
            "method": ["spearman"],
            "source": ["factor_ic"],
        })
        ic_summary = pd.DataFrame({
            "factor_name": ["return_20d"],
            "label_name": ["forward_return_20d"],
            "ic_mean": [0.25],
            "ic_std": [0.1],
            "ic_ir": [2.5],
            "sample_dates": [20],
            "method": ["spearman"],
            "source": ["factor_ic"],
        })

        self.db.upsert_technical_factors(technical_factors)
        self.db.upsert_factor_labels(labels)
        self.db.upsert_factor_ic(ic_detail, ic_summary)

        saved_labels = self.db.query_factor_labels_between("2026-06-01", "2026-06-30")
        dataset = self.db.query_factor_dataset(
            "2026-06-01",
            "2026-06-30",
            factor_columns=["return_20d", "ma20_bias"],
            label_column="forward_return_20d",
        )
        saved_detail = self.db.query_sql("SELECT * FROM factor_ic_detail")
        saved_summary = self.db.query_sql("SELECT * FROM factor_ic_summary")

        self.assertEqual(saved_labels.iloc[0]["forward_return_20d"], 8.0)
        self.assertEqual(dataset.iloc[0]["return_20d"], 12.0)
        self.assertEqual(dataset.iloc[0]["forward_return_20d"], 8.0)
        self.assertEqual(saved_detail.iloc[0]["sample_count"], 100)
        self.assertEqual(saved_summary.iloc[0]["ic_ir"], 2.5)

    def test_query_financial_statements_accepts_compact_dates(self):
        statements = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "report_type": ["income_statement"],
            "end_date": pd.to_datetime(["2026-03-31"]),
            "ann_date": [pd.NaT],
            "item_order": [1],
            "item": ["营业总收入"],
            "value": [100.5],
            "source": ["sina_finance"],
        })
        self.db.upsert_financial_statements(statements)

        saved = self.db.query_financial_statements("20260101", "20261231")

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved.iloc[0]["item"], "营业总收入")

    def test_research_universe_excludes_delisted_st_suspended_and_invalid_rows(self):
        stocks = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"],
            "symbol": ["000001", "000002", "000003", "000004", "000005"],
            "name": ["平安银行", "万科A", "*ST金田", "异常股", "正常股"],
            "exchange": ["SZSE"] * 5,
            "area": ["深圳"] * 5,
            "industry": ["银行", "地产", "综合", "综合", "综合"],
            "list_status": ["L", "L", "D", "L", "L"],
            "list_date": pd.to_datetime(["1991-04-03", "1991-01-29", "1991-07-03", "2020-01-01", "2020-01-01"]),
            "delist_date": [pd.NaT, pd.NaT, pd.Timestamp("2026-06-15"), pd.NaT, pd.NaT],
        })
        self.db.conn.register("_tmp_stocks_for_universe", stocks)
        self.db.conn.execute("""
            INSERT INTO stock_list (
                ts_code, symbol, name, exchange, area, industry,
                list_status, list_date, delist_date
            )
            SELECT
                ts_code, symbol, name, exchange, area, industry,
                list_status, list_date, delist_date
            FROM _tmp_stocks_for_universe
        """)

        kline = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"],
            "trade_date": pd.to_datetime(["2026-06-16"] * 5),
            "open": [10.0, 20.0, 30.0, 40.0, 50.0],
            "high": [10.5, 20.5, 30.5, 40.5, 50.5],
            "low": [9.8, 19.8, 29.8, 39.8, 49.8],
            "close": [10.2, 20.2, 30.2, 40.2, 50.2],
            "vol": [1000.0, 0.0, 1000.0, 1000.0, 1000.0],
            "amount": [10000.0] * 5,
            "pct_chg": [1.0] * 5,
            "adj_factor": [1.0] * 5,
            "raw_open": [10.0, 20.0, 30.0, 40.0, 50.0],
            "raw_high": [10.5, 20.5, 30.5, 40.5, 50.5],
            "raw_low": [9.8, 19.8, 29.8, 39.8, 49.8],
            "raw_close": [10.2, 20.2, 30.2, 40.2, 50.2],
            "flag_extreme": [False, False, False, False, False],
            "flag_suspended": [False, True, False, False, False],
            "flag_aligned": [False, False, False, False, False],
            "flag_invalid_ohlc": [False, False, False, True, False],
        })
        self.db.upsert_daily_kline_batch(kline)
        self.db.upsert_stock_name_history(pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "name": ["*ST平安"],
            "start_date": pd.to_datetime(["2026-01-01"]),
            "end_date": pd.to_datetime(["2026-12-31"]),
            "change_reason": ["ST"],
            "is_st": [True],
        }))

        full = self.db.query_research_universe("2026-06-16", only_in_universe=False)
        investable = self.db.query_research_universe("2026-06-16")

        self.assertEqual(investable["ts_code"].tolist(), ["000005.SZ"])
        reasons = dict(zip(full["ts_code"], full["exclude_reason"]))
        self.assertEqual(reasons["000001.SZ"], "historical_st")
        self.assertEqual(reasons["000002.SZ"], "suspended")
        self.assertEqual(reasons["000003.SZ"], "delisted")
        self.assertEqual(reasons["000004.SZ"], "invalid_ohlc")


if __name__ == "__main__":
    unittest.main()
