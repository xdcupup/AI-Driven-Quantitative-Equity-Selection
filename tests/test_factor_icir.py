import unittest

import pandas as pd

from core.evaluation.icir import evaluate_factor_ic


class FactorICIRTest(unittest.TestCase):
    def test_evaluates_cross_sectional_ic_and_ir(self):
        dataset = pd.DataFrame({
            "trade_date": pd.to_datetime(["2026-06-01"] * 4 + ["2026-06-02"] * 4),
            "ts_code": ["A", "B", "C", "D"] * 2,
            "return_20d": [1.0, 2.0, 3.0, 4.0, 2.0, 4.0, 6.0, 8.0],
            "ma20_bias": [4.0, 3.0, 2.0, 1.0, 8.0, 6.0, 4.0, 2.0],
            "forward_return_20d": [2.0, 4.0, 6.0, 8.0, 1.0, 2.0, 3.0, 4.0],
        })

        detail, summary = evaluate_factor_ic(
            dataset,
            factor_columns=["return_20d", "ma20_bias"],
            label_column="forward_return_20d",
        )

        self.assertEqual(len(detail), 4)
        positive = summary[summary["factor_name"] == "return_20d"].iloc[0]
        negative = summary[summary["factor_name"] == "ma20_bias"].iloc[0]
        self.assertEqual(positive["ic_mean"], 1.0)
        self.assertEqual(negative["ic_mean"], -1.0)
        self.assertEqual(positive["sample_dates"], 2)
        self.assertEqual(positive["source"], "factor_ic")

    def test_empty_input_returns_stable_schemas(self):
        detail, summary = evaluate_factor_ic(
            pd.DataFrame(),
            factor_columns=["return_20d"],
            label_column="forward_return_20d",
        )

        self.assertTrue(detail.empty)
        self.assertTrue(summary.empty)
        self.assertIn("ic", detail.columns)
        self.assertIn("ic_ir", summary.columns)


if __name__ == "__main__":
    unittest.main()
