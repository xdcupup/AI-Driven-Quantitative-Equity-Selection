# AStock Trade Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary business-day calendar in `AStockDataGateway` with a real Tencent-derived A-share trading calendar.

**Architecture:** Add a focused Tencent calendar client under `core/astock/market/`. The client derives open dates from Shanghai Composite daily K-line bars and falls back to business days on bad responses. The gateway delegates calendar calls to this injectable client.

**Tech Stack:** Python 3.11, pandas, requests, unittest.

---

### Task 1: Calendar Client

**Files:**
- Create: `core/astock/market/trade_calendar.py`
- Modify: `tests/test_astock_market.py`

- [ ] Write failing tests for Tencent calendar parsing, fallback behavior, and `pretrade_date`.
- [ ] Run `./.venv/bin/python -m unittest tests.test_astock_market.TencentTradeCalendarClientTest -v` and confirm import failure.
- [ ] Implement `TencentTradeCalendarClient` with stable schema and business-day fallback.
- [ ] Re-run the focused test and confirm pass.

### Task 2: Gateway Integration

**Files:**
- Modify: `core/astock/gateway.py`
- Modify: `tests/test_astock_gateway.py`

- [ ] Write a failing gateway test proving `fetch_trade_calendar()` calls the injected calendar client.
- [ ] Run `./.venv/bin/python -m unittest tests.test_astock_gateway -v` and confirm failure.
- [ ] Inject `calendar_client` into `AStockDataGateway` and delegate `fetch_trade_calendar()`.
- [ ] Re-run gateway tests and confirm pass.

### Task 3: Docs, Verification, Commit

**Files:**
- Modify: `README.md`
- Modify: `config.yaml`

- [ ] Update docs to remove the “working-day approximate calendar” limitation.
- [ ] Run `./.venv/bin/python -m unittest discover -s tests -v`.
- [ ] Run `./.venv/bin/python -m py_compile core/astock/market/trade_calendar.py core/astock/gateway.py`.
- [ ] Commit and push.
