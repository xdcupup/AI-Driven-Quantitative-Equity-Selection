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


if __name__ == "__main__":
    unittest.main()
