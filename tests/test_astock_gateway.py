import unittest
from unittest.mock import Mock

import pandas as pd

from core.astock.gateway import AStockDataGateway


class AStockDataGatewayTest(unittest.TestCase):
    def test_daily_kline_prefers_mootdx(self):
        mootdx = Mock()
        baidu = Mock()
        mootdx.fetch_daily_kline.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-16"]),
            "open": [11.1],
            "high": [11.2],
            "low": [10.9],
            "close": [10.94],
            "vol": [1200.0],
            "amount": [131280.0],
            "source": ["mootdx"],
        })
        gateway = AStockDataGateway(mootdx_client=mootdx, baidu_client=baidu)

        result = gateway.fetch_daily_kline("000001.SZ", "20260615", "20260616")

        self.assertEqual(result.iloc[0]["source"], "mootdx")
        baidu.fetch_kline_with_ma.assert_not_called()

    def test_daily_kline_falls_back_to_baidu_not_eastmoney(self):
        mootdx = Mock()
        baidu = Mock()
        eastmoney = Mock()
        mootdx.fetch_daily_kline.return_value = pd.DataFrame()
        baidu.fetch_kline_with_ma.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-16"]),
            "open": [11.1],
            "high": [11.2],
            "low": [10.9],
            "close": [10.94],
            "vol": [1200.0],
            "amount": [131280.0],
            "source": ["baidu"],
        })
        gateway = AStockDataGateway(
            mootdx_client=mootdx,
            baidu_client=baidu,
            eastmoney_client=eastmoney,
        )

        result = gateway.fetch_daily_kline("000001.SZ", "20260615", "20260616")

        self.assertEqual(result.iloc[0]["source"], "baidu")
        eastmoney.em_get.assert_not_called()

    def test_daily_basic_uses_tencent_quote_fields(self):
        tencent = Mock()
        tencent.fetch_quotes.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "pe_ttm": [6.5],
            "pb": [0.7],
            "turnover_rate": [1.2],
            "volume_ratio": [0.9],
            "circ_mv": [1000000000.0],
            "total_mv": [1200000000.0],
        })
        gateway = AStockDataGateway(tencent_client=tencent)

        result = gateway.fetch_daily_basic(["000001.SZ"], "20260616")

        self.assertEqual(result.iloc[0]["trade_date"], pd.Timestamp("2026-06-16"))
        self.assertEqual(result.iloc[0]["pe_ttm"], 6.5)
        self.assertEqual(result.iloc[0]["total_mv"], 1200000000.0)

    def test_daily_basic_accepts_pipeline_style_trade_date_only(self):
        tencent = Mock()
        tencent.fetch_quotes.return_value = pd.DataFrame(columns=[
            "ts_code",
            "pe_ttm",
            "pb",
            "turnover_rate",
            "volume_ratio",
            "circ_mv",
            "total_mv",
        ])
        gateway = AStockDataGateway(
            config={"stock_pool": {"codes": ["000001.SZ"]}},
            tencent_client=tencent,
        )

        result = gateway.fetch_daily_basic("20260616")

        self.assertTrue(result.empty)
        tencent.fetch_quotes.assert_called_once_with(["000001.SZ"])


if __name__ == "__main__":
    unittest.main()
