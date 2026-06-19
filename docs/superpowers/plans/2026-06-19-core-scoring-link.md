# 打通核心选股链路 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入东财龙虎榜+资金流数据源，替换评分器占位数据，用真实数据跑一次分层回测验证选股效果。

**Architecture:** 继续 AStockDataGateway 模式，2 个新数据源 → DuckDB 2 张新表 → enrich.py 统一增强 → hot_candidate 替换占位 → backtest engine 实跑。

**Tech Stack:** Python 3.12, pandas, DuckDB, mootdx, requests, unittest

---

## Task C1: 东财龙虎榜数据采集

**Files:**
- Create: `core/astock/eastmoney/dragon_tiger.py`
- Create: `tests/test_astock_dragon_tiger.py`

- [ ] **Step 1: 写空响应测试**

```python
import unittest
from unittest.mock import Mock

from core.astock.eastmoney.dragon_tiger import fetch_dragon_tiger


class DragonTigerTest(unittest.TestCase):
    def test_returns_empty_for_empty_response(self):
        client = Mock()
        client.datacenter.return_value = []
        result = fetch_dragon_tiger(client, "000001.SZ", "2026-06-19")
        self.assertTrue(result.empty)
        self.assertEqual(
            list(result.columns),
            ["ts_code", "trade_date", "buy_amount", "sell_amount",
             "net_amount", "reason", "source"],
        )


if __name__ == "__main__":
    unittest.main()
```

Run: `pytest tests/test_astock_dragon_tiger.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 2: 实现最少代码让测试通过**

```python
"""East Money dragon tiger board (龙虎榜) data source."""

from __future__ import annotations

import pandas as pd

from core.astock.eastmoney.client import EastMoneyDataClient
from core.astock.symbols import normalize_code

DT_COLUMNS = [
    "ts_code", "trade_date", "buy_amount", "sell_amount",
    "net_amount", "reason", "source",
]


def fetch_dragon_tiger(
    client: EastMoneyDataClient,
    ts_code: str,
    trade_date: str,
) -> pd.DataFrame:
    """Fetch dragon tiger board detail for a stock on a given date."""
    return pd.DataFrame(columns=DT_COLUMNS)
```

Run: `pytest tests/test_astock_dragon_tiger.py -v`
Expected: PASS (1 test)

Commit: `git add ... && git commit -m "feat: add dragon tiger stub"`

- [ ] **Step 3: 加解析测试 + 完整实现**

```python
    def test_parses_datacenter_response(self):
        client = Mock()
        client.datacenter.return_value = [
            {
                "SECURITY_CODE": "000001.SZ", "TRADE_DATE": "2026-06-19 00:00:00",
                "BUY_AMT": 50000000.0, "SELL_AMT": 30000000.0,
                "NET_AMT": 20000000.0, "REASON": "日涨幅偏离值达7%",
            },
        ]
        result = fetch_dragon_tiger(client, "000001.SZ", "2026-06-19")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.iloc[0]["buy_amount"], 50000000.0)
        self.assertAlmostEqual(result.iloc[0]["net_amount"], 20000000.0)
        self.assertEqual(result.iloc[0]["reason"], "日涨幅偏离值达7%")
        self.assertEqual(result.iloc[0]["source"], "eastmoney_dragon_tiger")
