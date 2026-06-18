# a-stock-data 数据源重写设计

日期：2026-06-18

## 背景

当前项目的数据层从 AKShare、Tushare、East Money、腾讯和新浪逐步演进而来。这个路线已经能跑通采集、清洗、DuckDB 落库和质量报告，但它不符合 `a-stock-data` skill 的目标架构：V3.0 起移除 AKShare，行情层优先通达信 `mootdx` 和腾讯，东财只用于它独有的数据，并且所有东财请求必须统一限流。

本次重写不是继续兼容旧 `DataFetcher` 的内部实现，而是建立一套新的 `a-stock-data` 风格数据源内核。旧代码只作为过渡入口，后续由新 gateway 接管 pipeline。

## 目标

- 行情层不再使用 AKShare。
- 行情/K 线主链路不再使用东财。
- 日 K 线主源使用 `mootdx`，补充源使用百度股市通。
- 实时估值和基础行情使用腾讯财经。
- 东财只用于研报、龙虎榜、解禁、两融、大宗交易、股东户数、分红、资金流、行业板块、新闻和个股基本信息等独有数据。
- 所有 `eastmoney.com` 请求统一走 `em_get()`，串行限流、会话复用、带浏览器 UA。
- 保留 DuckDB、清洗、质量报告和 pipeline 的可复用部分，但数据源 API 重新设计。

## 非目标

- 第一阶段不一次性实现 skill 里的 27 个端点。
- 第一阶段不改因子层、选股策略层或回测层。
- 第一阶段不把东财接口重新放进行情主链路。
- 第一阶段不依赖 Tushare Token；Tushare 不再作为新数据源架构的一部分。

## 数据源优先级

### 行情层

1. `mootdx`
   - 用途：日 K、周 K、月 K、分钟 K、盘口、逐笔成交。
   - 定位：主行情源。
   - 风险：TCP 7709 在国内网络更稳定，海外网络可能超时。

2. 腾讯财经
   - 用途：实时价格、昨收、PE、PB、市值、换手率、量比、涨跌停、指数和 ETF。
   - 定位：估值和实时行情补充源。
   - 注意：接口返回 GBK 编码，字段用 `~` 分隔，PB 在索引 46。

3. 百度股市通
   - 用途：带 MA5、MA10、MA20 的 K 线补充数据。
   - 定位：K 线补充和对账源。
   - 注意：`ResultCode` 可能是数字或字符串，统一按字符串比较。

### 独有数据层

东财只用于通达信、腾讯、百度、新浪、巨潮、同花顺拿不到或不稳定的数据：

- 研报列表和 PDF。
- 个股所属板块、行业板块排名。
- 个股资金流分钟级和 120 日日级。
- 龙虎榜、全市场龙虎榜。
- 限售解禁、融资融券、大宗交易、股东户数、分红。
- 个股新闻、全球资讯。
- 个股基本信息。

### 基础数据和公告层

- `mootdx finance`：季报财务快照。
- `mootdx F10`：公司资料和公告摘要。
- 新浪财报三表：资产负债表、利润表、现金流量表。
- 巨潮公告：公告全文检索和下载入口。

## 新模块结构

```text
core/
  astock/
    __init__.py
    symbols.py
    http.py
    gateway.py
    market/
      __init__.py
      mootdx_client.py
      tencent_quote.py
      baidu_kline.py
    eastmoney/
      __init__.py
      client.py
      reports.py
      signals.py
      capital.py
      news.py
      fundamentals.py
    fundamentals/
      __init__.py
      sina_finance.py
      ths_forecast.py
      mootdx_f10.py
    announcements/
      __init__.py
      cninfo.py
```

### `symbols.py`

统一处理股票代码格式：

- 输入支持 `688017`、`SH688017`、`688017.SH`、`SZ000001`、`BJ832000`。
- 内部主键使用纯 6 位 `symbol`。
- 对存储层输出保留 `ts_code`，例如 `688017.SH`。
- 提供市场前缀：腾讯/百度/新浪使用 `sh`、`sz`、`bj`。
- 提供 mootdx 市场代码：深圳 0，上海 1。北交所第一阶段不进入主行情采集。

### `market/mootdx_client.py`

负责连接 `mootdx.quotes.Quotes.factory(market="std")`，提供：

- `fetch_daily_kline(code, start, end)`。
- `fetch_realtime_quotes(codes)`，仅保留 mootdx 可提供的盘口和成交字段。
- `fetch_transactions(code, trade_date)`。

日 K 输出统一字段：

```text
ts_code, trade_date, open, high, low, close, vol, amount, source
```

### `market/tencent_quote.py`

负责直连 `https://qt.gtimg.cn/q=...`，提供：

