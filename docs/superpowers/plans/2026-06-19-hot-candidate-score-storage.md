# Hot Candidate Score Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist hot-candidate scoring snapshots in DuckDB and allow the hot-candidate backtest runner to read them directly from the database.

**Architecture:** Add one DuckDB table plus two `QuantDB` methods for score upsert/query. Reuse the existing hot-candidate backtest adapter so CSV mode and DB mode share the same filtering and simulation path.

**Tech Stack:** Python 3.12, pandas, DuckDB, argparse, unittest

---

### Task 1: Persist Hot Candidate Scores

**Files:**
- Modify: `core/data_storage.py`
- Modify: `tests/test_data_storage.py`

- [x] **Step 1: Write the failing storage test**

Add a test that creates scored rows, writes them with `upsert_hot_candidate_scores`, and queries them with `query_hot_candidate_scores`.

- [x] **Step 2: Run the targeted test and verify RED**

Run: `.venv/bin/python -m unittest tests.test_data_storage.QuantDBTest.test_upsert_and_query_hot_candidate_scores -v`

Expected: fail with missing `upsert_hot_candidate_scores`.

- [x] **Step 3: Add schema and QuantDB methods**

Add `hot_candidate_scores` to `SCHEMA_SQL`, then implement `upsert_hot_candidate_scores` and `query_hot_candidate_scores`.

- [x] **Step 4: Run targeted storage test and verify GREEN**

Run: `.venv/bin/python -m unittest tests.test_data_storage.QuantDBTest.test_upsert_and_query_hot_candidate_scores -v`

Expected: pass.

### Task 2: Load Scores From DB In Backtest Runner

**Files:**
- Modify: `scripts/run_hot_candidate_backtest.py`
- Modify: `tests/test_hot_candidate_backtest.py`

- [x] **Step 1: Write failing CLI argument test**

Add a test for mutually exclusive score inputs and for DB score loading behavior through a small helper function.

- [x] **Step 2: Run targeted test and verify RED**

Run: `.venv/bin/python -m unittest tests.test_hot_candidate_backtest -v`

Expected: fail with missing helper/behavior.

- [x] **Step 3: Implement DB input mode**

Add `--from-db`, `--strategy-name`, and mutual exclusion with `--scores-csv`. Query scores via `QuantDB.query_hot_candidate_scores`.

- [x] **Step 4: Run targeted hot-candidate tests and verify GREEN**

Run: `.venv/bin/python -m unittest tests.test_hot_candidate_backtest -v`

Expected: pass.

### Task 3: Docs, Verification, Commit

**Files:**
- Modify: `README.md`

- [x] **Step 1: Update README**

Document `--from-db` usage while keeping the CSV example.

- [x] **Step 2: Run verification**

Run:

```bash
.venv/bin/python -m py_compile scripts/run_hot_candidate_backtest.py core/backtest/hot_candidate.py core/data_storage.py
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all commands exit 0.

- [x] **Step 3: Commit and push**

Commit the implementation and push `refactor/provider-stage1`.