```

完整实现 `fetch_dragon_tiger`:

```python
def fetch_dragon_tiger(
    client: EastMoneyDataClient,
    ts_code: str,
    trade_date: str,
) -> pd.DataFrame:
    """Fetch dragon tiger board detail for a stock on a given date.

    Uses East Money datacenter report RPT_DAILYBILLBOARD_DETAILSNEW.
    """
    symbol = normalize_code(ts_code)
    date_str = str(trade_date).replace("-", "")[:8]
    rows = client.datacenter(
        report_name="RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f'(SECURITY_CODE="{symbol.symbol}")(TRADE_DATE>="{date_str}")(TRADE_DATE<="{date_str}")',
        page_size=50,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    if not rows:
        return pd.DataFrame(columns=DT_COLUMNS)

    data = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        buy_amt = float(r.get("BUY_AMT", 0) or 0)
        sell_amt = float(r.get("SELL_AMT", 0) or 0)
        net_amt = float(r.get("NET_AMT", 0) or 0)
        reason = str(r.get("REASON", ""))
        trade_dt = str(r.get("TRADE_DATE", ""))[:10]
        if not trade_dt:
            continue
        data.append({
            "ts_code": symbol.ts_code,
            "trade_date": pd.Timestamp(trade_dt),
            "buy_amount": buy_amt,
            "sell_amount": sell_amt,
            "net_amount": net_amt,
            "reason": reason,
            "source": "eastmoney_dragon_tiger",
        })
    return pd.DataFrame(data)[DT_COLUMNS].reset_index(drop=True)
```

Run: `pytest tests/test_astock_dragon_tiger.py -v`
Expected: PASS (2 tests)

- [ ] **Step 4: Commit**

```bash
git add ... && git commit -m "feat: implement eastmoney dragon tiger data source"
```

---

## Task C2: 东财个股资金流数据采集

**Files:**
- Create: `core/astock/eastmoney/fund_flow.py`
- Create: `tests/test_astock_fund_flow.py`

- [ ] **Step 1: 写测试 + 实现**

```python
import unittest
from unittest.mock import Mock

import pandas as pd

from core.astock.eastmoney.fund_flow import fetch_stock_fund_flow


class FundFlowTest(unittest.TestCase):
    def test_returns_empty_for_empty_response(self):
        client = Mock()
        client.datacenter.return_value = []
        result = fetch_stock_fund_flow(client, "000001.SZ", "2026-06-19")
        self.assertTrue(result.empty)

    def test_parses_ddx_ddy_and_flow_fields(self):
        client = Mock()
        client.datacenter.return_value = [
            {
                "SECURITY_CODE": "000001.SZ", "TRADE_DATE": "2026-06-19 00:00:00",
                "MAIN_NET_AMT": 1.5e8, "MAIN_NET_RATIO": 5.2,
                "HUGE_NET_AMT": 8e7, "BIG_NET_AMT": 7e7,
                "MID_NET_AMT": -3e7, "SMALL_NET_AMT": -1.2e8,
                "DDX": 0.75, "DDY": 0.62,
            },
        ]
        result = fetch_stock_fund_flow(client, "000001.SZ", "2026-06-19")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.iloc[0]["main_net_amt"], 1.5e8)
        self.assertAlmostEqual(result.iloc[0]["ddx"], 0.75)
        self.assertAlmostEqual(result.iloc[0]["ddy"], 0.62)
        self.assertEqual(result.iloc[0]["source"], "eastmoney_fund_flow")
```

`core/astock/eastmoney/fund_flow.py`:

```python
"""East Money individual stock fund flow (个股资金流) data source."""

from __future__ import annotations

import pandas as pd

from core.astock.eastmoney.client import EastMoneyDataClient
from core.astock.symbols import normalize_code

FF_COLUMNS = [
    "ts_code", "trade_date",
    "main_net_amt", "main_net_ratio",
    "huge_net_amt", "big_net_amt",
    "mid_net_amt", "small_net_amt",
    "ddx", "ddy",
    "source",
]


