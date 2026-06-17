import unittest

import pandas as pd

from core.data_quality import QualityMonitor


class FakeQualityDB:
    def query_cross_section(self, trade_date):
        return pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "trade_date": pd.to_datetime([trade_date, trade_date]),
            "open": [10.0, 20.0],
            "high": [10.5, 21.0],
            "low": [9.8, 19.5],
            "close": [10.2, 20.5],
            "vol": [1000.0, 2000.0],
            "amount": [float("nan"), float("nan")],
            "adj_factor": [float("nan"), float("nan")],
            "flag_suspended": [False, False],
            "flag_invalid_ohlc": [False, False],
            "pct_chg": [1.0, 2.0],
        })

    @property
    def conn(self):
        class Conn:
            def execute(self, sql):
                class Cursor:
                    def fetchone(self):
                        return (pd.Timestamp("2026-06-16").date(), pd.Timestamp("2026-06-16").date())
                return Cursor()
        return Conn()


class QualityMonitorTest(unittest.TestCase):
    def test_known_missing_fields_do_not_create_missing_anomalies(self):
        monitor = QualityMonitor(
            FakeQualityDB(),
            {
                "quality": {
                    "known_missing_fields": ["amount", "adj_factor"],
                    "alerts": {"missing_data_ratio": 0.05},
                    "report": {"save_raw": False},
                }
            },
        )

        report = monitor.generate_daily_report("2026-06-16")

        self.assertNotIn("amount", report["missing_rate"])
        self.assertFalse(
            any("amount 缺失率" in anomaly for anomaly in report["anomalies"])
        )


if __name__ == "__main__":
    unittest.main()
