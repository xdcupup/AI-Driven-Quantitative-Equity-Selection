# a-stock-data Market Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the project's default market-data source path with an `a-stock-data` style layer: `mootdx` for K-line, Tencent for quotes and valuation, Baidu for K-line MA fallback, and East Money only for unique non-market endpoints with strict rate limiting.

**Architecture:** Add a new `core/astock/` package instead of extending the legacy `core/data_fetcher.py` internals. Keep old modules present during this first migration slice so existing storage, cleaning, and quality tests still run, but change the new default configuration and gateway path to the new data-source layer.

**Tech Stack:** Python 3.11, pandas, requests, urllib, mootdx, unittest, DuckDB pipeline unchanged for this slice.

---

## File Structure

- Create `core/astock/__init__.py`: package marker and public exports.
- Create `core/astock/symbols.py`: canonical A-share ticker normalization and market prefix helpers.
- Create `core/astock/market/__init__.py`: market package marker.
- Create `core/astock/market/tencent_quote.py`: Tencent GBK quote parser and HTTP client.
- Create `core/astock/market/baidu_kline.py`: Baidu K-line with MA parser and HTTP client.
- Create `core/astock/market/mootdx_client.py`: `mootdx` adapter with injectable fake client support.
- Create `core/astock/eastmoney/__init__.py`: East Money package marker.
- Create `core/astock/eastmoney/client.py`: `em_get` and datacenter helper with serial limiter.
- Create `core/astock/gateway.py`: new pipeline-facing gateway for first-stage market data.
- Create `tests/test_astock_symbols.py`: ticker tests.
- Create `tests/test_astock_market.py`: Tencent, Baidu, and mootdx provider tests.
- Create `tests/test_astock_gateway.py`: routing tests proving no East Money market fallback.
- Create `tests/test_astock_eastmoney.py`: East Money limiter/datacenter tests.
- Modify `pipeline.py`: instantiate `AStockDataGateway` when config selects `astock`.
- Modify `config.yaml`: make `astock` the default source engine and remove `akshare` as the configured primary source.
- Modify `requirements.txt`: remove `akshare` and `tushare`; add `mootdx` and `stockstats`.
- Modify `README.md`: document the `a-stock-data` data-source priority and first-stage limitations.

---

### Task 1: Symbol Normalization Core

**Files:**
- Create: `core/astock/__init__.py`
- Create: `core/astock/symbols.py`
- Test: `tests/test_astock_symbols.py`

- [ ] **Step 1: Write failing symbol tests**

Create `tests/test_astock_symbols.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_symbols -v
```

Expected: fail with `ModuleNotFoundError: No module named 'core.astock'`.

- [ ] **Step 3: Implement symbol module**

Create `core/astock/__init__.py`:

```python
"""a-stock-data style direct data-source adapters."""
```

Create `core/astock/symbols.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class AStockSymbol:
    symbol: str
    exchange_suffix: str

    @property
    def ts_code(self) -> str:
        return f"{self.symbol}.{self.exchange_suffix}"

    @property
    def http_prefix(self) -> str:
        if self.exchange_suffix == "SH":
            return "sh"
        if self.exchange_suffix == "BJ":
            return "bj"
        return "sz"

    @property
    def tencent_code(self) -> str:
        return f"{self.http_prefix}{self.symbol}"

    @property
    def mootdx_market(self) -> int:
        return 1 if self.exchange_suffix == "SH" else 0

    @property
    def supports_mootdx_stage_one(self) -> bool:
        return self.exchange_suffix in {"SH", "SZ"}


def normalize_code(code: str) -> AStockSymbol:
    raw = str(code).strip().upper()
    if "." in raw:
        symbol, suffix = raw.split(".", 1)
    elif raw.startswith(("SH", "SZ", "BJ")):
        suffix = raw[:2]
        symbol = raw[2:]
    else:
        symbol = raw
        if symbol.startswith(("6", "9")):
            suffix = "SH"
        elif symbol.startswith(("8", "4")):
            suffix = "BJ"
        else:
            suffix = "SZ"

    return AStockSymbol(symbol=symbol.zfill(6), exchange_suffix=suffix)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_symbols -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/astock/__init__.py core/astock/symbols.py tests/test_astock_symbols.py
git commit -m "feat: add astock symbol normalization"
```

---

### Task 2: Tencent Quote Provider

**Files:**
- Create: `core/astock/market/__init__.py`
- Create: `core/astock/market/tencent_quote.py`
- Test: `tests/test_astock_market.py`

