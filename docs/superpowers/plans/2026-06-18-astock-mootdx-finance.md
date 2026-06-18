# AStock Mootdx Finance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mootdx finance snapshot adapter that can supply the existing `financial_indicators` storage schema without AKShare/Tushare.

**Architecture:** Create `MootdxFinanceClient` under `core/astock/fundamental/`. It calls `quotes.finance(symbol)`, normalizes the single-row snapshot to the pipeline financial schema, derives conservative ratios where source fields allow, and leaves unavailable fields as `NaN`. `AStockDataGateway.fetch_financial_indicators()` delegates to this client.

**Tech Stack:** Python 3.11, pandas, mootdx, unittest.

---

### Task 1: Mootdx Finance Client

**Files:**
- Create: `core/astock/fundamental/__init__.py`
- Create: `core/astock/fundamental/mootdx_finance.py`
- Modify: `tests/test_astock_fundamental.py`

- [x] Write failing tests for finance snapshot normalization and empty/error behavior.
- [x] Run `.venv/bin/python -m unittest tests.test_astock_fundamental -v` and confirm the missing module failure.
- [x] Implement `MootdxFinanceClient`.
- [x] Re-run focused tests and confirm pass.

### Task 2: Gateway Integration

**Files:**
- Modify: `core/astock/gateway.py`
- Modify: `tests/test_astock_gateway.py`

- [x] Write a failing gateway test proving `fetch_financial_indicators()` delegates to the injected finance client.
- [x] Inject `finance_client` into `AStockDataGateway`.
- [x] Re-run gateway tests and confirm pass.

### Task 3: Docs, Verification, Commit

**Files:**
- Modify: `README.md`
- Modify: `config.yaml`

- [x] Update docs/config to describe mootdx finance as a snapshot source, not a full historical statement source.
- [x] Run `.venv/bin/python -m unittest discover -s tests -v`.
- [x] Run `.venv/bin/python -m py_compile core/astock/fundamental/mootdx_finance.py core/astock/gateway.py`.
- [ ] Commit and push.
