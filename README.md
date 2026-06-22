# AI Quant Pipeline

AI 量化选股系统的数据采集层。当前重构目标是按 `a-stock-data` 思路建立直连数据源内核：行情不再依赖 AKShare / Tushare，日 K 线优先走 mootdx，HTTP 兜底走百度股市通，估值和实时 quote 走腾讯财经，东财只保留给其独有数据并统一限流。

## 当前状态

- 已建立 `core/astock` 新数据源包。
- 已完成代码规范化：`000001.SZ`、`SZ000001`、`000001.sz`、`920000.BJ` 等格式统一解析。
- 已完成腾讯 quote 客户端：PE、PB、市值、换手率、涨跌停、成交额等字段。
- 已完成百度股市通 K 线客户端：带 MA5/MA10/MA20 的兜底行情。
- 已完成 mootdx 日 K 线客户端：沪深主行情源，北交所首阶段返回空表。
- 已完成 mootdx 全市场股票列表客户端：沪深 A 股列表，过滤指数、基金、债券和 B 股。
- 已完成 mootdx finance 最新财务快照适配，可写入现有 `financial_indicators` 表。
- 已完成 mootdx F10 基础信息接口：支持目录和指定章节文本读取。
- 已完成新浪三表原始财报接口和 `financial_statements` 入库：支持资产负债表、利润表、现金流量表长表读取。
- 已完成基础财务因子派生：从原始三表生成 `financial_factors`。
- 已完成基础技术/量价因子派生：从 `daily_kline` 生成 `technical_factors`。
- 已完成第一版标签和 IC/IR 评估：从 `daily_kline` 生成 `factor_labels`，从因子和标签生成 `factor_ic_detail` / `factor_ic_summary`。
- 已完成东财特色数据客户端：所有请求必须走 `em_get` 串行限速入口。
- 已完成 `AStockDataGateway`：pipeline 默认可切到新数据层。

首阶段保留的兼容限制：

- 复权因子暂未接入，`daily_kline` 保存未复权价格。
- 历史 ST、名称变更暂不再走 Tushare，后续接直连源补齐。
- 新浪三表当前作为原始报表源入库，默认关闭；全量任务可按需开启。
- 交易日历使用腾讯上证指数日 K 线日期派生，接口失败时才回退工作日近似。
- 全市场股票列表优先从配置显式代码池读取；未配置时通过 mootdx 拉取沪深 A 股列表。

## 数据源策略

| 数据 | 默认来源 | 说明 |
| --- | --- | --- |
| 日 K 线 | mootdx | 通达信 TCP，首选行情源 |
| 日 K 线兜底 | 百度股市通 | HTTP，返回 MA 字段 |
| PE/PB/市值/换手率/涨跌停 | 腾讯财经 | HTTP GBK 接口 |
| 资产负债表/利润表/现金流量表 | 新浪财经 | HTTP，原始报表长表 |
| 龙虎榜、解禁、融资融券、大宗交易、股东户数、分红、研报、新闻 | 东财 | 仅独有数据使用，必须通过 `em_get` 限速 |

项目依赖里已经移除 `akshare` 和 `tushare`。

## 目录结构

```text
ai_quant_pipeline/
├── pipeline.py
├── config.yaml
├── requirements.txt
├── core/
│   ├── astock/
│   │   ├── gateway.py
│   │   ├── symbols.py
│   │   ├── market/
│   │   │   ├── mootdx_client.py
│   │   │   ├── tencent_quote.py
│   │   │   └── baidu_kline.py
│   │   ├── fundamental/
│   │   │   ├── mootdx_finance.py
│   │   │   ├── mootdx_f10.py
│   │   │   └── sina_finance.py
│   │   └── eastmoney/
│   │       └── client.py
│   ├── data_cleaner.py
│   ├── data_storage.py
│   └── data_quality.py
├── data/
├── logs/
├── scripts/
└── tests/
```

## 环境准备

```bash
cd "/Volumes/XDC/Quantitative trading/ai_quant_pipeline"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

mootdx 使用通达信 TCP 行情，网络环境需要能连通对应行情服务器。腾讯和百度路径是 HTTP 直连。

## 配置

核心配置在 `config.yaml`：

```yaml
data_source:
  engine: astock
  market_primary: mootdx
  market_fallback: baidu
  quote_source: tencent
  eastmoney_usage: unique_only
```

小规模测试可以显式指定股票池：

```yaml
stock_pool:
  codes:
    - 000001.SZ
    - 600000.SH
```

如果没有配置 `stock_pool.codes`，网关会通过 mootdx 获取沪深 A 股股票列表，并过滤指数、基金、债券和 B 股。

新浪三表默认关闭。需要全量拉取原始财报时开启：

```yaml
fetch:
  financial_statements:
    enabled: true
    full_refresh_only: true
    statement_types:
      - income_statement
      - balance_sheet
      - cash_flow
  factor_derivation:
    enabled: true
  technical_factors:
    enabled: true
  factor_labels:
    enabled: true