- [ ] **Step 1: Write failing Tencent tests**

Create `tests/test_astock_market.py` with the Tencent section:

```python
import unittest
from unittest.mock import Mock

import pandas as pd

from core.astock.market.tencent_quote import TencentQuoteClient


class TencentQuoteClientTest(unittest.TestCase):
    def test_parse_gbk_quote_uses_correct_pb_index(self):
        raw = (
            'v_sh600519="1~贵州茅台~600519~1688.00~1670.00~1678.00~'
            '0~0~0~1687.00~1~1686.00~2~1685.00~3~1689.00~1~1690.00~2~'
            '1691.00~3~0~0~0~0~0~0~0~0~0~0~18.00~1.08~1699.00~1660.00~'
            '0~0~123456.78~2.50~25.60~0~0~0~3.10~21000.00~20000.00~'
            '8.70~1837.80~1502.20~1.20~22.30";'
        ).encode("gbk")
        opener = Mock(return_value=raw)
        client = TencentQuoteClient(opener=opener)

        result = client.fetch_quotes(["600519"])

        row = result.iloc[0]
        self.assertEqual(row["ts_code"], "600519.SH")
        self.assertEqual(row["name"], "贵州茅台")
        self.assertEqual(row["price"], 1688.00)
        self.assertEqual(row["pe_ttm"], 25.60)
        self.assertEqual(row["pb"], 8.70)
        self.assertEqual(row["amount"], 1234567800.0)
        self.assertEqual(row["total_mv"], 2100000000000.0)
        self.assertEqual(row["circ_mv"], 2000000000000.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_market.TencentQuoteClientTest -v
```

Expected: fail with `ModuleNotFoundError` or missing `TencentQuoteClient`.

- [ ] **Step 3: Implement Tencent provider**

Create `core/astock/market/__init__.py`:

```python
"""Market data adapters that do not depend on AKShare."""
```

Create `core/astock/market/tencent_quote.py`:

```python
from collections.abc import Callable
import urllib.request

import pandas as pd

from core.astock.symbols import normalize_code


UA = "Mozilla/5.0"


def _to_float(value: str) -> float:
    try:
        return float(value) if value not in ("", "-") else 0.0
    except (TypeError, ValueError):
        return 0.0


class TencentQuoteClient:
    """Tencent quote API client for realtime quote and valuation fields."""

    def __init__(self, opener: Callable[[str], bytes] | None = None):
        self.opener = opener or self._open_url

    @staticmethod
    def _open_url(url: str) -> bytes:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()

    def fetch_quotes(self, codes: list[str]) -> pd.DataFrame:
        symbols = [normalize_code(code) for code in codes]
        url = "https://qt.gtimg.cn/q=" + ",".join(s.tencent_code for s in symbols)
        text = self.opener(url).decode("gbk")
        rows = []
        for line in text.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            values = line.split('"')[1].split("~")
            if len(values) < 53:
                continue
            symbol = normalize_code(key[2:])
            rows.append({
                "ts_code": symbol.ts_code,
                "symbol": symbol.symbol,
                "name": values[1],
                "price": _to_float(values[3]),
                "last_close": _to_float(values[4]),
                "open": _to_float(values[5]),
                "change_amt": _to_float(values[31]),
                "change_pct": _to_float(values[32]),
                "high": _to_float(values[33]),
                "low": _to_float(values[34]),
                "amount": _to_float(values[37]) * 10000,
                "turnover_rate": _to_float(values[38]),
                "pe_ttm": _to_float(values[39]),
                "amplitude_pct": _to_float(values[43]),
                "total_mv": _to_float(values[44]) * 100000000,
                "circ_mv": _to_float(values[45]) * 100000000,
                "pb": _to_float(values[46]),
                "limit_up": _to_float(values[47]),
                "limit_down": _to_float(values[48]),
                "volume_ratio": _to_float(values[49]),
                "pe_static": _to_float(values[52]),
                "source": "tencent",
            })
        return pd.DataFrame(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_market.TencentQuoteClientTest -v
```

Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add core/astock/market/__init__.py core/astock/market/tencent_quote.py tests/test_astock_market.py
git commit -m "feat: add astock tencent quote client"
```

---

### Task 3: Baidu K-line Provider

**Files:**
- Modify: `core/astock/market/baidu_kline.py`
- Modify: `tests/test_astock_market.py`

- [ ] **Step 1: Add failing Baidu tests**

Append to `tests/test_astock_market.py`:

```python
from core.astock.market.baidu_kline import BaiduKlineClient


