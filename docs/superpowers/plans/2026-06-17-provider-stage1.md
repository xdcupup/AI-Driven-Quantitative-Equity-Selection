# Provider Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first refactor slice for the seven-layer data platform by introducing provider boundaries and a reusable East Money rate limiter without changing existing pipeline behavior.

**Architecture:** Keep `DataFetcher` as the compatibility facade. Add focused modules under `core/providers/` for shared provider utilities, then gradually route existing fetcher internals through those modules. Stage 1 only extracts safe infrastructure and one East Money request path.

**Tech Stack:** Python 3.11, pandas, requests, unittest, DuckDB pipeline unchanged.

---

### Task 1: Provider Package Skeleton

**Files:**
- Create: `core/providers/__init__.py`
- Create: `core/providers/base.py`
- Test: `tests/test_providers.py`

- [x] Write tests for ticker normalization and provider response contracts.
- [x] Implement `MarketSymbol`, `normalize_symbol`, and `ProviderResult`.
- [x] Run provider tests.

### Task 2: East Money Limiter

**Files:**
- Create: `core/providers/rate_limit.py`
- Create: `core/providers/eastmoney.py`
- Test: `tests/test_providers.py`

- [x] Write tests that East Money requests sleep when called too quickly and reuse request headers.
- [x] Implement `EastMoneyLimiter` and `EastMoneyClient`.
- [x] Run provider tests.

### Task 3: DataFetcher Integration

**Files:**
- Modify: `core/data_fetcher.py`
- Test: `tests/test_data_fetcher.py`

- [x] Write a test that `DataFetcher` creates an East Money client with config interval.
- [x] Route `_fetch_kline_eastmoney_curl` through the client URL builder while preserving current parsing.
- [x] Run all tests and compile checks.
