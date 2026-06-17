import time
import unittest
from unittest.mock import Mock, patch

from core.providers.base import ProviderResult, normalize_symbol
from core.providers.eastmoney import EastMoneyClient
from core.providers.rate_limit import EastMoneyLimiter


class ProviderBaseTest(unittest.TestCase):
    def test_normalize_symbol_accepts_common_stock_code_formats(self):
        self.assertEqual(normalize_symbol("000001.SZ").symbol, "000001")
        self.assertEqual(normalize_symbol("SZ000001").exchange_suffix, "SZ")
        self.assertEqual(normalize_symbol("sh600000").exchange_suffix, "SH")
        self.assertEqual(normalize_symbol("BJ832000").eastmoney_market, "0")

    def test_provider_result_tracks_source_and_error(self):
        result = ProviderResult(source="eastmoney", ok=False, error="empty")

        self.assertFalse(result.ok)
        self.assertEqual(result.source, "eastmoney")
        self.assertEqual(result.error, "empty")


class EastMoneyProviderTest(unittest.TestCase):
    def test_limiter_sleeps_when_called_too_quickly(self):
        limiter = EastMoneyLimiter(min_interval_sec=1.0, jitter_range=(0.0, 0.0))
        limiter._last_call = 100.0

        with patch("core.providers.rate_limit.time.time", return_value=100.2), \
             patch("core.providers.rate_limit.time.sleep") as sleep:
            limiter.wait()

        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.8)

    def test_client_builds_kline_url_and_uses_limiter(self):
        session = Mock()
        response = Mock(status_code=200, text="{}")
        session.get.return_value = response
        limiter = Mock()
        client = EastMoneyClient(session=session, limiter=limiter)

        got = client.get_kline("000001", "20260615", "20260616", adjust="none")

        self.assertIs(got, response)
        limiter.wait.assert_called_once()
        args, kwargs = session.get.call_args
        self.assertIn("push2his.eastmoney.com", args[0])
        self.assertEqual(kwargs["params"]["secid"], "0.000001")
        self.assertEqual(kwargs["params"]["fqt"], "0")
        self.assertIn("User-Agent", kwargs["headers"])
        self.assertEqual(kwargs["timeout"], 20)


if __name__ == "__main__":
    unittest.main()
