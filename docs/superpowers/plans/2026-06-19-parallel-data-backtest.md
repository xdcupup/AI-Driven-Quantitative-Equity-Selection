# 双线并行：评分器数据源 + 回测框架 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track A 接入东财概念板块 + 同花顺热点数据源，补全评分器输入维度；Track B 构建完整版回测框架（分层+仿真+绩效+中性化+参数扫描+衰减+归因）。

**Architecture:** 两条线独立并行，共同接口是 DuckDB 中的因子和标签表。Track A 在 `core/astock/` 下扩展数据采集，通过 `AStockDataGateway` 注册。Track B 新建 `core/backtest/` 独立模块，读取现有 `technical_factors` + `factor_labels` + `daily_kline` + `daily_basic`，不发明新数据通道。

**Tech Stack:** Python 3.12, pandas, DuckDB, mootdx, requests, unittest

---

## Track A: 评分器数据源

### Task A1: 东财概念板块数据采集

**Files:**
- Create: `core/astock/eastmoney/concept.py`
- Create: `tests/test_astock_concept.py`

- [ ] **Step 1: 写空响应测试**

```python
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
```

Run: `pytest tests/test_astock_concept.py::EastMoneyConceptTest::test_fetch_stock_concepts_returns_empty_for_empty_response -v`
Expected: FAIL with "No module named 'core.astock.eastmoney.concept'"

- [ ] **Step 2: 实现最少代码让测试通过**

```python
"""East Money concept board and stock-concept mapping."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.astock.eastmoney.client import EastMoneyDataClient
from core.astock.symbols import normalize_code

CONCEPT_COLUMNS = ["ts_code", "concept_code", "concept_name", "source"]
CONCEPT_STOCK_COLUMNS = ["concept_code", "concept_name", "ts_code", "ts_name", "source"]


def fetch_stock_concepts(
    client: EastMoneyDataClient,
    ts_code: str,
) -> pd.DataFrame:
    """Fetch all concept boards a stock belongs to.

    Returns DataFrame with columns: ts_code, concept_code, concept_name, source
    """
    return pd.DataFrame(columns=CONCEPT_COLUMNS)


def fetch_concept_stocks(
    client: EastMoneyDataClient,
    concept_code: str,
) -> pd.DataFrame:
    """Fetch all stocks in a concept board.

    Returns DataFrame with columns: concept_code, concept_name, ts_code, ts_name, source
    """
    return pd.DataFrame(columns=CONCEPT_STOCK_COLUMNS)
```

Run: `pytest tests/test_astock_concept.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: 提交**

```bash
git add core/astock/eastmoney/concept.py tests/test_astock_concept.py
git commit -m "feat: add eastmoney concept board stubs"
```

- [ ] **Step 4: 写真实解析测试**

```python
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
```

Run: `pytest tests/test_astock_concept.py::EastMoneyConceptTest::test_fetch_stock_concepts_parses_datacenter_response -v`
Expected: FAIL — 空 DataFrame 不含数据

- [ ] **Step 5: 实现东财概念板块采集**

东财 datacenter report name: `RPT_PC_BOARDCP`（概念板块成分股），按 `SECURITY_CODE` 过滤。

```python
def fetch_stock_concepts(
    client: EastMoneyDataClient,
    ts_code: str,
) -> pd.DataFrame:
    symbol = normalize_code(ts_code)
    rows = client.datacenter(
        report_name="RPT_PC_BOARDCP",
        filter_str=f'(SECURITY_CODE="{symbol.symbol}")',
        page_size=100,
        sort_columns="BOARD_CODE",
        sort_types="1",
    )
    if not rows:
        return pd.DataFrame(columns=CONCEPT_COLUMNS)
    data = [
        {
            "ts_code": symbol.ts_code,
            "concept_code": str(r.get("BOARD_CODE", "")),
            "concept_name": str(r.get("BOARD_NAME", "")),
            "source": "eastmoney_concept",
        }
        for r in rows
        if r.get("BOARD_CODE") and r.get("BOARD_NAME")
    ]
    return pd.DataFrame(data)[CONCEPT_COLUMNS].drop_duplicates(
        subset=["ts_code", "concept_code"]
    ).reset_index(drop=True)


def fetch_concept_stocks(
    client: EastMoneyDataClient,
    concept_code: str,
) -> pd.DataFrame:
    rows = client.datacenter(
        report_name="RPT_PC_BOARDCP",
        filter_str=f'(BOARD_CODE="{concept_code}")',
        page_size=500,
        sort_columns="SECURITY_CODE",
        sort_types="1",
    )
    if not rows:
        return pd.DataFrame(columns=CONCEPT_STOCK_COLUMNS)
    data = [
        {
            "concept_code": concept_code,
            "concept_name": str(r.get("BOARD_NAME", "")),
            "ts_code": normalize_code(str(r.get("SECURITY_CODE", ""))).ts_code,
            "ts_name": str(r.get("SECURITY_NAME_ABBR", "")),
            "source": "eastmoney_concept",
        }
        for r in rows
        if r.get("SECURITY_CODE")
    ]
    return pd.DataFrame(data)[CONCEPT_STOCK_COLUMNS].reset_index(drop=True)
```

Run: `pytest tests/test_astock_concept.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: 加边界测试**

```python
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
```

Run: `pytest tests/test_astock_concept.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: 提交**

```bash
git add core/astock/eastmoney/concept.py tests/test_astock_concept.py
git commit -m "feat: implement eastmoney concept board data source"
```

---

### Task A2: 同花顺热点数据采集

**Files:**
- Create: `core/astock/ths/__init__.py`
- Create: `core/astock/ths/hot_theme.py`
- Create: `tests/test_astock_ths.py`

- [ ] **Step 1: 写空响应测试**

```python
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
```

Run: `pytest tests/test_astock_ths.py::ThsHotThemeTest::test_fetch_hot_themes_returns_empty_for_bad_json -v`
Expected: FAIL

- [ ] **Step 2: 实现同花顺热点采集**

同花顺热点接口：`https://d.10jqka.com.cn/v2/plate/hot_rank/list`（热点排名列表）和 `https://d.10jqka.com.cn/v2/plate/hot_rank/detail`（热点板块个股）。

