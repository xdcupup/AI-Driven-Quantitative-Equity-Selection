# AStock Stock List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mootdx-backed full-market stock list source for the astock gateway.

**Architecture:** Create a focused `MootdxStockListClient` that calls `quotes.stocks(market=0/1)`, normalizes rows into the pipeline stock-list schema, and filters out non-A-share instruments. `AStockDataGateway` keeps configured stock pools as the first priority and delegates full-market discovery to this client when no explicit codes are configured.

**Tech Stack:** Python 3.11, pandas, mootdx, unittest.

---

### Task 1: Mootdx Stock List Client

**Files:**
- Create: `core/astock/market/stock_list.py`
- Modify: `tests/test_astock_market.py`

- [x] Write failing tests for normalizing Shenzhen/Shanghai mootdx rows, filtering funds/bonds/B-shares, deduplicating symbols, and returning a stable empty schema when mootdx fails.
- [x] Run `.venv/bin/python -m unittest tests.test_astock_market.MootdxStockListClientTest -v` and confirm the missing module failure.
- [x] Implement `MootdxStockListClient`.
- [x] Re-run focused tests and confirm they pass.

### Task 2: Gateway Integration

**Files:**
- Modify: `core/astock/gateway.py`
- Modify: `tests/test_astock_gateway.py`

- [x] Write a failing gateway test proving `fetch_stock_list()` delegates to the injected stock-list client when no config codes exist.
- [x] Run `.venv/bin/python -m unittest tests.test_astock_gateway -v` and confirm failure.
- [x] Inject `stock_list_client` into `AStockDataGateway` and replace the inline mootdx stock-list code.
- [x] Re-run gateway tests and confirm they pass.

### Task 3: Docs, Verification, Commit

**Files:**
- Modify: `README.md`

- [x] Update docs to mark full-market stock list as implemented through mootdx.
- [x] Run `.venv/bin/python -m unittest discover -s tests -v`.
- [x] Run `.venv/bin/python -m py_compile core/astock/market/stock_list.py core/astock/gateway.py`.
- [ ] Commit and push.
