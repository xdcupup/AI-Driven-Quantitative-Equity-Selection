"""East Money concept board and stock-concept mapping."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.astock.eastmoney.client import EastMoneyDataClient
from core.astock.symbols import normalize_code

CONCEPT_COLUMNS = ["ts_code", "concept_code", "concept_name", "source"]
CONCEPT_STOCK_COLUMNS = ["concept_code", "concept_name", "ts_code", "ts_name", "source"]


def fetch_stock_concepts(
    client: EastMoneyDataClient,
    ts_code: str,
) -> pd.DataFrame:
    """Fetch all concept boards a stock belongs to.

    Uses East Money datacenter report RPT_PC_BOARDCP.
    Returns DataFrame with columns: ts_code, concept_code, concept_name, source
    """
    symbol = normalize_code(ts_code)
    rows = client.datacenter(
        report_name="RPT_PC_BOARDCP",
        filter_str=f'(SECURITY_CODE="{symbol.symbol}")',
        page_size=100,
        sort_columns="BOARD_CODE",
        sort_types="1",
    )
    if not rows:
        return pd.DataFrame(columns=CONCEPT_COLUMNS)
    data = [
        {
            "ts_code": symbol.ts_code,
            "concept_code": str(r.get("BOARD_CODE", "")),
            "concept_name": str(r.get("BOARD_NAME", "")),
            "source": "eastmoney_concept",
        }
        for r in rows
        if r.get("BOARD_CODE") and r.get("BOARD_NAME")
    ]
    return pd.DataFrame(data)[CONCEPT_COLUMNS].drop_duplicates(
        subset=["ts_code", "concept_code"]
    ).reset_index(drop=True)


def fetch_concept_stocks(
    client: EastMoneyDataClient,
    concept_code: str,
) -> pd.DataFrame:
    """Fetch all stocks in a concept board.

    Returns DataFrame with columns: concept_code, concept_name, ts_code, ts_name, source
    """
    rows = client.datacenter(
        report_name="RPT_PC_BOARDCP",
        filter_str=f'(BOARD_CODE="{concept_code}")',
        page_size=500,
        sort_columns="SECURITY_CODE",
        sort_types="1",
    )
    if not rows:
        return pd.DataFrame(columns=CONCEPT_STOCK_COLUMNS)
    data = [
        {
            "concept_code": concept_code,
            "concept_name": str(r.get("BOARD_NAME", "")),
            "ts_code": normalize_code(str(r.get("SECURITY_CODE", ""))).ts_code,
            "ts_name": str(r.get("SECURITY_NAME_ABBR", "")),
            "source": "eastmoney_concept",
        }
        for r in rows
        if r.get("SECURITY_CODE")
    ]
    return pd.DataFrame(data)[CONCEPT_STOCK_COLUMNS].reset_index(drop=True)