```python
"""THS (同花顺) hot theme / concept board data source."""

from __future__ import annotations

from typing import Any
from datetime import datetime

import pandas as pd
import requests

from core.astock.symbols import normalize_code

THS_HOT_LIST_URL = "https://d.10jqka.com.cn/v2/plate/hot_rank/list"
THS_HOT_DETAIL_URL = "https://d.10jqka.com.cn/v2/plate/hot_rank/detail"

THEME_COLUMNS = [
    "theme_code", "theme_name", "rank", "heat_score",
    "pct_chg", "leading_stock", "stock_count", "trade_date", "source",
]
THEME_STOCK_COLUMNS = [
    "theme_code", "theme_name", "ts_code", "ts_name",
    "pct_chg", "reason", "trade_date", "source",
]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://www.10jqka.com.cn/",
}


def fetch_hot_themes(trade_date: str | None = None) -> pd.DataFrame:
    """Fetch ranked hot theme list from THS."""
    trade_date = trade_date or datetime.now().strftime("%Y%m%d")
    try:
        resp = requests.get(
            THS_HOT_LIST_URL,
            headers=DEFAULT_HEADERS,
            params={"date": trade_date},
            timeout=10,
        )
        payload = resp.json()
    except (ValueError, requests.RequestException):
        return pd.DataFrame(columns=THEME_COLUMNS)

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return pd.DataFrame(columns=THEME_COLUMNS)

    rows = [
        {
            "theme_code": str(r.get("plate_id", "")),
            "theme_name": str(r.get("plate_name", "")),
            "rank": int(r.get("rank", 0)),
            "heat_score": float(r.get("hot_num", 0)),
            "pct_chg": float(r.get("pct_chg", 0)),
            "leading_stock": str(r.get("lead_stock_name", "")),
            "stock_count": int(r.get("stock_count", 0)),
            "trade_date": pd.Timestamp(trade_date),
            "source": "ths_hot_theme",
        }
        for r in data
        if isinstance(r, dict) and r.get("plate_id")
    ]
    return pd.DataFrame(rows)[THEME_COLUMNS].reset_index(drop=True)


def fetch_theme_stocks(
    theme_code: str,
    trade_date: str | None = None,
) -> pd.DataFrame:
    """Fetch constituent stocks for a THS hot theme."""
    trade_date = trade_date or datetime.now().strftime("%Y%m%d")
    try:
        resp = requests.get(
            THS_HOT_DETAIL_URL,
            headers=DEFAULT_HEADERS,
            params={"plate_id": theme_code, "date": trade_date},
            timeout=10,
        )
        payload = resp.json()
    except (ValueError, requests.RequestException):
        return pd.DataFrame(columns=THEME_STOCK_COLUMNS)

    result = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return pd.DataFrame(columns=THEME_STOCK_COLUMNS)

    stocks = result.get("stocks") if isinstance(result, dict) else result.get("data")
    if not isinstance(stocks, list):
        return pd.DataFrame(columns=THEME_STOCK_COLUMNS)

    theme_name = str(result.get("plate_name", ""))
    rows = [
        {
            "theme_code": theme_code,
            "theme_name": theme_name,
            "ts_code": normalize_code(str(s.get("code", ""))).ts_code,
            "ts_name": str(s.get("name", "")),
            "pct_chg": float(s.get("pct_chg", 0)),
            "reason": str(s.get("reason", "")),
            "trade_date": pd.Timestamp(trade_date),
            "source": "ths_hot_theme",
        }
        for s in stocks
        if isinstance(s, dict) and s.get("code")
    ]
    return pd.DataFrame(rows)[THEME_STOCK_COLUMNS].reset_index(drop=True)
```

```python
# core/astock/ths/__init__.py
```

Run: `pytest tests/test_astock_ths.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: 加解析测试和提交**

```python
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
```

Run: `pytest tests/test_astock_ths.py -v`
Expected: PASS (4 tests)

```bash
git add core/astock/ths/ tests/test_astock_ths.py
git commit -m "feat: add THS hot theme data source"
```

---

### Task A3: 存储 Schema + Gateway 注册

**Files:**
- Modify: `core/data_storage.py` (add schema + upsert methods)
- Modify: `core/astock/gateway.py` (register new methods)

- [ ] **Step 1: 在 SCHEMA_SQL 中添加概念板块表**

在 `data_storage.py` 的 `SCHEMA_SQL` 末尾，`trade_calendar` 表之前添加：

```sql
-- ====================================================================
-- 东财概念板块归属
-- ====================================================================
CREATE TABLE IF NOT EXISTS stock_concept_blocks (
    ts_code       VARCHAR NOT NULL,
    concept_code  VARCHAR NOT NULL,
    concept_name  VARCHAR NOT NULL,
    source        VARCHAR,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, concept_code)
);

CREATE INDEX IF NOT EXISTS idx_concept_code
ON stock_concept_blocks (concept_code);