def fetch_stock_fund_flow(
    client: EastMoneyDataClient,
    ts_code: str,
    trade_date: str,
) -> pd.DataFrame:
    """Fetch daily fund flow for a stock.

    Uses East Money datacenter report RPT_DMSK_FN_INDEXCP.
    """
    symbol = normalize_code(ts_code)
    date_str = str(trade_date).replace("-", "")[:8]
    rows = client.datacenter(
        report_name="RPT_DMSK_FN_INDEXCP",
        filter_str=f'(SECURITY_CODE="{symbol.symbol}")(TRADE_DATE>="{date_str}")(TRADE_DATE<="{date_str}")',
        page_size=10,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    if not rows:
        return pd.DataFrame(columns=FF_COLUMNS)

    data = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        trade_dt = str(r.get("TRADE_DATE", ""))[:10]
        if not trade_dt:
            continue
        data.append({
            "ts_code": symbol.ts_code,
            "trade_date": pd.Timestamp(trade_dt),
            "main_net_amt": float(r.get("MAIN_NET_AMT", 0) or 0),
            "main_net_ratio": float(r.get("MAIN_NET_RATIO", 0) or 0),
            "huge_net_amt": float(r.get("HUGE_NET_AMT", 0) or 0),
            "big_net_amt": float(r.get("BIG_NET_AMT", 0) or 0),
            "mid_net_amt": float(r.get("MID_NET_AMT", 0) or 0),
            "small_net_amt": float(r.get("SMALL_NET_AMT", 0) or 0),
            "ddx": float(r.get("DDX", 0) or 0),
            "ddy": float(r.get("DDY", 0) or 0),
            "source": "eastmoney_fund_flow",
        })
    return pd.DataFrame(data)[FF_COLUMNS].reset_index(drop=True)
```

Run: `pytest tests/test_astock_fund_flow.py -v`
Expected: PASS (2 tests)

- [ ] **Step 2: Commit**

```bash
git add ... && git commit -m "feat: add eastmoney stock fund flow data source"
```

---

## Task C3: 存储 + Gateway + Pipeline 集成

**Files:**
- Modify: `core/data_storage.py`
- Modify: `core/astock/gateway.py`
- Modify: `pipeline.py`
- Modify: `config.yaml`

- [ ] **Step 1: data_storage.py — 加 2 张新表 Schema**

在 SCHEMA_SQL 中添加（插在 `stock_concept_blocks` 表之后）：

```sql
-- ====================================================================
-- 龙虎榜明细
-- ====================================================================
CREATE TABLE IF NOT EXISTS dragon_tiger_daily (
    ts_code       VARCHAR NOT NULL,
    trade_date    DATE NOT NULL,
    buy_amount    DOUBLE,
    sell_amount   DOUBLE,
    net_amount    DOUBLE,
    reason        VARCHAR,
    source        VARCHAR,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_dt_date ON dragon_tiger_daily (trade_date);

-- ====================================================================
-- 个股资金流
-- ====================================================================
CREATE TABLE IF NOT EXISTS stock_fund_flow_daily (
    ts_code       VARCHAR NOT NULL,
    trade_date    DATE NOT NULL,
    main_net_amt  DOUBLE,
    main_net_ratio DOUBLE,
    huge_net_amt  DOUBLE,
    big_net_amt   DOUBLE,
    mid_net_amt   DOUBLE,
    small_net_amt DOUBLE,
    ddx           DOUBLE,
    ddy           DOUBLE,
    source        VARCHAR,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_ff_date ON stock_fund_flow_daily (trade_date);
```

- [ ] **Step 2: data_storage.py — 加 upsert 方法**

```python
    def upsert_dragon_tiger(self, df: pd.DataFrame):
        if df.empty:
            return
        self.conn.register("_tmp_dt", df)
        self.conn.execute(
            "INSERT OR REPLACE INTO dragon_tiger_daily SELECT * FROM _tmp_dt"
        )
        self.conn.unregister("_tmp_dt")

    def upsert_fund_flow(self, df: pd.DataFrame):
        if df.empty:
            return
        self.conn.register("_tmp_ff", df)
        self.conn.execute(
            "INSERT OR REPLACE INTO stock_fund_flow_daily SELECT * FROM _tmp_ff"
        )
        self.conn.unregister("_tmp_ff")
```

- [ ] **Step 3: gateway.py — 加 2 个 fetch 方法**

```python
    def fetch_dragon_tiger(self, ts_code: str, trade_date: str) -> pd.DataFrame:
        from core.astock.eastmoney.dragon_tiger import fetch_dragon_tiger
        return fetch_dragon_tiger(self.eastmoney, ts_code, trade_date)

    def fetch_stock_fund_flow(self, ts_code: str, trade_date: str) -> pd.DataFrame:
        from core.astock.eastmoney.fund_flow import fetch_stock_fund_flow
        return fetch_stock_fund_flow(self.eastmoney, ts_code, trade_date)
```

- [ ] **Step 4: pipeline.py — 加 2 个 step 方法**

```python
    def _step_dragon_tiger(self, stock_codes: list, target_date: str):
        cfg = self.config.get("fetch", {}).get("dragon_tiger", {})
        if not cfg.get("enabled", False):
            return
        logger.info("采集龙虎榜数据...")
        sample = stock_codes[:int(cfg.get("max_stocks", 200))]
        all_rows = []
        for code in sample:
            df = self.fetcher.fetch_dragon_tiger(code, target_date)
            if not df.empty:
                all_rows.append(df)
        if all_rows:
            self.db.upsert_dragon_tiger(pd.concat(all_rows, ignore_index=True))

    def _step_fund_flow(self, stock_codes: list, target_date: str):
        cfg = self.config.get("fetch", {}).get("fund_flow", {})
        if not cfg.get("enabled", False):
            return
        logger.info("采集资金流数据...")
        sample = stock_codes[:int(cfg.get("max_stocks", 200))]
        all_rows = []
        for code in sample:
            df = self.fetcher.fetch_stock_fund_flow(code, target_date)
            if not df.empty:
                all_rows.append(df)
        if all_rows:
            self.db.upsert_fund_flow(pd.concat(all_rows, ignore_index=True))
```

在 `run()` 中 `_step_stock_concepts` 之后添加：
```python
            self._step_dragon_tiger(stock_codes, target_date)
            self._step_fund_flow(stock_codes, target_date)
```

- [ ] **Step 5: config.yaml — 加配置**

```yaml
  dragon_tiger:
    enabled: false
    max_stocks: 200
  fund_flow:
    enabled: false
    max_stocks: 200
```

- [ ] **Step 6: 全量测试**

```bash
pytest tests/ -x --tb=short -q
```
Expected: all 145+ pass

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: wire dragon tiger and fund flow into pipeline"
```

---

## Task C4: enrich.py 扩展 + 评分器连线

**Files:**
- Modify: `core/scoring/enrich.py`
- Modify: `core/scoring/hot_candidate.py` (替换占位数据来源)

- [ ] **Step 1: 扩展 enrich.py — 加 enrich_fund_flow**

```python
def enrich_fund_flow(
    candidates: pd.DataFrame,
    fund_flow: pd.DataFrame,
) -> pd.DataFrame:
    """Add DDX/DDY/main_net fields from fund flow data."""
    if candidates.empty or fund_flow.empty:
        return candidates

    df = candidates.copy()
    ff = fund_flow[["ts_code", "trade_date", "ddx", "ddy",
                     "main_net_amt", "main_net_ratio"]].copy()
    merged = df.merge(ff, on=["ts_code", "trade_date"], how="left")
    for col in ["ddx", "ddy", "main_net_ratio"]:
        if col in merged.columns:
            df[col] = merged[col].fillna(0)
    return df


def enrich_daily_kline_features(
    candidates: pd.DataFrame,
    kline: pd.DataFrame,
) -> pd.DataFrame:
    """Add open_gap_pct, volume_ratio, turnover from daily_kline."""
    if candidates.empty or kline.empty:
        return candidates

    df = candidates.copy()
    kl = kline[["ts_code", "trade_date", "open", "close", "vol", "pct_chg"]].copy()
    # open_gap_pct = today_open / yesterday_close - 1
    kl = kl.sort_values(["ts_code", "trade_date"])
    kl["prev_close"] = kl.groupby("ts_code")["close"].shift(1)
    kl["open_gap_pct"] = (kl["open"] / kl["prev_close"] - 1) * 100
    kl["volume_ratio"] = kl["vol"] / kl.groupby("ts_code")["vol"].transform(
        lambda x: x.rolling(5, min_periods=1).mean()
    )

    merged = df.merge(
        kl[["ts_code", "trade_date", "open_gap_pct", "volume_ratio", "pct_chg"]],
        on=["ts_code", "trade_date"],
        how="left",
    )
    for col in ["open_gap_pct", "volume_ratio"]:
        if col in merged.columns:
            df[col] = merged[col].fillna(0)
    return df
```

- [ ] **Step 2: 给 enrich.py 加测试**

在 `tests/test_hot_candidate_scoring.py` 中添加：

```python
    def test_enrich_fund_flow_adds_ddx_ddy(self):
        from core.scoring.enrich import enrich_fund_flow
        candidates = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-19"]),
        })
        ff = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-19"]),
            "ddx": [0.75],
            "ddy": [0.62],
        })
        result = enrich_fund_flow(candidates, ff)
        self.assertAlmostEqual(result.iloc[0]["ddx"], 0.75)
```

- [ ] **Step 3: 更新 hot_candidate.py — 修改评分器入口**

在 `score_hot_candidates` 函数开头，替换占位数据逻辑：不再假定 ddx/ddy/open_gap 已在 DataFrame 中。如果缺失，标记 score_reason 而非直接给低分。实际连线在外部调用方完成（pipeline 或独立脚本先从 DB 查数据再 enrich 再评分）。

当前 `score_hot_candidates` 已经有保守低分逻辑（缺失字段给低分），无需改动核心评分逻辑。改动在**调用方**：pipeline 或独立脚本需要在评分前调用 enrich 函数。

- [ ] **Step 4: 全量测试**

```bash
pytest tests/ -x --tb=short -q
```
Expected: 147+ pass

- [ ] **Step 5: Commit**

```bash
git add ... && git commit -m "feat: extend enrich with fund flow and kline features"
```

---

## Task C5: 回测实跑验证

**Files:**
- Modify: `config.yaml` (开启回测)
- Create: `scripts/run_backtest.py` (独立回测脚本)

- [ ] **Step 1: 创建独立回测脚本**

```python
#!/usr/bin/env python3
"""Run factor backtest with real data and output results."""

import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.backtest.config import BacktestConfig
from core.backtest.engine import BacktestEngine
from core.backtest.analytics import compute_layer_returns
from core.data_storage import QuantDB
import yaml


def main():
    # Load config
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    db = QuantDB(cfg["storage"]["db_path"], cfg)
    bt_cfg_dict = cfg.get("backtest", {})
    bt_config = BacktestConfig.from_dict(bt_cfg_dict)

    # Set date range
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = bt_cfg_dict.get("start_date", "2024-01-01")

    print(f"回测区间: {start_date} → {end_date}")

    # Query factor dataset
    factors = db.query_factor_dataset(
        start_date.replace("-", ""),
        end_date.replace("-", ""),
        factor_columns=bt_config.factor_columns,
        label_column=bt_config.label_column,
    )
    print(f"因子数据: {len(factors)} 行")

    labels = db.conn.execute(
        "SELECT * FROM factor_labels WHERE trade_date BETWEEN ? AND ?",
        [start_date, end_date],
    ).df()
    print(f"标签数据: {len(labels)} 行")

    kline = db.conn.execute(
        "SELECT ts_code, trade_date, open, close, high, low, vol, amount "
        "FROM daily_kline WHERE trade_date BETWEEN ? AND ?",
        [start_date, end_date],
    ).df()
    print(f"K线数据: {len(kline)} 行")

    # Run backtest
    engine = BacktestEngine(bt_config)
    report = engine.run(factors, labels, kline)

    print(f"\n========== 回测结果 ==========")
    print(f"总收益:    {report['total_return']:.2%}")
    print(f"年化收益:  {report['annual_return']:.2%}")
    print(f"Sharpe:   {report['sharpe_ratio']:.2f}")
    print(f"最大回撤:  {report['max_drawdown']:.2%}")
    print(f"Calmar:   {report['calmar_ratio']:.2f}")
    print(f"Sortino:  {report['sortino_ratio']:.2f}")
    print(f"胜率:      {report['win_rate']:.2%}")

    # Layer analysis for each factor
    print(f"\n========== 因子分层分析 ==========")
    for factor in bt_config.factor_columns:
        layer = compute_layer_returns(factors, labels, factor, bt_config.label_column)
        print(f"  {factor}: spread={layer['spread']:.4f}, ic_mean={layer['ic_mean']:.4f}")

    # Save report
    os.makedirs(bt_config.output_dir, exist_ok=True)
    report_path = os.path.join(bt_config.output_dir, f"backtest_{end_date}.json")
    report_save = {k: v for k, v in report.items()
                   if k not in ("daily_returns", "trades", "nav_series")}
    with open(report_path, "w") as f:
        json.dump(report_save, f, indent=2, default=str)
    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行回测脚本**

```bash
cd "/Volumes/XDC/Quantitative trading/ai_quant_pipeline" && python scripts/run_backtest.py
```

Expected: 输出回测结果（总收益、Sharpe、分层分析）。如果 DB 数据充足，应该看到非零结果。

- [ ] **Step 3: Commit**

```bash
git add scripts/run_backtest.py && git commit -m "feat: add standalone backtest runner script"
```