evaluation:
  factor_ic:
    enabled: true
```

## 常用命令

运行测试：

```bash
cd "/Volumes/XDC/Quantitative trading/ai_quant_pipeline"
.venv/bin/python -m unittest discover -s tests -v
```

测试新数据源核心模块：

```bash
.venv/bin/python -m unittest \
  tests.test_astock_symbols \
  tests.test_astock_market \
  tests.test_astock_eastmoney \
  tests.test_astock_gateway \
  -v
```

小规模采集：

```bash
.venv/bin/python pipeline.py --test --full-refresh --start-date 2026-06-01 --date 2026-06-16
```

增量采集：

```bash
.venv/bin/python pipeline.py --date 2026-06-16
```

全量重建：

```bash
./scripts/rebuild_market_data.sh --start-date 2021-06-18 --date 2026-06-18
```

查看日志：

```bash
tail -n 120 logs/pipeline.log
```

## 数据语义

`daily_kline.open/high/low/close` 保存未复权价格。未知值使用 `NULL`，不使用业务有效值伪装。

关键字段：

- `amount`：mootdx / 百度 / 腾讯 quote 可提供时正常落库。
- `adj_factor`：首阶段暂未接入，质量报告中列为已知缺失。
- `price_type`：当前为 `none`，表示未复权。
- `source`：记录行情来源，如 `mootdx`、`baidu`、`tencent`。
- `financial_indicators`：mootdx finance 当前提供最新快照；同比类字段缺少可靠来源时保持 `NULL`。
- `F10`：当前通过 gateway 提供目录和章节文本接口，暂未设计入库表。
- `financial_statements`：新浪三表原始长表，字段为 `ts_code/report_type/end_date/ann_date/item_order/item/value/value_text/item_yoy/source`。`item_order` 保留原始行序，避免重复科目名覆盖；`value_text` 保留原始值，`value` 尽量转为数字，文本科目保留在 `value_text`。
- `financial_factors`：财务因子宽表，字段包括 `revenue/net_profit/total_assets/total_liabilities/equity/operating_cashflow/revenue_yoy/net_profit_yoy/debt_to_assets/roe/operating_cashflow_to_profit`。查询时优先用 `ann_date` 防前视。
- `technical_factors`：技术/量价因子宽表，字段包括 `return_5d/return_20d/return_60d/volatility_20d/ma20_bias/ma60_bias/max_drawdown_60d/volume_ratio_20d/liquidity_20d`。来源为 `daily_kline`，查询时按 `trade_date <= as_of_date` 取最新可见行。
- `factor_labels`：监督学习标签表，字段包括 `forward_return_5d/forward_return_10d/forward_return_20d/max_drawdown_20d`。这些字段使用信号日之后的价格生成，只能用于训练、评估和回测归因，不能作为信号日可见因子。
- `factor_ic_detail` / `factor_ic_summary`：因子 IC/IR 评估结果，默认用 Spearman 截面相关衡量技术因子对 `forward_return_20d` 的预测能力。

## 策略规则

已复用一版“抱团股”规则，代码在 `core/strategies/crowded.py`。

核心口径：

- 月初选股：从可交易股票池中，取过去 22 个交易日平均成交额最高的 10 只股票。
- 过滤条件：剔除 ST、非上市、新股上市不足 120 天、停牌和 OHLC 异常样本。
- 每日择时：计算目标股票过去 25 个交易日的等权组合动量。
- 状态机：目标池为空则清仓；动量大于 0 且空仓则等权开仓；动量大于 0 且已持仓则继续持有；动量小于等于 0 则清仓或继续空仓。

## 短线候选评分

已接入稳定版短线候选股评分器，代码在 `core/scoring/hot_candidate.py`。当前主策略为 `hot_candidate_v2_stable`：只使用已能稳定采集的日 K、成交额、换手率、量比、流通市值和安全过滤字段；资金流、封单、板块题材等不稳定来源不计入总分。

总分 100 分，不包含题材验证：

- 可买性/溢价风险：25
- 涨停强度/连板惯性：20
- 量价承接质量：20
- 安全过滤：15
- 流动性/市值结构：20

为兼容当前 `hot_candidate_scores` 表结构，部分旧字段仍会保留：`capital_persistence_score`、`seal_quality_score`、`sector_resonance_score` 固定为 0；`leader_status_score` 暂时承载“涨停强度/连板惯性”的 20 分。题材验证字段随候选结果返回，暂不计入 `total_score` 排序。

### 短线候选每日评分流水线

每日评分入口已接入主流水线，代码在 `core/scoring/pipeline.py` 和 `pipeline.py` 的 `_step_hot_candidate_scores`。当前基础候选口径为：目标交易日 `daily_kline.pct_chg >= min_pct_chg`，默认 9%，即优先从涨停/接近涨停样本里生成短线候选。

评分前会尽量补充：

- `daily_kline`：开盘溢价、量比、连板高度。
- `daily_basic`：换手率、流通市值。

以下数据源如果存在，会作为候选附加信息保留，但当前稳定版评分不依赖它们：

- `stock_fund_flow_daily`：DDX、DDY、主力净流入比例。
- `hot_theme_daily` / `hot_theme_stocks`：板块涨幅和板块内热度。

打开配置：

```yaml
scoring:
  hot_candidate:
    enabled: true
    strategy_name: hot_candidate_v2_stable
    min_pct_chg: 9.0
    lookback_days: 10