class BaiduKlineClientTest(unittest.TestCase):
    def test_parse_kline_accepts_string_result_code_and_ma_fields(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            "ResultCode": "0",
            "Result": {
                "newMarketData": {
                    "keys": [
                        "time", "open", "close", "high", "low",
                        "volume", "amount", "ma5avgprice",
                        "ma10avgprice", "ma20avgprice",
                    ],
                    "marketData": (
                        "20260615,11.20,11.10,11.30,11.00,1000,111000,10.9,10.8,10.7;"
                        "20260616,11.10,10.94,11.12,10.91,1200,131280,11.0,10.9,10.8"
                    ),
                }
            },
        }
        session.get.return_value = response
        client = BaiduKlineClient(session=session)

        result = client.fetch_kline_with_ma("000001", start_time="")

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(result.iloc[1]["close"], 10.94)
        self.assertEqual(result.iloc[1]["ma20"], 10.8)
        self.assertEqual(result.iloc[1]["source"], "baidu")

    def test_parse_kline_accepts_integer_result_code(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            "ResultCode": 0,
            "Result": {
                "newMarketData": {
                    "keys": ["time", "open", "close", "high", "low", "volume", "amount"],
                    "marketData": "20260616,11.10,10.94,11.12,10.91,1200,131280",
                }
            },
        }
        session.get.return_value = response
        client = BaiduKlineClient(session=session)

        result = client.fetch_kline_with_ma("000001")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["amount"], 131280.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_market.BaiduKlineClientTest -v
```

Expected: fail with missing `core.astock.market.baidu_kline`.

- [ ] **Step 3: Implement Baidu provider**

Create `core/astock/market/baidu_kline.py`:

```python
import pandas as pd
import requests

from core.astock.symbols import normalize_code


URL = "https://finance.pae.baidu.com/selfselect/getstockquotation"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/vnd.finance-web.v1+json",
    "Origin": "https://gushitong.baidu.com",
    "Referer": "https://gushitong.baidu.com/",
}


