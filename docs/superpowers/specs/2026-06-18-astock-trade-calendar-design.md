# AStock Trade Calendar Design

## Goal

Replace the temporary business-day calendar in `AStockDataGateway` with a real A-share trading calendar source while keeping a deterministic fallback for network failures.

## Source Strategy

Use Tencent Finance daily K-line dates for the Shanghai Composite index (`000001.SH`) as the primary calendar source. A date with an index daily bar is treated as an open A-share trading day. This avoids AKShare/Tushare and keeps East Money out of market infrastructure.

If Tencent returns an error, bad JSON, an empty payload, or an unexpected schema, the client returns a business-day fallback calendar and marks it with `source = "business_day_fallback"` so logs and tests can distinguish it.

## Interface

Add `core/astock/market/trade_calendar.py` with `TencentTradeCalendarClient.fetch_trade_calendar(year) -> pd.DataFrame`.

The returned DataFrame must include:

- `exchange`
- `trade_date`
- `is_open`
- `pretrade_date`
- `source`

`trade_date` and `pretrade_date` use pandas timestamps. `is_open` is `1` for open days. The gateway passes the DataFrame to existing storage, which ignores extra columns such as `exchange` and `source`.

## Gateway Integration

`AStockDataGateway` accepts an injectable `calendar_client`. `fetch_trade_calendar(year)` delegates to that client. This keeps tests deterministic and isolates provider parsing from pipeline orchestration.

## Testing

Add tests for:

- Tencent payload parsing creates only real trading days and excludes missing holiday/weekend dates.
- `pretrade_date` points to the prior parsed trading day.
- malformed payloads return stable fallback rows.
- gateway calls the injected calendar client.

## Scope

This change does not implement stock list, financial data, ST history, or复权因子. It only replaces the stage-one approximate calendar.