- `fetch_quotes(codes)`。
- 输出 `price`、`last_close`、`open`、`high`、`low`、`amount`、`turnover_rate`、`pe_ttm`、`pe_static`、`pb`、`total_mv`、`circ_mv`、`limit_up`、`limit_down`、`volume_ratio`。
- 金额统一转为元，市值统一转为元。

### `market/baidu_kline.py`

负责直连百度股市通 K 线接口，提供：

- `fetch_kline_with_ma(code, start)`。
- 输出原始 K 线字段和 `ma5`、`ma10`、`ma20`。
- 作为 mootdx K 线对账或补充源，不作为第一主源。

### `eastmoney/client.py`

只提供东财共用 HTTP 能力：

- `em_get(url, params=None, headers=None, timeout=15, **kwargs)`。
- `datacenter(report_name, columns="ALL", filter_str="", page_size=50, sort_columns="", sort_types="-1")`。
- 内置最小间隔 1 秒和随机抖动。
- 复用 `requests.Session`。

此模块不得被行情主链路调用。

### `gateway.py`

提供 pipeline 面向的数据源门面：

- `fetch_stock_list()`。
- `fetch_trade_calendar(year)`。
- `fetch_daily_kline(ts_code, start_date, end_date)`。
- `fetch_daily_basic(trade_date)`。
- `compare_market_sources(ts_code, start_date, end_date)`。

第一阶段 `gateway.py` 只覆盖行情层和基础日度字段，不覆盖全部 27 个端点。

## 第一阶段范围

第一阶段只做行情层重写，并让测试和 pipeline 可以跑一个小样本：

1. 新增 `core/astock/symbols.py`。
2. 新增 `core/astock/market/tencent_quote.py`。
3. 新增 `core/astock/market/baidu_kline.py`。
4. 新增 `core/astock/market/mootdx_client.py`。
5. 新增 `core/astock/eastmoney/client.py`，但不接入行情主链路。
6. 新增 `core/astock/gateway.py`。
7. 修改配置，把默认行情主源改为 `mootdx`。
8. 修改 requirements，移除 `akshare` 和 `tushare`，新增 `mootdx` 和 `stockstats`。
9. 修改 README，说明新数据源架构和第一阶段限制。

## 旧代码淘汰策略

- 不继续扩展 `core/providers/akshare.py`，也不新增 AKShare provider。
- 旧 `core/data_fetcher.py` 在第一阶段保留文件，但不作为新功能开发目标。
- pipeline 先通过 `AStockDataGateway` 获得新行情数据。
- 旧 EastMoney K 线、AKShare、Tushare 路径在新 gateway 上不暴露。
- 后续阶段删除旧 provider 文件和旧测试，避免一次性删除导致存储和质量报告测试大面积失效。

## 错误处理

- `mootdx` 连接失败时，gateway 记录错误并尝试百度 K 线补充源。
- 腾讯实时行情失败时，返回空 DataFrame，不阻塞日 K 线采集。
- 百度 K 线失败时，返回空 DataFrame，不回退东财。
- 东财独有数据失败时，保留错误消息，并通过质量报告体现。
- 所有 provider 不抛出裸网络异常到 pipeline，返回空数据或带错误的结构化结果。

## 测试策略

第一阶段使用单元测试锁定解析和路由行为，不依赖真实网络：

- `symbols` 覆盖输入格式、交易所后缀、市场前缀。
- 腾讯解析测试使用 GBK 响应样本，确认 PB 使用索引 46。
- 百度解析测试使用 JSON 样本，确认 `ResultCode` 数字和字符串都能处理。
- mootdx 测试使用 fake client，确认字段归一化。
- gateway 路由测试确认日 K 线优先 mootdx，失败后走百度，不走东财。
- 东财 client 测试确认两次请求之间会 sleep，datacenter 参数拼装正确。

## 迁移风险

- `mootdx` 在当前机器上可能未安装或 TCP 连通性不稳定；第一阶段必须允许用 fake client 测试。
- 旧 pipeline 依赖 `DataFetcher` 的一些方法，切换 gateway 时要分批迁移。
- 旧质量报告把 `amount` 和 `adj_factor` 当作已知缺失字段；新行情源中 `mootdx` 可以提供 `amount`，但复权因子仍不是第一阶段目标。
- 股票列表和交易日历需要替代旧 AKShare/Tushare 来源。第一阶段可以先用配置内股票池或腾讯/东财基础信息补充，第二阶段再补完整全市场股票列表方案。

## 验收标准

- 项目不再新增任何 AKShare 依赖或 AKShare provider。
- 新行情 gateway 的日 K 线主路径不调用东财。
- `requirements.txt` 不再包含 `akshare` 和 `tushare`。
- `config.yaml` 默认数据源不再写 `akshare`。
- 单元测试覆盖新行情层解析、路由和东财限流。
- 全量单元测试通过。
- README 明确写出 `a-stock-data` 数据源优先级和第一阶段范围。