class BaiduKlineClient:
    """Baidu Gushitong K-line client with MA fields."""

    def __init__(self, session=None):
        self.session = session or requests.Session()

    def fetch_kline_with_ma(self, code: str, start_time: str = "") -> pd.DataFrame:
        symbol = normalize_code(code)
        response = self.session.get(
            URL,
            params={
                "all": "1",
                "isIndex": "false",
                "isBk": "false",
                "isBlock": "false",
                "isFutures": "false",
                "isStock": "true",
                "newFormat": "1",
                "group": "quotation_kline_ab",
                "finClientType": "pc",
                "code": symbol.symbol,
                "start_time": start_time,
                "ktype": "1",
            },
            headers=HEADERS,
            timeout=10,
        )
        payload = response.json()
        if str(payload.get("ResultCode", -1)) != "0":
            return pd.DataFrame()
        market_data = (
            payload.get("Result", {})
            .get("newMarketData", {})
        )
        keys = market_data.get("keys", [])
        rows_raw = [row for row in market_data.get("marketData", "").split(";") if row]
        rows = []
        for raw in rows_raw:
            values = raw.split(",")
            item = dict(zip(keys, values))
            rows.append({
                "ts_code": symbol.ts_code,
                "trade_date": item.get("time", ""),
                "open": item.get("open"),
                "close": item.get("close"),
                "high": item.get("high"),
                "low": item.get("low"),
                "vol": item.get("volume"),
                "amount": item.get("amount"),
                "ma5": item.get("ma5avgprice"),
                "ma10": item.get("ma10avgprice"),
                "ma20": item.get("ma20avgprice"),
                "source": "baidu",
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        for col in ["open", "close", "high", "low", "vol", "amount", "ma5", "ma10", "ma20"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.sort_values("trade_date").reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_market.BaiduKlineClientTest -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/astock/market/baidu_kline.py tests/test_astock_market.py
git commit -m "feat: add astock baidu kline client"
```

---

### Task 4: Mootdx Market Provider

**Files:**
- Create: `core/astock/market/mootdx_client.py`
- Modify: `tests/test_astock_market.py`

- [ ] **Step 1: Add failing mootdx tests**

Append to `tests/test_astock_market.py`:

```python
from core.astock.market.mootdx_client import MootdxMarketClient


class MootdxMarketClientTest(unittest.TestCase):
    def test_daily_kline_normalizes_fake_client_rows(self):
        class FakeQuotes:
            def bars(self, symbol, market, category, offset):
                self.call = (symbol, market, category, offset)
                return pd.DataFrame({
                    "datetime": ["2026-06-15", "2026-06-16"],
                    "open": [11.2, 11.1],
                    "close": [11.1, 10.94],
                    "high": [11.3, 11.12],
                    "low": [11.0, 10.91],
                    "vol": [1000.0, 1200.0],
                    "amount": [111000.0, 131280.0],
                })

        fake = FakeQuotes()
        client = MootdxMarketClient(quotes=fake)

        result = client.fetch_daily_kline("000001.SZ", "20260615", "20260616")

        self.assertEqual(fake.call, ("000001", 0, 4, 1200))
        self.assertEqual(result.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(result.iloc[1]["close"], 10.94)
        self.assertEqual(result.iloc[1]["source"], "mootdx")

    def test_daily_kline_skips_bse_in_stage_one(self):
        client = MootdxMarketClient(quotes=Mock())

        result = client.fetch_daily_kline("832000.BJ", "20260615", "20260616")

        self.assertTrue(result.empty)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_market.MootdxMarketClientTest -v
```

Expected: fail with missing `core.astock.market.mootdx_client`.

- [ ] **Step 3: Implement mootdx provider**

Create `core/astock/market/mootdx_client.py`:

```python
import pandas as pd

from core.astock.symbols import normalize_code


class MootdxMarketClient:
    """mootdx market adapter with injectable quote client for tests."""

    def __init__(self, quotes=None):
        self.quotes = quotes

    def _get_quotes(self):
        if self.quotes is None:
            from mootdx.quotes import Quotes

            self.quotes = Quotes.factory(market="std")
        return self.quotes

    def fetch_daily_kline(
        self, code: str, start: str, end: str, offset: int = 1200
    ) -> pd.DataFrame:
        symbol = normalize_code(code)
        if not symbol.supports_mootdx_stage_one:
            return pd.DataFrame()

        df = self._get_quotes().bars(
            symbol=symbol.symbol,
            market=symbol.mootdx_market,
            category=4,
            offset=offset,
        )
        if df is None or df.empty:
            return pd.DataFrame()

        result = df.rename(columns={"datetime": "trade_date"}).copy()
        result["trade_date"] = pd.to_datetime(result["trade_date"])
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        result = result[
            (result["trade_date"] >= start_ts) & (result["trade_date"] <= end_ts)
        ].copy()
        if result.empty:
            return result

        result["ts_code"] = symbol.ts_code
        result["source"] = "mootdx"
        for col in ["open", "high", "low", "close", "vol", "amount"]:
            if col in result.columns:
                result[col] = pd.to_numeric(result[col], errors="coerce")
        return result[
            ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "source"]
        ].sort_values("trade_date").reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_market.MootdxMarketClientTest -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/astock/market/mootdx_client.py tests/test_astock_market.py
git commit -m "feat: add astock mootdx market client"
```

---

### Task 5: East Money Unique-Data Client

**Files:**
- Create: `core/astock/eastmoney/__init__.py`
- Create: `core/astock/eastmoney/client.py`
- Test: `tests/test_astock_eastmoney.py`

- [ ] **Step 1: Write failing East Money tests**

Create `tests/test_astock_eastmoney.py`:

```python
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

        with patch("core.astock.eastmoney.client.time.time", side_effect=[100.2, 100.2]), \
             patch("core.astock.eastmoney.client.time.sleep") as sleep:
            got = client.em_get("https://datacenter-web.eastmoney.com/api/data/v1/get")

        self.assertIs(got, response)
        sleep.assert_called_once_with(0.8)
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
        self.assertEqual(kwargs["params"]["reportName"], "RPT_DAILYBILLBOARD_DETAILSNEW")
        self.assertEqual(kwargs["params"]["filter"], '(SECURITY_CODE="600519")')
        self.assertEqual(kwargs["params"]["pageSize"], "20")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_eastmoney -v
```

Expected: fail with missing `core.astock.eastmoney`.

- [ ] **Step 3: Implement East Money client**

Create `core/astock/eastmoney/__init__.py`:

```python
"""East Money adapters for unique data only."""
```

Create `core/astock/eastmoney/client.py`:

```python
import random
import threading
import time

import requests


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


class EastMoneyDataClient:
    """Rate-limited East Money client for unique non-market endpoints."""

    def __init__(
        self,
        session=None,
        min_interval_sec: float = 1.0,
        jitter_range: tuple[float, float] = (0.1, 0.5),
    ):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self.min_interval_sec = float(min_interval_sec)
        self.jitter_range = jitter_range
        self._last_call = 0.0
        self._lock = threading.Lock()

    def em_get(self, url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 15, **kwargs):
        with self._lock:
            wait_for = self.min_interval_sec - (time.time() - self._last_call)
            if wait_for > 0:
                time.sleep(wait_for + random.uniform(*self.jitter_range))
            try:
                return self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                    **kwargs,
                )
            finally:
                self._last_call = time.time()

    def datacenter(
        self,
        report_name: str,
        columns: str = "ALL",
        filter_str: str = "",
        page_size: int = 50,
        sort_columns: str = "",
        sort_types: str = "-1",
    ) -> list[dict]:
        params = {
            "reportName": report_name,
            "columns": columns,
            "filter": filter_str,
            "pageNumber": "1",
            "pageSize": str(page_size),
            "sortColumns": sort_columns,
            "sortTypes": sort_types,
            "source": "WEB",
            "client": "WEB",
        }
        response = self.em_get(DATACENTER_URL, params=params, timeout=15)
        payload = response.json()
        if payload.get("result") and payload["result"].get("data"):
            return payload["result"]["data"]
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_eastmoney -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/astock/eastmoney/__init__.py core/astock/eastmoney/client.py tests/test_astock_eastmoney.py
git commit -m "feat: add astock eastmoney unique-data client"
```

---

### Task 6: Gateway Routing and Project Defaults

**Files:**
- Create: `core/astock/gateway.py`
- Test: `tests/test_astock_gateway.py`
- Modify: `pipeline.py`
- Modify: `tests/test_pipeline.py`
- Modify: `config.yaml`
- Modify: `requirements.txt`
- Modify: `README.md`

- [ ] **Step 1: Write failing gateway tests**

Create `tests/test_astock_gateway.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_gateway -v
```

Expected: fail with missing `core.astock.gateway`.

- [ ] **Step 3: Implement gateway**

Create `core/astock/gateway.py`:

```python
import pandas as pd

from core.astock.eastmoney.client import EastMoneyDataClient
from core.astock.market.baidu_kline import BaiduKlineClient
from core.astock.market.mootdx_client import MootdxMarketClient
from core.astock.market.tencent_quote import TencentQuoteClient


def _parse_date(value: str) -> str:
    return str(value).replace("-", "")


class AStockDataGateway:
    """Pipeline-facing gateway for the new a-stock-data source layer."""

    def __init__(
        self,
        config: dict | None = None,
        mootdx_client=None,
        tencent_client=None,
        baidu_client=None,
        eastmoney_client=None,
    ):
        self.config = config or {}
        self.mootdx = mootdx_client or MootdxMarketClient()
        self.tencent = tencent_client or TencentQuoteClient()
        self.baidu = baidu_client or BaiduKlineClient()
        self.eastmoney = eastmoney_client or EastMoneyDataClient()

    def fetch_daily_kline(self, ts_code: str, start_date: str, end_date: str, adjust: str = "none") -> pd.DataFrame:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        df = self.mootdx.fetch_daily_kline(ts_code, start, end)
        if not df.empty:
            return self._normalize_daily_kline(df)

        fallback = self.baidu.fetch_kline_with_ma(ts_code, start_time=start)
        if not fallback.empty:
            fallback = fallback[
                (fallback["trade_date"] >= pd.Timestamp(start))
                & (fallback["trade_date"] <= pd.Timestamp(end))
            ].copy()
            return self._normalize_daily_kline(fallback)
        return pd.DataFrame()

    def fetch_daily_basic(self, codes, trade_date: str) -> pd.DataFrame:
        if isinstance(codes, str):
            codes = [codes]
        df = self.tencent.fetch_quotes(list(codes))
        if df.empty:
            return df
        result = df[[
            "ts_code", "pe_ttm", "pb", "turnover_rate",
            "volume_ratio", "circ_mv", "total_mv",
        ]].copy()
        result["trade_date"] = pd.Timestamp(_parse_date(trade_date))
        result["pe"] = result["pe_ttm"]
        return result[[
            "ts_code", "trade_date", "pe", "pe_ttm", "pb",
            "turnover_rate", "volume_ratio", "circ_mv", "total_mv",
        ]]

    def _normalize_daily_kline(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        result["trade_date"] = pd.to_datetime(result["trade_date"])
        if "pct_chg" not in result.columns:
            result["pct_chg"] = result.groupby("ts_code")["close"].pct_change() * 100
        result["adj_factor"] = float("nan")
        result["price_type"] = "none"
        result["flag_extreme"] = False
        result["flag_suspended"] = False
        result["flag_aligned"] = False
        result["flag_invalid_ohlc"] = False
        for col in ["open", "high", "low", "close"]:
            result[f"raw_{col}"] = result[col]
        return result.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
```

- [ ] **Step 4: Run gateway tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_astock_gateway -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Add pipeline source selection helper**

Add this helper near the top of `pipeline.py`, after `init_logging` and before `class Pipeline`:

```python
def select_fetcher_class(config: dict):
    source_engine = config.get("data_source", {}).get("engine", "legacy")
    if source_engine == "astock":
        from core.astock.gateway import AStockDataGateway

        return AStockDataGateway
    from core.data_fetcher import DataFetcher

    return DataFetcher
```

- [ ] **Step 6: Modify pipeline initialization**

In `pipeline.py`, keep this legacy import because `build_stock_code_set` is still used:

```python
        from core.data_fetcher import DataFetcher, build_stock_code_set
```

Then replace the current fetcher initialization:

```python
        self.fetcher = DataFetcher(config)
```

with:

```python
        FetcherClass = select_fetcher_class(config)
        self.fetcher = FetcherClass(config)
```

- [ ] **Step 7: Add pipeline selection test**

Append to `tests/test_pipeline.py`:

```python
class PipelineSourceSelectionTest(unittest.TestCase):
    def test_select_fetcher_class_returns_astock_gateway_when_configured(self):
        from pipeline import select_fetcher_class
        from core.astock.gateway import AStockDataGateway

        self.assertIs(
            select_fetcher_class({"data_source": {"engine": "astock"}}),
            AStockDataGateway,
        )
```

- [ ] **Step 8: Update config, requirements, and README**

In `config.yaml`, replace:

```yaml
data_source:
  primary: akshare
  tushare_token: ""
```

with:

```yaml
data_source:
  engine: astock
  market_primary: mootdx
  market_fallback: baidu
  quote_source: tencent
```

In `requirements.txt`, remove:

```text
akshare>=1.14.0
tushare>=1.4.0
```

and add:

```text
mootdx>=0.11.0
stockstats>=0.6.0
```

In `README.md`, replace the old data-source summary with:

```markdown
> 当前阶段：数据源内核按 a-stock-data 架构重写。行情层默认使用 mootdx + 腾讯 + 百度股市通；AKShare/Tushare 不再作为新架构依赖；东财只用于独有数据并统一限流。
```

Add a "数据源优先级" section:

```markdown
## 数据源优先级

- 行情 K 线：mootdx 为主源，百度股市通为补充源。
- 实时行情和估值：腾讯财经。
- 东财：只用于研报、龙虎榜、解禁、两融、大宗交易、股东户数、分红、资金流、行业板块、新闻和个股基本信息。
- 基础财务文本：mootdx finance/F10、 新浪财报三表。
- 公告：巨潮公告和 mootdx F10 摘要。
```

- [ ] **Step 9: Run focused tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_astock_symbols \
  tests.test_astock_market \
  tests.test_astock_eastmoney \
  tests.test_astock_gateway \
  -v
```

Expected: all new astock tests pass.

- [ ] **Step 10: Run full verification**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall pipeline.py core tests
```

Expected: all tests pass and compileall exits 0.

- [ ] **Step 11: Commit**

```bash
git add core/astock tests/test_astock_*.py pipeline.py tests/test_pipeline.py config.yaml requirements.txt README.md
git commit -m "feat: add astock market data gateway"
```

---

## Self-Review Checklist

- The plan implements the approved first-stage scope from `docs/superpowers/specs/2026-06-18-astock-data-source-rewrite-design.md`.
- The market path uses `mootdx`, Tencent, and Baidu; it does not call East Money for K-line fallback.
- East Money exists only as a rate-limited unique-data helper.
- The plan removes `akshare` and `tushare` from project requirements.
- The plan preserves legacy tests during this slice, while new defaults move to `AStockDataGateway`.
- Every task includes red test, failure verification, implementation, pass verification, and commit.