-- ====================================================================
-- 同花顺每日热点主题
-- ====================================================================
CREATE TABLE IF NOT EXISTS hot_theme_daily (
    theme_code    VARCHAR NOT NULL,
    trade_date    DATE NOT NULL,
    theme_name    VARCHAR NOT NULL,
    rank          INTEGER,
    heat_score    DOUBLE,
    pct_chg       DOUBLE,
    leading_stock VARCHAR,
    stock_count   INTEGER,
    source        VARCHAR,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (theme_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_hot_theme_date
ON hot_theme_daily (trade_date);

-- ====================================================================
-- 同花顺热点个股明细
-- ====================================================================
CREATE TABLE IF NOT EXISTS hot_theme_stocks (
    theme_code    VARCHAR NOT NULL,
    trade_date    DATE NOT NULL,
    ts_code       VARCHAR NOT NULL,
    theme_name    VARCHAR,
    ts_name       VARCHAR,
    pct_chg       DOUBLE,
    reason        VARCHAR,
    source        VARCHAR,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (theme_code, trade_date, ts_code)
);

CREATE INDEX IF NOT EXISTS idx_theme_stocks_date
ON hot_theme_stocks (trade_date);
```

- [ ] **Step 2: 添加 upsert 方法**

在 `QuantDB` 类末尾添加：

```python
    def upsert_stock_concepts(self, df: pd.DataFrame):
        """Upsert stock->concept mapping."""
        if df.empty:
            return
        self.conn.register("_tmp_concepts", df)
        self.conn.execute("""
            INSERT OR REPLACE INTO stock_concept_blocks
            SELECT * FROM _tmp_concepts
        """)
        self.conn.unregister("_tmp_concepts")

    def upsert_hot_themes(self, df: pd.DataFrame):
        """Upsert daily hot theme rankings."""
        if df.empty:
            return
        self.conn.register("_tmp_hot_themes", df)
        self.conn.execute("""
            INSERT OR REPLACE INTO hot_theme_daily
            SELECT * FROM _tmp_hot_themes
        """)
        self.conn.unregister("_tmp_hot_themes")

    def upsert_hot_theme_stocks(self, df: pd.DataFrame):
        """Upsert hot theme constituent stocks."""
        if df.empty:
            return
        self.conn.register("_tmp_theme_stocks", df)
        self.conn.execute("""
            INSERT OR REPLACE INTO hot_theme_stocks
            SELECT * FROM _tmp_theme_stocks
        """)
        self.conn.unregister("_tmp_theme_stocks")
```

- [ ] **Step 3: Gateway 注册**

在 `gateway.py` 的 `AStockDataGateway.__init__` 中添加默认 client，并在类末尾添加方法：

```python
from core.astock.eastmoney.concept import fetch_stock_concepts, fetch_concept_stocks
from core.astock.ths.hot_theme import fetch_hot_themes, fetch_theme_stocks


class AStockDataGateway:
    # ... existing __init__ ...

    def fetch_stock_concepts(self, ts_code: str) -> pd.DataFrame:
        """Fetch concept boards for a stock from East Money."""
        return fetch_stock_concepts(self.eastmoney, ts_code)

    def fetch_concept_stocks(self, concept_code: str) -> pd.DataFrame:
        """Fetch stocks in a concept board from East Money."""
        return fetch_concept_stocks(self.eastmoney, concept_code)

    def fetch_hot_themes(self, trade_date: str | None = None) -> pd.DataFrame:
        """Fetch daily THS hot theme rankings."""
        return fetch_hot_themes(trade_date)

    def fetch_theme_stocks(
        self,
        theme_code: str,
        trade_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch constituent stocks for a THS hot theme."""
        return fetch_theme_stocks(theme_code, trade_date)
```

- [ ] **Step 4: Pipeline 中添加东财概念采集步骤**

在 `pipeline.py` 的 `DataPipeline` 类中添加：

```python
    def _step_stock_concepts(self, stock_codes: list, target_date: str):
        """Collect concept board affiliations from East Money."""
        cfg = self.config.get("fetch", {}).get("stock_concepts", {})
        if not cfg.get("enabled", False):
            return
        logger.info("采集东财概念板块归属...")
        sample = stock_codes[:int(cfg.get("max_stocks", 100))]
        all_rows = []
        for code in sample:
            df = self.fetcher.fetch_stock_concepts(code)
            if not df.empty:
                all_rows.append(df)
        if all_rows:
            self.db.upsert_stock_concepts(pd.concat(all_rows, ignore_index=True))

    def _step_hot_themes(self, target_date: str):
        """Collect daily hot themes from THS."""
        cfg = self.config.get("fetch", {}).get("hot_themes", {})
        if not cfg.get("enabled", False):
            return
        logger.info("采集同花顺热点...")
        df = self.fetcher.fetch_hot_themes(target_date)
        if not df.empty:
            self.db.upsert_hot_themes(df)
        # Collect stocks for top themes
        top_n = int(cfg.get("top_themes", 10))
        top_codes = df.sort_values("rank").head(top_n)["theme_code"].tolist()
        for code in top_codes:
            stocks = self.fetcher.fetch_theme_stocks(code, target_date)
            if not stocks.empty:
                self.db.upsert_hot_theme_stocks(stocks)
```

在 `run()` 方法的 step sequence 中添加：

```python
            self._step_stock_concepts(stock_codes, target_date)
            self._step_hot_themes(target_date)
```

（放在 `_step_factor_ic` 之后、`_step_quality_report` 之前）

- [ ] **Step 5: 跑全部测试确认不破坏现有逻辑**

```bash
pytest tests/ -x --tb=short -q
```

Expect: 108+ tests pass (no regressions).

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: wire concept/hot-theme data into pipeline and storage"
```

---

### Task A4: 接入评分器 — 替换占位数据

**Files:**
- Create: `core/scoring/enrich.py` (数据增强层)
- Modify: `tests/test_hot_candidate_scoring.py` (加集成测试)

- [ ] **Step 1: 创建数据增强模块**

```python
"""Enrich candidate DataFrame with concept/themel data for scoring."""

from __future__ import annotations

import pandas as pd


def enrich_sector_info(
    candidates: pd.DataFrame,
    concept_map: pd.DataFrame,
    hot_themes: pd.DataFrame,
    theme_stocks: pd.DataFrame,
) -> pd.DataFrame:
    """Add sector/themel fields to candidate rows from DB lookup tables.

    Input candidates must have ts_code and trade_date columns.
    Concept map: stock_concept_blocks (ts_code, concept_code, concept_name)
    Hot themes: hot_theme_daily (theme_code, trade_date, theme_name, rank, pct_chg, ...)
    Theme stocks: hot_theme_stocks (theme_code, trade_date, ts_code, ...)
    """
    if candidates.empty:
        return candidates

    df = candidates.copy()
    # Ensure expected columns exist
    for col in [
        "sector_limit_up_count", "sector_pct_chg", "sector_main_direction",
        "sector_rank", "limit_up_streak",
    ]:
        if col not in df.columns:
            df[col] = None

    # Enrich from hot themes: match candidate ts_code against theme_stocks
    if not theme_stocks.empty and "ts_code" in theme_stocks.columns:
        merged = df[["ts_code", "trade_date"]].merge(
            theme_stocks,
            on=["ts_code", "trade_date"],
            how="left",
            suffixes=("", "_ths"),
        )
        # Count stocks in same theme
        if "theme_code" in theme_stocks.columns:
            theme_counts = (
                theme_stocks.groupby(["theme_code", "trade_date"])
                .size()
                .reset_index(name="sector_limit_up_count")
            )
            merged = merged.merge(
                theme_counts,
                on=["theme_code", "trade_date"],
                how="left",
            )
            df["sector_limit_up_count"] = merged["sector_limit_up_count"].fillna(0).astype(int)

        # Theme percentage change from hot_themes
        if not hot_themes.empty:
            theme_pct = hot_themes[["theme_code", "trade_date", "pct_chg"]].rename(
                columns={"pct_chg": "sector_pct_chg_ths"}
            )
            merged = merged.merge(theme_pct, on=["theme_code", "trade_date"], how="left")
            df["sector_pct_chg"] = merged["sector_pct_chg_ths"].fillna(
                df.get("sector_pct_chg", 0)
            )

    return df
```

- [ ] **Step 2: 写增强层单测**

```python
    def test_enrich_adds_sector_counts_from_theme_stocks(self):
        from core.scoring.enrich import enrich_sector_info

        candidates = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-19"]),
        })
        theme_stocks = pd.DataFrame({
            "theme_code": ["T1", "T1", "T1"],
            "trade_date": pd.to_datetime(["2026-06-19"] * 3),
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
        })
        result = enrich_sector_info(candidates, pd.DataFrame(), pd.DataFrame(), theme_stocks)
        self.assertEqual(result.iloc[0]["sector_limit_up_count"], 3)
```

- [ ] **Step 3: 提交**

```bash
git add core/scoring/enrich.py tests/test_hot_candidate_scoring.py
git commit -m "feat: add candidate enricher for sector/themel scoring dimensions"
```

---

## Track B: 完整版回测框架

### Task B1: 回测配置 + 引擎核心

**Files:**
- Create: `core/backtest/__init__.py`
- Create: `core/backtest/config.py`
- Create: `core/backtest/engine.py`
- Create: `tests/test_backtest_engine.py`

- [ ] **Step 1: 写配置类**

```python
"""Backtest configuration types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class BacktestConfig:
    """Complete backtest configuration."""
    # Date range
    start_date: date | str = "2024-01-01"
    end_date: date | str = "2026-06-01"

    # Factor selection
    factor_columns: list[str] = field(default_factory=lambda: [
        "return_20d", "return_60d", "volatility_20d",
        "ma20_bias", "ma60_bias", "max_drawdown_60d",
        "volume_ratio_20d", "liquidity_20d",
    ])
    label_column: str = "forward_return_20d"
    top_n: int = 50
    bottom_n: int = 50

    # Portfolio
    initial_capital: float = 1_000_000.0
    max_positions: int = 20
    position_sizing: str = "equal_weight"  # equal_weight, score_weighted
    rebalance_frequency: str = "daily"      # daily, weekly(5d), monthly(21d)
    turnover_limit: float = 0.5             # max portfolio turnover per rebalance

    # Execution
    execution_model: str = "next_open"      # next_open, vwap_estimate
    slippage_bps: float = 5.0               # basis points
    commission_bps: float = 2.5             # basis points
    stamp_duty_bps: float = 10.0            # 印花税, sell only

    # Neutralization
    industry_neutral: bool = False
    market_cap_neutral: bool = False

    # Parameter scan
    scan_enabled: bool = False
    scan_params: dict[str, list[Any]] = field(default_factory=dict)

    # Signal decay
    decay_enabled: bool = False
    decay_half_life: int = 5               # days to halve signal strength

    # Attribution
    attribution_enabled: bool = False

    # Output
    output_dir: str = "data/backtest"

    @classmethod
    def from_dict(cls, d: dict) -> BacktestConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
```

- [ ] **Step 2: 写引擎空跑测试**

```python
import unittest
import pandas as pd

from core.backtest.config import BacktestConfig
from core.backtest.engine import BacktestEngine


class BacktestEngineTest(unittest.TestCase):
    def setUp(self):
        self.config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            top_n=5,
            bottom_n=5,
        )

    def test_engine_initializes_with_config(self):
        engine = BacktestEngine(self.config)
        self.assertEqual(engine.config.top_n, 5)
        self.assertEqual(engine.config.initial_capital, 1_000_000.0)

    def test_engine_returns_empty_result_for_empty_data(self):
        engine = BacktestEngine(self.config)
        result = engine.run(
            factors=pd.DataFrame(),
            labels=pd.DataFrame(),
            kline=pd.DataFrame(),
        )
        self.assertEqual(result["total_return"], 0.0)
        self.assertEqual(result["sharpe_ratio"], 0.0)
        self.assertEqual(len(result["daily_returns"]), 0)
```

Run: `pytest tests/test_backtest_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 实现引擎核心**

```python
"""Backtest engine: factor-based stock selection and simulation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from core.backtest.config import BacktestConfig
from core.backtest.portfolio import Portfolio
from core.backtest.analytics import compute_metrics


class BacktestEngine:
    """Config-driven factor backtest engine."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.portfolio = None
        self.daily_returns = []

    def run(
        self,
        factors: pd.DataFrame,
        labels: pd.DataFrame,
        kline: pd.DataFrame,
        daily_basic: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Execute full backtest and return performance report."""
        if factors.empty or kline.empty:
            return {
                "total_return": 0.0, "annual_return": 0.0,
                "sharpe_ratio": 0.0, "max_drawdown": 0.0,
                "win_rate": 0.0, "daily_returns": [],
                "trades": [], "attribution": {},
            }

        start = pd.Timestamp(self.config.start_date)
        end = pd.Timestamp(self.config.end_date)

        factors["trade_date"] = pd.to_datetime(factors["trade_date"], errors="coerce")
        kline["trade_date"] = pd.to_datetime(kline["trade_date"], errors="coerce")
        labels["trade_date"] = pd.to_datetime(labels["trade_date"], errors="coerce")

        trade_dates = sorted(
            factors[factors["trade_date"].between(start, end)]["trade_date"].unique()
        )
        if len(trade_dates) < 2:
            return {
                "total_return": 0.0, "annual_return": 0.0,
                "sharpe_ratio": 0.0, "max_drawdown": 0.0,
                "win_rate": 0.0, "daily_returns": [],
                "trades": [], "attribution": {},
            }

        self.portfolio = Portfolio(self.config.initial_capital)
        daily_returns = []
        trades = []

        for i, signal_date in enumerate(trade_dates[:-1]):
            next_date = trade_dates[i + 1]
            self._rebalance(factors, signal_date)
            day_return = self._mark_to_market(
                kline, signal_date, next_date, trades
            )
            daily_returns.append({
                "signal_date": signal_date,
                "exec_date": next_date,
                "daily_return": day_return,
                "nav": self.portfolio.nav,
            })

        self.daily_returns = daily_returns
        return compute_metrics(
            daily_returns, trades, self.config,
            start_date=start, end_date=end,
        )

    def _rebalance(self, factors: pd.DataFrame, signal_date: pd.Timestamp):
        """Select top-N stocks and rebalance portfolio."""
        day_factors = factors[factors["trade_date"] == signal_date]
        if day_factors.empty:
            return

        scored = self._score_stocks(day_factors)
        top_stocks = scored.head(self.config.top_n)["ts_code"].tolist()

        self.portfolio.rebalance(
            target_stocks=top_stocks,
            signal_date=signal_date,
            max_positions=self.config.max_positions,
            position_sizing=self.config.position_sizing,
            turnover_limit=self.config.turnover_limit,
        )

    def _score_stocks(self, day_factors: pd.DataFrame) -> pd.DataFrame:
        """Compute composite factor score for one day's cross-section."""
        factor_cols = [
            c for c in self.config.factor_columns if c in day_factors.columns
        ]
        if not factor_cols:
            day_factors = day_factors.copy()
            day_factors["_score"] = 0
            return day_factors.sort_values("_score", ascending=False)

        df = day_factors.copy()
        # Cross-sectional z-score each factor, then equal-weight sum
        for col in factor_cols:
            vals = df[col].astype(float)
            mean_val = vals.mean()
            std_val = vals.std()
            if std_val and std_val > 0:
                df[f"{col}_z"] = (vals - mean_val) / std_val
            else:
                df[f"{col}_z"] = 0.0

        z_cols = [f"{c}_z" for c in factor_cols]
        # Direction: assume factors with positive IC should rank higher
        # User can override per-factor direction via config
        df["_score"] = df[z_cols].sum(axis=1)
        return df.sort_values("_score", ascending=False)

    def _mark_to_market(
        self,
        kline: pd.DataFrame,
        signal_date: pd.Timestamp,
        next_date: pd.Timestamp,
        trades: list,
    ) -> float:
        """Compute daily P&L by marking positions to next day's open."""
        return self.portfolio.mark_to_market(
            kline, signal_date, next_date, trades,
            slippage_bps=self.config.slippage_bps,
            commission_bps=self.config.commission_bps,
            stamp_duty_bps=self.config.stamp_duty_bps,
        )
```

Run: `pytest tests/test_backtest_engine.py -v`
Expected: PASS (2 tests)

- [ ] **Step 4: 提交**

```bash
git add core/backtest/ tests/test_backtest_engine.py
git commit -m "feat: add backtest engine core and config"
```

---

### Task B2: 组合管理器

**Files:**
- Create: `core/backtest/portfolio.py`
- Modify: `tests/test_backtest_engine.py` (add portfolio tests)

- [ ] **Step 1: 写 Portfolio 单测**

```python
    def test_portfolio_initializes_with_cash(self):
        from core.backtest.portfolio import Portfolio
        p = Portfolio(1_000_000.0)
        self.assertEqual(p.nav, 1_000_000.0)
        self.assertEqual(p.cash, 1_000_000.0)
        self.assertEqual(len(p.positions), 0)

    def test_portfolio_rebalance_adds_equal_weight_positions(self):
        from core.backtest.portfolio import Portfolio
        p = Portfolio(1_000_000.0)
        p.rebalance(
            target_stocks=["000001.SZ", "000002.SZ"],
            signal_date=pd.Timestamp("2024-01-02"),
            max_positions=10,
            position_sizing="equal_weight",
            turnover_limit=1.0,
        )
        self.assertEqual(len(p.positions), 2)
        self.assertAlmostEqual(sum(pos.weight for pos in p.positions.values()), 1.0)
```

Run: `pytest tests/test_backtest_engine.py::BacktestEngineTest::test_portfolio_initializes_with_cash -v`
Expected: FAIL

- [ ] **Step 2: 实现 Portfolio**

```python
"""Portfolio: position tracking, rebalancing, mark-to-market."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Position:
    ts_code: str
    shares: int = 0
    avg_cost: float = 0.0
    weight: float = 0.0

    @property
    def market_value(self) -> float:
        return self.shares * self._last_price

    @property
    def _last_price(self) -> float:
        return self.avg_cost  # updated on mark_to_market


class Portfolio:
    """Tracks cash, positions, and NAV throughout a backtest."""

    def __init__(self, initial_capital: float = 1_000_000.0):
        self.initial_capital = float(initial_capital)
        self.cash = self.initial_capital
        self.positions: dict[str, Position] = {}
        self._last_prices: dict[str, float] = {}
        self._trade_log: list[dict] = []

    @property
    def nav(self) -> float:
        position_value = sum(
            pos.shares * self._last_prices.get(pos.ts_code, pos.avg_cost)
            for pos in self.positions.values()
        )
        return self.cash + position_value

    def rebalance(
        self,
        target_stocks: list[str],
        signal_date: pd.Timestamp,
        max_positions: int = 20,
        position_sizing: str = "equal_weight",
        turnover_limit: float = 0.5,
    ):
        """Adjust portfolio to target weights.

        Args:
            target_stocks: ordered list of target stock codes (best first)
            max_positions: cap on number of positions
            position_sizing: "equal_weight" or "score_weighted"
            turnover_limit: max fraction of portfolio to turn over (unused in v1)
        """
        targets = target_stocks[:max_positions]
        if not targets:
            return

        n = len(targets)
        target_weight = 1.0 / n

        current_codes = set(self.positions.keys())
        target_set = set(targets)

        # Sell positions not in targets
        for code in list(self.positions.keys()):
            if code not in target_set:
                self._sell(code, signal_date)

        # Adjust existing positions to target weight
        for code in targets:
            if code in self.positions:
                self.positions[code].weight = target_weight
            else:
                self.positions[code] = Position(
                    ts_code=code,
                    weight=target_weight,
                )

    def mark_to_market(
        self,
        kline: pd.DataFrame,
        signal_date: pd.Timestamp,
        exec_date: pd.Timestamp,
        trades: list,
        slippage_bps: float = 5.0,
        commission_bps: float = 2.5,
        stamp_duty_bps: float = 10.0,
    ) -> float:
        """Mark positions to execution prices and compute daily return.

        For next_open execution: use exec_date's open price.
        """
        if not self.positions:
            return 0.0

        exec_kline = kline[kline["trade_date"] == exec_date]
        if exec_kline.empty:
            return 0.0

        price_map = dict(zip(exec_kline["ts_code"], exec_kline["open"]))

        prev_nav = self.nav
        total_position_value = 0.0

        for code, pos in list(self.positions.items()):
            price = price_map.get(code)
            if price is None or price <= 0:
                continue
            self._last_prices[code] = float(price)

            # On first mark, set avg_cost and allocate cash
            if pos.avg_cost == 0.0:
                alloc = self.initial_capital * pos.weight
                # Apply slippage: buy at slightly worse price
                buy_price = price * (1 + slippage_bps / 10000)
                pos.shares = int(alloc / buy_price)
                pos.avg_cost = buy_price
                cost = pos.shares * buy_price
                self.cash -= cost
                # Commission
                comm = cost * commission_bps / 10000
                self.cash -= comm

            total_position_value += pos.shares * price

        new_nav = self.cash + total_position_value
        day_return = (new_nav - prev_nav) / prev_nav if prev_nav > 0 else 0.0
        return float(day_return)

    def _sell(self, ts_code: str, trade_date: pd.Timestamp):
        """Remove a position and return cash."""
        pos = self.positions.pop(ts_code, None)
        if pos is None:
            return
        price = self._last_prices.get(ts_code, pos.avg_cost)
        proceeds = pos.shares * price
        self.cash += proceeds
        # Stamp duty on sell
        stamp = proceeds * 10.0 / 10000
        self.cash -= stamp
        self._trade_log.append({
            "ts_code": ts_code, "action": "sell",
            "shares": pos.shares, "price": price,
            "trade_date": trade_date,
        })
```

Run: `pytest tests/test_backtest_engine.py -v`
Expected: PASS (4 tests)

- [ ] **Step 3: 提交**

```bash
git add core/backtest/portfolio.py tests/test_backtest_engine.py
git commit -m "feat: add backtest portfolio manager with rebalancing and execution"
```

---

### Task B3: 绩效分析

**Files:**
- Create: `core/backtest/analytics.py`
- Modify: `tests/test_backtest_engine.py`

- [ ] **Step 1: 写绩效分析单测**

```python
    def test_compute_metrics_returns_zero_for_empty(self):
        from core.backtest.analytics import compute_metrics
        result = compute_metrics([], [], self.config)
        self.assertEqual(result["sharpe_ratio"], 0.0)
        self.assertEqual(result["total_return"], 0.0)

    def test_compute_metrics_calculates_sharpe_from_returns(self):
        from core.backtest.analytics import compute_metrics
        returns = [
            {"signal_date": pd.Timestamp("2024-01-02"), "exec_date": pd.Timestamp("2024-01-03"), "daily_return": 0.01, "nav": 1_010_000.0},
            {"signal_date": pd.Timestamp("2024-01-03"), "exec_date": pd.Timestamp("2024-01-04"), "daily_return": -0.005, "nav": 1_004_950.0},
        ]
        result = compute_metrics(returns, [], self.config)
        self.assertAlmostEqual(result["total_return"], 0.00495, places=4)
        self.assertTrue(result["sharpe_ratio"] != 0.0)
```

- [ ] **Step 2: 实现 compute_metrics + 分层分析**

```python
"""Performance analytics: metrics, layer analysis, and decay."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def compute_metrics(
    daily_returns: list[dict],
    trades: list[dict],
    config: Any,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Compute full performance report from daily returns and trades."""
    if not daily_returns:
        return _empty_report()

    rets = np.array([d["daily_return"] for d in daily_returns], dtype=float)
    navs = np.array([d["nav"] for d in daily_returns], dtype=float)

    total_return = float((navs[-1] / navs[0] - 1) if navs[0] > 0 else 0.0)

    n_days = len(rets)
    trading_days_per_year = 252
    ann_return = float(((1 + total_return) ** (trading_days_per_year / n_days) - 1) if n_days > 0 else 0.0)

    # Sharpe: annualized excess return / annualized volatility, risk-free = 0
    mean_ret = float(np.mean(rets))
    std_ret = float(np.std(rets, ddof=1))
    sharpe = float((mean_ret / std_ret * math.sqrt(trading_days_per_year)) if std_ret > 0 else 0.0)

    # Max drawdown
    cummax = np.maximum.accumulate(navs)
    drawdowns = (navs - cummax) / cummax
    max_dd = float(np.min(drawdowns))

    # Win rate
    wins = int(np.sum(rets > 0))
    win_rate = float(wins / n_days if n_days > 0 else 0.0)

    # Calmar ratio
    calmar = float(ann_return / abs(max_dd) if max_dd != 0 else 0.0)

    # Sortino ratio (downside deviation only)
    downside = rets[rets < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = float((mean_ret / downside_std * math.sqrt(trading_days_per_year)) if downside_std > 0 else 0.0)

    return {
        "total_return": total_return,
        "annual_return": ann_return,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
        "sortino_ratio": sortino,
        "win_rate": win_rate,
        "n_days": n_days,
        "n_trades": len(trades),
        "daily_returns": daily_returns,
        "trades": trades,
        "nav_series": navs.tolist(),
        "attribution": {},
    }


def compute_layer_returns(
    factors: pd.DataFrame,
    labels: pd.DataFrame,
    factor_column: str,
    label_column: str = "forward_return_20d",
    n_groups: int = 5,
) -> dict[str, Any]:
    """Split stocks into n_groups by factor value and compute mean forward return per group.

    Returns layer analysis: each group's mean return, top-bottom spread, IC.
    """
    if factors.empty or labels.empty:
        return {"groups": [], "spread": 0.0, "ic_mean": 0.0}

    merged = factors[["ts_code", "trade_date", factor_column]].merge(
        labels[["ts_code", "trade_date", label_column]],
        on=["ts_code", "trade_date"],
        how="inner",
    )
    if merged.empty:
        return {"groups": [], "spread": 0.0, "ic_mean": 0.0}

    merged = merged.dropna(subset=[factor_column, label_column])
    if merged.empty:
        return {"groups": [], "spread": 0.0, "ic_mean": 0.0}

    # Per date: rank into n_groups
    results = []
    for date, group in merged.groupby("trade_date"):
        if len(group) < n_groups:
            continue
        group["_quantile"] = pd.qcut(
            group[factor_column], n_groups, labels=False, duplicates="drop"
        )
        for q in range(n_groups):
            q_data = group[group["_quantile"] == q]
            if not q_data.empty:
                results.append({
                    "trade_date": date,
                    "group": q,
                    "mean_return": float(q_data[label_column].mean()),
                    "count": len(q_data),
                })

    if not results:
        return {"groups": [], "spread": 0.0, "ic_mean": 0.0}

    layer_df = pd.DataFrame(results)
    group_means = layer_df.groupby("group")["mean_return"].mean().to_dict()

    spread = group_means.get(n_groups - 1, 0) - group_means.get(0, 0)

    # Mean cross-sectional Spearman IC
    ic_values = []
    for _, group in merged.groupby("trade_date"):
        if len(group) < 10:
            continue
        ic = group[factor_column].corr(group[label_column], method="spearman")
        if not math.isnan(ic):
            ic_values.append(ic)
    ic_mean = float(np.mean(ic_values)) if ic_values else 0.0

    return {
        "groups": [
            {"group": g, "mean_return": v} for g, v in sorted(group_means.items())
        ],
        "spread": spread,
        "ic_mean": ic_mean,
    }


def _empty_report() -> dict[str, Any]:
    return {
        "total_return": 0.0, "annual_return": 0.0,
        "sharpe_ratio": 0.0, "max_drawdown": 0.0,
        "calmar_ratio": 0.0, "sortino_ratio": 0.0,
        "win_rate": 0.0, "n_days": 0, "n_trades": 0,
        "daily_returns": [], "trades": [],
        "nav_series": [], "attribution": {},
    }
```

Run: `pytest tests/test_backtest_engine.py -v`
Expected: PASS (6 tests)

- [ ] **Step 3: 提交**

```bash
git add core/backtest/analytics.py tests/test_backtest_engine.py
git commit -m "feat: add backtest performance analytics and layer analysis"
```

---

### Task B4: 中性化（行业 + 市值）

**Files:**
- Create: `core/backtest/neutralizer.py`

- [ ] **Step 1: 写中性化单测**

```python
class FactorNeutralizerTest(unittest.TestCase):
    def test_industry_neutral_subtracts_group_mean(self):
        from core.backtest.neutralizer import industry_neutralize
        df = pd.DataFrame({
            "ts_code": ["A", "B", "C", "D"],
            "trade_date": pd.Timestamp("2024-01-02"),
            "factor_value": [10.0, 20.0, 30.0, 40.0],
            "industry": ["银行", "银行", "科技", "科技"],
        })
        result = industry_neutralize(df, "factor_value", "industry")
        # 银行 mean=15, 科技 mean=35
        self.assertAlmostEqual(result.loc[0, "factor_value_neutral"], -5.0)
        self.assertAlmostEqual(result.loc[3, "factor_value_neutral"], 5.0)

    def test_market_cap_neutral_residualizes(self):
        from core.backtest.neutralizer import market_cap_neutralize
        df = pd.DataFrame({
            "ts_code": ["A", "B", "C"],
            "trade_date": pd.Timestamp("2024-01-02"),
            "factor_value": [1.0, 2.0, 3.0],
            "log_market_cap": [10.0, 11.0, 12.0],
        })
        result = market_cap_neutralize(df, "factor_value", "log_market_cap")
        self.assertIn("factor_value_neutral", result.columns)
```

- [ ] **Step 2: 实现中性化**

```python
"""Factor neutralization: industry and market-cap adjustments."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


def industry_neutralize(
    df: pd.DataFrame,
    factor_col: str = "factor_value",
    industry_col: str = "industry",
    output_col: str = "factor_value_neutral",
) -> pd.DataFrame:
    """Subtract industry mean from factor values (cross-sectional per date)."""
    if df.empty or industry_col not in df.columns:
        df[output_col] = df.get(factor_col, 0)
        return df

    result = df.copy()
    result[output_col] = result[factor_col].astype(float)
    result[output_col] = result[output_col] - result.groupby(
        ["trade_date", industry_col], group_keys=False
    )[factor_col].transform("mean")
    return result


def market_cap_neutralize(
    df: pd.DataFrame,
    factor_col: str = "factor_value",
    mcap_col: str = "log_market_cap",
    output_col: str = "factor_value_neutral",
) -> pd.DataFrame:
    """Regress factor on log market cap cross-sectionally and return residuals."""
    if df.empty or mcap_col not in df.columns:
        df[output_col] = df.get(factor_col, 0)
        return df

    result = df.copy()
    result[output_col] = result[factor_col].astype(float)

    for date, group in result.groupby("trade_date"):
        valid = group[[factor_col, mcap_col]].dropna()
        if len(valid) < 10:
            continue
        X = valid[[mcap_col]].values
        y = valid[factor_col].values
        model = LinearRegression().fit(X, y)
        predicted = model.predict(X)
        residuals = y - predicted
        result.loc[valid.index, output_col] = residuals

    return result
```

Run: `pytest tests/test_backtest_engine.py -v`
Expected: PASS (8 tests)

- [ ] **Step 3: 提交**

```bash
git add core/backtest/neutralizer.py tests/test_backtest_engine.py
git commit -m "feat: add factor neutralization (industry and market cap)"
```

---

### Task B5: 参数扫描 + 信号衰减

**Files:**
- Create: `core/backtest/scanner.py`
- Create: `core/backtest/decay.py`

- [ ] **Step 1: 写参数扫描 + 衰减单测**

```python
    def test_scanner_runs_grid_over_top_n_and_factors(self):
        from core.backtest.scanner import ParameterScanner
        from core.backtest.config import BacktestConfig
        cfg = BacktestConfig(
            start_date="2024-01-01", end_date="2024-01-15",
            top_n=5,
        )
        scanner = ParameterScanner(cfg)
        scan_config = {
            "top_n": [3, 5],
            "factor_columns": [
                ["return_20d"],
                ["return_20d", "volatility_20d"],
            ],
        }
        combinations = scanner._build_combinations(scan_config)
        self.assertEqual(len(combinations), 4)  # 2×2

    def test_signal_decay_reduces_score_over_time(self):
        from core.backtest.decay import exponential_decay
        scores = pd.Series([1.0, 1.0, 1.0])
        ages = pd.Series([0, 3, 10])
        decayed = exponential_decay(scores, ages, half_life=5)
        self.assertAlmostEqual(decayed.iloc[0], 1.0)
        self.assertLess(decayed.iloc[2], 0.5)
```

- [ ] **Step 2: 实现 parameter scanner**

```python
"""ParameterScanner: grid search over backtest parameters."""

from __future__ import annotations

import itertools
from copy import deepcopy
from typing import Any

import pandas as pd

from core.backtest.config import BacktestConfig


class ParameterScanner:
    """Scan parameter combinations and rank results."""

    def __init__(self, base_config: BacktestConfig):
        self.base_config = base_config

    def build_combinations(self, scan_params: dict[str, list[Any]]) -> list[dict]:
        """Generate all parameter combinations."""
        keys = list(scan_params.keys())
        values = list(scan_params.values())
        combos = []
        for combo in itertools.product(*values):
            combos.append(dict(zip(keys, combo)))
        return combos

    def apply_combo(self, config: BacktestConfig, combo: dict) -> BacktestConfig:
        """Create a new config with overridden parameters."""
        new_cfg = deepcopy(config)
        for key, value in combo.items():
            setattr(new_cfg, key, value)
        return new_cfg

    def scan(
        self,
        factors: pd.DataFrame,
        labels: pd.DataFrame,
        kline: pd.DataFrame,
        daily_basic: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Run all combinations and return ranked results."""
        from core.backtest.engine import BacktestEngine

        combos = self.build_combinations(self.base_config.scan_params)
        results = []
        for combo in combos:
            cfg = self.apply_combo(self.base_config, combo)
            engine = BacktestEngine(cfg)
            report = engine.run(factors, labels, kline, daily_basic)
            results.append({**combo, **{
                "sharpe": report["sharpe_ratio"],
                "total_return": report["total_return"],
                "max_drawdown": report["max_drawdown"],
                "calmar": report["calmar_ratio"],
            }})
        return pd.DataFrame(results).sort_values("sharpe", ascending=False)
```

- [ ] **Step 3: 实现 signal decay**

```python
"""Signal decay: model diminishing signal strength over time."""

from __future__ import annotations

import numpy as np
import pandas as pd


def exponential_decay(
    scores: pd.Series,
    ages_days: pd.Series,
    half_life: int = 5,
) -> pd.Series:
    """Apply exponential decay: score * 0.5^(age/half_life)."""
    decay_factor = np.power(0.5, ages_days.astype(float) / half_life)
    return scores * decay_factor


def apply_decay_to_signals(
    signals: pd.DataFrame,
    half_life: int = 5,
    signal_col: str = "_score",
    output_col: str = "_score_decayed",
) -> pd.DataFrame:
    """Age signals by days since first appearance and apply decay."""
    if signals.empty:
        signals[output_col] = 0.0
        return signals

    df = signals.sort_values(["ts_code", "trade_date"]).copy()
    df["_first_seen"] = df.groupby("ts_code")["trade_date"].transform("min")
    df["_age_days"] = (df["trade_date"] - df["_first_seen"]).dt.days
    df[output_col] = exponential_decay(
        df[signal_col].fillna(0), df["_age_days"].fillna(0), half_life
    )
    return df.drop(columns=["_first_seen", "_age_days"])
```

Run: `pytest tests/test_backtest_engine.py -v`
Expected: PASS (10 tests)

- [ ] **Step 4: 提交**

```bash
git add core/backtest/scanner.py core/backtest/decay.py tests/test_backtest_engine.py
git commit -m "feat: add parameter scanner and signal decay modules"
```

---

### Task B6: 归因分析 + Pipeline 集成

**Files:**
- Create: `core/backtest/attribution.py`
- Modify: `pipeline.py` (add backtest step)
- Modify: `config.yaml` (add backtest config section)

- [ ] **Step 1: 实现归因分析**

```python
"""Performance attribution: decompose P&L by factor."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def factor_attribution(
    portfolio_returns: list[dict],
    factor_exposures: pd.DataFrame,
    factor_names: list[str],
) -> dict[str, Any]:
    """Decompose portfolio returns into factor contributions via regression.

    Args:
        portfolio_returns: list of {signal_date, daily_return}
        factor_exposures: DataFrame with factor values per date per stock
        factor_names: list of factor column names to attribute to

    Returns:
        dict with factor_name -> contribution (fraction of total return)
    """
    if not portfolio_returns or factor_exposures.empty:
        return {}

    rets = pd.DataFrame(portfolio_returns)
    rets["signal_date"] = pd.to_datetime(rets["signal_date"])

    # Simple approach: compute factor ICs and weight by factor z-score
    contributions = {}
    for factor in factor_names:
        if factor not in factor_exposures.columns:
            continue
        # Mean cross-sectional IC as factor strength proxy
        ic_values = []
        for _, group in factor_exposures.groupby("trade_date"):
            if "forward_return_20d" in group.columns and len(group) >= 10:
                ic = group[factor].corr(group["forward_return_20d"], method="spearman")
                if not np.isnan(ic):
                    ic_values.append(ic)
        mean_ic = float(np.mean(ic_values)) if ic_values else 0.0
        contributions[factor] = mean_ic

    total = sum(abs(v) for v in contributions.values()) or 1.0
    return {
        k: v / total for k, v in contributions.items()
    }
```

- [ ] **Step 2: 在 pipeline.py 添加回测步骤**

```python
    def _step_backtest(self, target_date: str):
        """Run factor backtest if configured."""
        cfg = self.config.get("backtest", {})
        if not cfg.get("enabled", False):
            return

        from core.backtest.config import BacktestConfig
        from core.backtest.engine import BacktestEngine

        logger.info("执行因子回测...")
        bt_config = BacktestConfig.from_dict(cfg)

        end = pd.Timestamp(
            (target_date or datetime.now().strftime("%Y%m%d")).replace("-", "")
        )
        start = end - pd.Timedelta(days=cfg.get("lookback_days", 365))

        factors = self.db.query_factor_dataset(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            factor_columns=bt_config.factor_columns,
            label_column=bt_config.label_column,
        )
        kline = self.db.query_kline_range(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))

        engine = BacktestEngine(bt_config)
        report = engine.run(factors, pd.DataFrame(), kline)

        # Save report
        import json
        os.makedirs(bt_config.output_dir, exist_ok=True)
        report_path = os.path.join(
            bt_config.output_dir,
            f"backtest_{end.strftime('%Y%m%d')}.json",
        )
        with open(report_path, "w") as f:
            json.dump({
                k: v for k, v in report.items()
                if k not in ("daily_returns", "trades", "nav_series")
            }, f, indent=2, default=str)

        logger.info(
            f"回测完成: 总收益={report['total_return']:.2%}, "
            f"Sharpe={report['sharpe_ratio']:.2f}, "
            f"最大回撤={report['max_drawdown']:.2%}"
        )
```

在 `run()` 方法中添加：

```python
            self._step_backtest(target_date)
```

（放在 `_step_factor_ic` 之后）

- [ ] **Step 3: 在 config.yaml 添加默认配置**

在 `config.yaml` 末尾添加：

```yaml
backtest:
  enabled: false
  start_date: "2024-01-01"
  lookback_days: 365
  top_n: 50
  bottom_n: 50
  initial_capital: 1000000.0
  max_positions: 20
  position_sizing: equal_weight
  rebalance_frequency: daily
  execution_model: next_open
  slippage_bps: 5.0
  commission_bps: 2.5
  stamp_duty_bps: 10.0
  industry_neutral: false
  market_cap_neutral: false
  scan_enabled: false
  decay_enabled: false
  decay_half_life: 5
  attribution_enabled: false
  output_dir: data/backtest
  factor_columns:
    - return_20d
    - return_60d
    - volatility_20d
    - ma20_bias
    - ma60_bias
    - max_drawdown_60d
    - volume_ratio_20d
    - liquidity_20d
  label_column: forward_return_20d
```

- [ ] **Step 4: 跑全部测试确认**

```bash
pytest tests/ -x --tb=short -q
```

Expect: All existing tests pass + new backtest tests pass.

- [ ] **Step 5: 最终提交**

```bash
git add -A
git commit -m "feat: add attribution analysis and backtest pipeline integration"
```
