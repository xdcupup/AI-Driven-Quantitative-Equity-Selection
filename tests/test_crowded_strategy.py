import unittest

import pandas as pd

from core.strategies.crowded import (
    calculate_equal_weight_momentum,
    generate_crowded_rebalance_signal,
    select_crowded_stocks,
)


class CrowdedStockStrategyTest(unittest.TestCase):
    def test_selects_top_average_amount_stocks_with_universe_filters(self):
        stocks = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"],
            "name": ["平安银行", "万科A", "*ST测试", "新股", "未知上市日"],
            "list_status": ["L", "L", "L", "L", "L"],
            "list_date": pd.to_datetime([
                "2020-01-01",
                "2020-01-01",
                "2020-01-01",
                "2026-05-01",
                None,
            ]),
        })
        rows = []
        dates = pd.date_range("2026-05-01", periods=22, freq="B")
        for code, amount in {
            "000001.SZ": 300.0,
            "000002.SZ": 500.0,
            "000003.SZ": 900.0,
            "000004.SZ": 800.0,
            "000005.SZ": 700.0,
        }.items():
            for date in dates:
                rows.append({
                    "ts_code": code,
                    "trade_date": date,
                    "close": 10.0,
                    "vol": 100.0,
                    "amount": amount,
                    "flag_suspended": False,
                    "flag_invalid_ohlc": False,
                })
        kline = pd.DataFrame(rows)

        selected = select_crowded_stocks(
            stocks,
            kline,
            as_of_date="2026-06-05",
            stock_num=2,
            lookback_days=22,
            min_listing_days=120,
        )

        self.assertEqual(selected["ts_code"].tolist(), ["000005.SZ", "000002.SZ"])
        self.assertEqual(selected.iloc[0]["avg_amount"], 700.0)
        self.assertEqual(selected.iloc[0]["rank"], 1)

    def test_momentum_uses_equal_weight_returns_before_signal_date(self):
        dates = pd.date_range("2026-05-01", periods=26, freq="B")
        rows = []
        for i, date in enumerate(dates):
            rows.append({
                "ts_code": "000001.SZ",
                "trade_date": date,
                "close": 100.0 + i,
            })
            rows.append({
                "ts_code": "000002.SZ",
                "trade_date": date,
                "close": 200.0 - i,
            })
        kline = pd.DataFrame(rows)

        momentum = calculate_equal_weight_momentum(
            kline,
            ["000001.SZ", "000002.SZ"],
            as_of_date="2026-06-10",
            momentum_days=25,
        )

        expected = (((125.0 / 100.0) - 1) + ((175.0 / 200.0) - 1)) / 2
        self.assertAlmostEqual(momentum, expected)

    def test_rebalance_signal_matches_original_state_machine(self):
        self.assertEqual(
            generate_crowded_rebalance_signal(
                target_stocks=["000001.SZ"],
                momentum=0.01,
                current_positions=[],
            )["action"],
            "open_equal_weight",
        )
        self.assertEqual(
            generate_crowded_rebalance_signal(
                target_stocks=["000001.SZ"],
                momentum=-0.01,
                current_positions=["000001.SZ"],
            )["action"],
            "clear",
        )
        self.assertEqual(
            generate_crowded_rebalance_signal(
                target_stocks=[],
                momentum=0.0,
                current_positions=["000001.SZ"],
            )["reason"],
            "empty_target",
        )


if __name__ == "__main__":
    unittest.main()
