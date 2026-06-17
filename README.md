# AI Quant Pipeline

AI 量化选股系统的数据采集层。当前项目负责 A 股股票列表、交易日历、日 K 线行情采集、清洗、DuckDB 落库和数据质量报告。

> 当前阶段：数据层已补充研究级增强入口；无 Tushare Token 时仍可运行免费行情路径。

## 功能范围

- 获取 A 股股票列表。
- 有 Tushare Token 时保留上市日期、退市日期、上市/退市状态、地域和行业。
- 有 Tushare Token 时采集股票名称变更历史，并标记历史 ST 区间。
- 默认采集沪深市场：`SZSE`、`SSE`。
- 默认排除北交所：`BSE`，包括 `920xxx` 代码段。
- 默认剔除名称含 `ST` 的股票。
- 获取交易日历。
- 获取日 K 线；短窗口优先腾讯财经，长历史未复权请求优先 East Money。
- 主行情表保存未复权价格。
- 有 Tushare Token 时补充 `adj_factor` 和前复权价格列。
- 有 Tushare Token 时补充 `daily_basic` 和季频财务指标。
- 清洗数据但不静默改写原始 OHLC。
- 标记极端涨跌、停牌补行和 OHLC 异常。
- 使用 DuckDB 批量 UPSERT。
- 生成质量报告和流水线运行日志。
- 轻量抽样对比腾讯和新浪收盘价，发现数据源漂移。
- 支持增量补跑和全量重建。

## 数据语义

`daily_kline.open/high/low/close` 保存未复权价格。

未知数据使用 `NULL`，不使用业务有效值伪装：

- `amount`：腾讯路径天然缺失时为 `NULL`；East Money 返回成交额时会落库。
- `adj_factor`：Tushare 返回复权因子时会落库；免费行情源天然缺失。

复权字段：

- `adj_factor`：Tushare 复权因子。
- `adj_open_qfq/adj_high_qfq/adj_low_qfq/adj_close_qfq`：基于 `adj_factor` 计算的前复权价格。

历史状态字段：

- `stock_name_history.is_st`：由 Tushare 名称变更记录中的名称和变更原因识别，用于后续按历史日期排除 ST。
- `data_source_audit.max_close_diff_pct`：腾讯和第二数据源抽样对账的最大收盘价差异百分比，默认第二源为新浪。

研究股票池：

- `research_daily_universe`：日度研究股票池视图，合并行情、上市/退市日期、历史 ST、停牌和 OHLC 异常。
- `is_in_universe`：是否进入默认研究样本。
- `exclude_reason`：未进入样本的原因，例如 `historical_st`、`suspended`、`delisted`、`invalid_ohlc`。

重要标记：

- `flag_extreme`：极端涨跌或质量异常。
- `flag_suspended`：停牌或补行停牌。
- `flag_aligned`：交易日历补出的行。
- `flag_invalid_ohlc`：违反 OHLC 关系。

## 目录结构

```text
ai_quant_pipeline/
├── pipeline.py
├── config.yaml
├── requirements.txt
├── core/
│   ├── data_fetcher.py
│   ├── data_cleaner.py
│   ├── data_storage.py
│   └── data_quality.py
├── data/
│   ├── quant.duckdb
│   ├── backups/
│   └── quality_reports/
├── logs/
├── scripts/
│   ├── run_pipeline.sh
│   └── rebuild_market_data.sh
└── tests/
```

## 环境准备

```bash
cd "/Volumes/XDC/Quantitative trading/ai_quant_pipeline"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果要采集历史股票元数据、复权因子、每日基本面或财务指标，设置：

```bash
export TUSHARE_TOKEN="your_token"
```

没有 `TUSHARE_TOKEN` 时，`daily_basic`、`financial_indicators`、`adj_factor` 和 `adj_*_qfq` 不会实际入库；日 K 线仍可运行。

## 常用命令

### 运行测试

```bash
cd "/Volumes/XDC/Quantitative trading/ai_quant_pipeline"
.venv/bin/python -m unittest discover -s tests -v
```

### 小规模测试采集

只处理前 5 只股票：

```bash
cd "/Volumes/XDC/Quantitative trading/ai_quant_pipeline"
.venv/bin/python pipeline.py --test --full-refresh --start-date 2026-06-01 --date 2026-06-16
```

### 增量采集

```bash
cd "/Volumes/XDC/Quantitative trading/ai_quant_pipeline"
.venv/bin/python pipeline.py --date 2026-06-16
```

增量模式会按每只股票的最新落库日期判断是否需要补采，并保留 10 天重叠窗口，用于正确重算边界收益率。

### 全量重建

推荐使用重建脚本。它会先备份旧库，再从空库重新采集。

```bash
cd "/Volumes/XDC/Quantitative trading/ai_quant_pipeline"
./scripts/rebuild_market_data.sh --start-date 2026-01-01 --date 2026-06-16
```

备份位置：

```text
data/backups/
```

新库位置：

```text
data/quant.duckdb
```

如果要从 2024 年开始：

```bash
./scripts/rebuild_market_data.sh --start-date 2024-01-01 --date 2026-06-16
```

如果要采更长历史：

```bash
./scripts/rebuild_market_data.sh --start-date 2015-01-01 --date 2026-06-16
```

长历史未复权行情会优先尝试 East Money，因为腾讯接口单次返回约 2000 根 K 线。若 East Money 不可用，系统会回退腾讯，但长历史覆盖可能不完整，需要看日志确认。

### 查看日志

```bash
tail -n 120 logs/pipeline.log
```

Cron 日志：

```text
logs/cron_YYYY-MM-DD.log
```

质量报告：

```text
data/quality_reports/
```

### 查询研究股票池

Python 中使用：

```python
from core.data_storage import QuantDB

