# Research Grade Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the current market-data collector from a runnable MVP into a research-grade data layer with survivorship-bias controls, long-history safeguards, optional adjustment factors, financial indicators, and clearer quality semantics.

**Architecture:** Keep the existing four-module shape: `DataFetcher` owns source-specific normalization, `DataCleaner` owns price semantics, `QuantDB` owns schema/upsert, and `Pipeline` owns orchestration. Prefer optional Tushare enrichment when `TUSHARE_TOKEN` exists, while preserving the current free Tencent/East Money path.

**Tech Stack:** Python 3.11, pandas, DuckDB, AKShare, Tushare, unittest, shell scripts.

---

### Task 1: Historical Stock Metadata

**Files:**
- Modify: `core/data_fetcher.py`
- Modify: `core/data_storage.py`
- Modify: `pipeline.py`
- Test: `tests/test_data_fetcher.py`

- [ ] Write a failing test proving Tushare stock lists preserve `list_date`, `delist_date`, and `list_status`.
- [ ] Add `delist_date` normalization to `_fetch_stock_list_tushare`.
- [ ] Include `delist_date`, `area`, and `industry` in stock-list upserts.
- [ ] Run `python -m unittest tests.test_data_fetcher -v`.

### Task 2: Long-History Market Data Source Selection

**Files:**
- Modify: `core/data_fetcher.py`
- Test: `tests/test_data_fetcher.py`

- [ ] Write a failing test for date ranges exceeding Tencent's 2000-bar limit.
- [ ] Prefer AKShare East Money for long raw-history requests, with Tencent as fallback.
- [ ] Add clear warnings when falling back to Tencent for long ranges.
- [ ] Run `python -m unittest tests.test_data_fetcher -v`.

### Task 3: Adjustment Factors and QFQ Columns

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] Write a failing test proving `_process_single_stock` stores `adj_factor` and `adj_close_qfq` when config enables adjustment factors and Tushare is available.
- [ ] Fetch adjustment factors per stock only when enabled.
- [ ] Map cleaner-generated `adj_open/high/low/close` to storage columns `adj_*_qfq`.
- [ ] Run `python -m unittest tests.test_pipeline -v`.

### Task 4: Financial Indicators Pipeline

**Files:**
- Modify: `pipeline.py`
- Modify: `config.yaml`
- Test: `tests/test_pipeline.py`

- [ ] Write a failing test proving financial indicators are fetched and upserted when enabled and a token-backed source exists.
- [ ] Add a bounded financial step with configurable batch limits for test mode and operational safety.
- [ ] Run `python -m unittest tests.test_pipeline -v`.

### Task 5: Quality Semantics and Documentation

**Files:**
- Modify: `core/data_quality.py`
- Modify: `README.md`
- Test: `tests/test_data_quality.py`

- [ ] Write a failing test proving known source-missing fields like `amount` and `adj_factor` do not become critical missing-data anomalies when configured as known gaps.
- [ ] Add `quality.known_missing_fields`.
- [ ] Document Tushare enrichment, long-history behavior, and remaining research caveats.
- [ ] Run the full test suite.

### Task 6: Historical ST State

**Files:**
- Modify: `core/data_fetcher.py`
- Modify: `core/data_storage.py`
- Modify: `pipeline.py`
- Test: `tests/test_data_fetcher.py`
- Test: `tests/test_data_storage.py`
- Test: `tests/test_pipeline.py`

- [x] Write failing tests for Tushare name-change normalization, ST flagging, and DuckDB upsert.
- [x] Add `stock_name_history` schema and `upsert_stock_name_history`.
- [x] Add `fetch_stock_name_history` backed by Tushare `namechange`.
- [x] Add `_step_stock_name_history`, guarded by `stock_pool.st_history.full_refresh_only`.
- [x] Document the table and operational switch.

### Task 7: Cross-Source Audit

**Files:**
- Modify: `core/data_fetcher.py`
- Modify: `core/data_storage.py`
- Modify: `pipeline.py`
- Test: `tests/test_data_fetcher.py`
- Test: `tests/test_data_storage.py`
- Test: `tests/test_pipeline.py`

- [x] Write failing tests for Tencent vs East Money close-price comparison and audit storage.
- [x] Add `data_source_audit` schema and `upsert_source_audit`.
- [x] Add `compare_market_sources`.
- [x] Add `_step_source_audit`, controlled by `quality.source_audit`.
- [x] Document audit configuration and expected table output.