```

运行主流水线后，评分结果写入 `hot_candidate_scores`，可直接用 `--from-db` 回测。

也可以单独批量生成某个区间的短线评分：

```bash
python scripts/build_hot_candidate_scores.py \
  --start 2026-01-05 \
  --end 2026-06-18 \
  --strategy-name hot_candidate_v2_stable \
  --min-pct-chg 9.0 \
  --lookback-days 10 \
  --output data/hot_candidates/hot_candidate_v2_stable_20260105_20260618_summary.json
```

如果历史 `daily_basic` 不完整，稳定版评分会自动降级：承接质量优先使用量比和成交额，流动性优先使用成交额；有换手率和流通市值时再使用完整规则。

### 短线候选回测

评分结果可以直接进入回测，入口为 `scripts/run_hot_candidate_backtest.py`。当前版本支持从 CSV 读取 `score_hot_candidates` 的输出，也支持从 DuckDB 的 `hot_candidate_scores` 表读取历史评分快照，并从 `daily_kline` 读取对应股票 K 线。

CSV 至少需要包含：

- `ts_code`
- `trade_date`
- `total_score`
- `is_rejected`（可选，有则自动剔除）

示例：

```bash
python scripts/run_hot_candidate_backtest.py \
  --scores-csv data/hot_candidates/scored.csv \
  --start 2026-06-01 \
  --end 2026-06-19 \
  --min-score 60 \
  --top-n 10 \
  --max-positions 10 \
  --output data/backtest/hot_candidate_20260619.json
```

从数据库读取评分结果：

```bash
python scripts/run_hot_candidate_backtest.py \
  --from-db \
  --strategy-name hot_candidate_v2_stable \
  --start 2026-06-01 \
  --end 2026-06-19 \
  --min-score 60 \
  --top-n 10 \
  --max-positions 10 \
  --output data/backtest/hot_candidate_20260619.json
```

当前本地样本区间 `2026-01-05` 到 `2026-06-18` 的初步回测结果：

| 阈值 | 入选信号 | 交易天数 | 总收益 | 年化 | Sharpe | 最大回撤 | 胜率 |
|------|----------|----------|--------|------|--------|----------|------|
| `min-score 60` | 8511 | 107 | -49.30% | -79.80% | -1.93 | -54.76% | 44.86% |
| `min-score 70` | 2769 | 106 | -49.06% | -79.88% | -2.08 | -53.92% | 47.17% |
| `min-score 75` | 500 | 100 | 1.55% | 3.95% | 0.42 | -23.47% | 43.00% |

这组结果只能作为工程验证和参数扫描起点。当前回测已加入“执行日涨停开盘不买入”和“执行日跌停开盘不卖出”约束，`min-score 70` 样本中有 39 次买入被涨停开盘跳过、24 次卖出被跌停开盘跳过。加入执行日卖出后，旧版本用上一价格卖出的乐观偏差被暴露；下一步仍需增强开盘滑点异常处理和真实盘口容量约束。

## 开发说明

新代码优先放在 `core/astock` 下。旧 `core/data_fetcher.py` 只作为 legacy 兼容入口存在，不再继续扩展 AKShare 或 Tushare 路径。

新增数据源时遵守这些原则：

- 行情/K线/实时价优先 mootdx、腾讯、百度。
- 东财只用于其独有数据。
- 所有东财请求必须走 `EastMoneyDataClient.em_get()`。
- 批量任务不要并发请求东财。
- provider 输出 DataFrame 必须有稳定列集合，失败时返回空表而不是抛穿 pipeline。

## 下一步

- 用 `hot_candidate_v2_stable` 跑足够多的历史评分和回测样本，验证稳定字段的有效性。
- 后续如果资金流、封单、板块题材数据源稳定，再作为增强维度重新评估是否计入总分。
- 为东财独有数据补齐龙虎榜、解禁、融资融券、大宗交易、股东户数、分红、研报和新闻模块。
