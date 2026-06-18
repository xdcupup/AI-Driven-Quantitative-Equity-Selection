import unittest
from unittest.mock import Mock, patch

from core.astock.eastmoney.client import EastMoneyDataClient


class EastMoneyDataClientTest(unittest.TestCase):
    def test_em_get_waits_and_reuses_session(self):
        session = Mock()
        response = Mock()
        session.get.return_value = response
        client = EastMoneyDataClient(
            session=session,
            min_interval_sec=1.0,
            jitter_range=(0.0, 0.0),
        )
        client._last_call = 100.0

        with patch(
            "core.astock.eastmoney.client.time.time",
            side_effect=[100.2, 100.2],
        ), patch("core.astock.eastmoney.client.time.sleep") as sleep:
            got = client.em_get("https://datacenter-web.eastmoney.com/api/data/v1/get")

        self.assertIs(got, response)
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.8)
        session.get.assert_called_once()

    def test_datacenter_builds_report_params(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {"result": {"data": [{"SECURITY_CODE": "600519"}]}}
        session.get.return_value = response
        client = EastMoneyDataClient(session=session, min_interval_sec=0.0)

        result = client.datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str='(SECURITY_CODE="600519")',
            page_size=20,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )

        self.assertEqual(result, [{"SECURITY_CODE": "600519"}])
        _, kwargs = session.get.call_args
        self.assertEqual(
            kwargs["params"]["reportName"], "RPT_DAILYBILLBOARD_DETAILSNEW"
        )
        self.assertEqual(kwargs["params"]["filter"], '(SECURITY_CODE="600519")')
        self.assertEqual(kwargs["params"]["pageSize"], "20")

    def test_datacenter_returns_empty_for_bad_json(self):
        session = Mock()
        response = Mock()
        response.json.side_effect = ValueError("not json")
        session.get.return_value = response
        client = EastMoneyDataClient(session=session, min_interval_sec=0.0)

        self.assertEqual(client.datacenter("RPT_DAILYBILLBOARD_DETAILSNEW"), [])

    def test_datacenter_filters_non_dict_rows(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            "result": {"data": [{"SECURITY_CODE": "600519"}, None, ["bad"]]}
        }
        session.get.return_value = response
        client = EastMoneyDataClient(session=session, min_interval_sec=0.0)

        self.assertEqual(
            client.datacenter("RPT_DAILYBILLBOARD_DETAILSNEW"),
            [{"SECURITY_CODE": "600519"}],
        )


if __name__ == "__main__":
    unittest.main()