db = QuantDB("./data/quant.duckdb")
universe = db.query_research_universe("2026-06-16")
```

SQL 中使用：

```sql
SELECT *
FROM research_daily_universe
WHERE trade_date = DATE '2026-06-16'
  AND is_in_universe = TRUE;
```

## 配置说明

核心配置在 `config.yaml`。

默认只采沪深：

```yaml
stock_pool:
  include_exchanges:
    - SZSE
    - SSE
    # - BSE
```

`920xxx` 会被识别为北交所 `BSE/.BJ`，默认不会进入采集队列。

并发配置：

```yaml
concurrency:
  enabled: true
  max_workers: 5
```

如果网络不稳定，可以降低并发：

```yaml
max_workers: 2
```

研究级增强配置：

```yaml
fetch:
  market_data:
    adj_factor: true
    daily_basic: true
  financial_data:
    enabled: true
    batch_size: 100
    max_stocks_per_run: null
quality:
  source_audit:
    enabled: true
    secondary: sina
    sample_size: 10
    lookback_days: 5
    tolerance_pct: 1.0
  known_missing_fields:
    - amount
    - adj_factor
```

`source_audit.secondary` 支持 `sina` 和 `eastmoney`，默认建议使用 `sina`，避免对账流程受东财网络连通性影响。

`known_missing_fields` 表示当前数据源天然缺失的字段，不作为质量报告的异常缺失项。接入 Tushare 或 East Money 成功后，这些字段会自然补齐。

历史 ST 配置：

```yaml
stock_pool:
  st_history:
    enabled: true
    full_refresh_only: true
    batch_size: 100
    max_stocks_per_run: null
```

`full_refresh_only: true` 表示历史名称/ST 只在全量重建时采集，避免每日增量过重。

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 成功 |
| 1 | 部分失败或质量状态 critical |
| 2 | 严重错误 |

返回 `1` 时，已成功数据会入库。可以直接重跑增量继续补缺：

```bash
.venv/bin/python pipeline.py --date 2026-06-16
```

## 常见问题

### 为什么 `920xxx` 之前一直失败？

`920xxx` 属于北交所相关代码段。腾讯当前采集接口只适合沪深 `0/3/6` 代码。现在系统已将 `9` 开头识别为 `BSE/.BJ`，默认配置会排除它们。

### 为什么 `amount` 缺失？

腾讯日 K 线接口未提供可靠成交额。系统保留为 `NULL`，不再写成 `0`。长历史路径会优先尝试 East Money，成功时可以补充成交额。

### 为什么 `adj_factor` 缺失？

免费行情源不提供可靠独立复权因子。设置 `TUSHARE_TOKEN` 且 `fetch.market_data.adj_factor=true` 后，系统会补充 `adj_factor` 和 `adj_*_qfq`。

### 全量跑完返回 1 怎么办？

先看日志：

```bash
tail -n 120 logs/pipeline.log
```

如果只是少量股票失败，直接补跑增量：

```bash
.venv/bin/python pipeline.py --date 2026-06-16
```

如果大面积失败，先检查网络/API 可用性，并降低 `max_workers` 后重跑。

## 数据层验收标准

全量重建后至少检查：

- OHLC 非法记录为 0。
- 主键 `(ts_code, trade_date)` 无重复。
- `raw_close` 等原始价字段完整。
- 无数据源支持的成交额和复权因子保持 `NULL`，有 Tushare/East Money 支持时应显著补齐。
- 有 Tushare Token 时，`stock_list` 应包含上市/退市日期，`financial_indicators` 应有数据。
- 有 Tushare Token 且全量重建后，`stock_name_history` 应有历史名称和 ST 标记。
- `data_source_audit` 应有最近一次抽样对账记录，异常时 `status=warning` 或 `failed`。
- `research_daily_universe` 可查询，且 `exclude_reason` 能解释被剔除样本。
- 目标股票覆盖率达到预期。
- 重复运行不会产生重复记录。
- 流水线日志耗时真实。
- 测试全部通过。

## 后续计划

- 将 `data_source_audit` 异常纳入质量报告摘要。
- 基于 `research_daily_universe` 开始构建因子层。
- 完成数据层验收后进入因子工程。
