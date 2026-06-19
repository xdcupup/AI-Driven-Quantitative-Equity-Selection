import unittest
from unittest.mock import Mock

from core.astock.eastmoney.concept import fetch_stock_concepts, fetch_concept_stocks


class EastMoneyConceptTest(unittest.TestCase):
    def test_fetch_stock_concepts_returns_empty_for_empty_response(self):
        client = Mock()
        client.datacenter.return_value = []
        result = fetch_stock_concepts(client, "000001.SZ")
        self.assertTrue(result.empty)
        self.assertEqual(list(result.columns), ["ts_code", "concept_code", "concept_name", "source"])

    def test_fetch_concept_stocks_returns_empty_for_empty_response(self):
        client = Mock()
        client.datacenter.return_value = []
        result = fetch_concept_stocks(client, "BK0001")
        self.assertTrue(result.empty)

    def test_fetch_stock_concepts_parses_datacenter_response(self):
        client = Mock()
        client.datacenter.return_value = [
            {"SECURITY_CODE": "000001.SZ", "BOARD_CODE": "BK0001", "BOARD_NAME": "人工智能"},
            {"SECURITY_CODE": "000001.SZ", "BOARD_CODE": "BK0002", "BOARD_NAME": "大数据"},
        ]
        result = fetch_stock_concepts(client, "000001.SZ")
        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["concept_name"], "人工智能")
        self.assertEqual(result.iloc[0]["source"], "eastmoney_concept")

    def test_fetch_stock_concepts_filters_bad_rows(self):
        client = Mock()
        client.datacenter.return_value = [
            {"SECURITY_CODE": "000001.SZ", "BOARD_CODE": None, "BOARD_NAME": None},
            {"SECURITY_CODE": "000001.SZ", "BOARD_CODE": "BK0001", "BOARD_NAME": "人工智能"},
        ]
        result = fetch_stock_concepts(client, "000001.SZ")
        self.assertEqual(len(result), 1)

    def test_fetch_concept_stocks_normalizes_ts_code(self):
        client = Mock()
        client.datacenter.return_value = [
            {"SECURITY_CODE": "600519", "BOARD_NAME": "白酒", "SECURITY_NAME_ABBR": "贵州茅台"},
        ]
        result = fetch_concept_stocks(client, "BK0001")
        self.assertEqual(result.iloc[0]["ts_code"], "600519.SH")


if __name__ == "__main__":
    unittest.main()
