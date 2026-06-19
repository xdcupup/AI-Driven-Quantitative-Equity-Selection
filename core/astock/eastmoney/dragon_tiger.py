"""East Money dragon tiger board data source."""

from __future__ import annotations

import pandas as pd

from core.astock.eastmoney.client import EastMoneyDataClient
from core.astock.symbols import normalize_code

DT_COLUMNS = [
    "ts_code", "trade_date", "buy_amount", "sell_amount",
    "net_amount", "reason", "source",
]


def fetch_dragon_tiger(
    client: EastMoneyDataClient,
    ts_code: str,
    trade_date: str,
) -> pd.DataFrame:
    """Fetch dragon tiger board detail for a stock on a given date."""
    return pd.DataFrame(columns=DT_COLUMNS)
