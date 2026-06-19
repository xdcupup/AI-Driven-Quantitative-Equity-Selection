import unittest
from unittest.mock import Mock, patch

from core.astock.ths.hot_theme import fetch_hot_themes, fetch_theme_stocks


class ThsHotThemeTest(unittest.TestCase):
    def test_fetch_hot_themes_returns_empty_for_bad_json(self):
        with patch("core.astock.ths.hot_theme.requests.get") as mock_get:
            mock_get.return_value.json.side_effect = ValueError("bad json")
            result = fetch_hot_themes()
            self.assertTrue(result.empty)

    def test_fetch_theme_stocks_returns_empty_for_empty_response(self):
        with patch("core.astock.ths.hot_theme.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"data": None}
            result = fetch_theme_stocks("12345")
            self.assertTrue(result.empty)

    def test_fetch_hot_themes_parses_ranked_list(self):
        mock_data = {
            "data": [
                {
                    "plate_id": "12345", "plate_name": "AI算力",
                    "rank": 1, "hot_num": 98.5, "pct_chg": 3.2,
                    "lead_stock_name": "科大讯飞", "stock_count": 45,
                },
            ]
        }
        with patch("core.astock.ths.hot_theme.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_data
            result = fetch_hot_themes("20260619")
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["theme_name"], "AI算力")
        self.assertEqual(result.iloc[0]["rank"], 1)
        self.assertEqual(result.iloc[0]["stock_count"], 45)

    def test_fetch_hot_themes_filters_nondict_items(self):
        mock_data = {"data": [{"plate_id": "1", "plate_name": "X"}, None, "bad"]}
        with patch("core.astock.ths.hot_theme.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_data
            result = fetch_hot_themes()
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
