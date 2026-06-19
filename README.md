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

## 开发说明

新代码优先放在 `core/astock` 下。旧 `core/data_fetcher.py` 只作为 legacy 兼容入口存在，不再继续扩展 AKShare 或 Tushare 路径。

新增数据源时遵守这些原则：

- 行情/K线/实时价优先 mootdx、腾讯、百度。
- 东财只用于其独有数据。
- 所有东财请求必须走 `EastMoneyDataClient.em_get()`。
- 批量任务不要并发请求东财。
- provider 输出 DataFrame 必须有稳定列集合，失败时返回空表而不是抛穿 pipeline。

## 下一步

- 建立标签表：未来 5/10/20 日收益、超额收益和回撤标签。
- 建立 IC/IR 评估和第一版选股打分器。
- 为东财独有数据补齐龙虎榜、解禁、融资融券、大宗交易、股东户数、分红、研报和新闻模块。
