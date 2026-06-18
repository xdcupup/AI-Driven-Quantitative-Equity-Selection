import unittest

from core.astock.symbols import normalize_code


class AStockSymbolTest(unittest.TestCase):
    def test_normalize_code_accepts_common_formats(self):
        self.assertEqual(normalize_code("688017").symbol, "688017")
        self.assertEqual(normalize_code("SH688017").ts_code, "688017.SH")
        self.assertEqual(normalize_code("688017.sh").ts_code, "688017.SH")
        self.assertEqual(normalize_code("SZ000001").ts_code, "000001.SZ")
        self.assertEqual(normalize_code("BJ832000").ts_code, "832000.BJ")

    def test_market_prefixes_match_astock_skill(self):
        self.assertEqual(normalize_code("600519").http_prefix, "sh")
        self.assertEqual(normalize_code("000001").http_prefix, "sz")
        self.assertEqual(normalize_code("832000").http_prefix, "bj")
        self.assertEqual(normalize_code("600519").mootdx_market, 1)
        self.assertEqual(normalize_code("000001").mootdx_market, 0)

    def test_bse_is_marked_not_supported_by_mootdx_stage_one(self):
        self.assertFalse(normalize_code("832000").supports_mootdx_stage_one)
        self.assertTrue(normalize_code("600519").supports_mootdx_stage_one)


if __name__ == "__main__":
    unittest.main()
