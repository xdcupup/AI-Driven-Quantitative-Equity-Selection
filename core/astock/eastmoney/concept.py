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
    """Fetch all concept boards a stock belongs to."""
    return pd.DataFrame(columns=CONCEPT_COLUMNS)


def fetch_concept_stocks(
    client: EastMoneyDataClient,
    concept_code: str,
) -> pd.DataFrame:
    """Fetch all stocks in a concept board."""
    return pd.DataFrame(columns=CONCEPT_STOCK_COLUMNS)
