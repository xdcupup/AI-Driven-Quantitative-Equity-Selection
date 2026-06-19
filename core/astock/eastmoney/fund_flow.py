"""East Money individual stock fund flow data source."""

from __future__ import annotations

import pandas as pd

from core.astock.eastmoney.client import EastMoneyDataClient
from core.astock.symbols import normalize_code

FF_COLUMNS = [
    "ts_code", "trade_date",
    "main_net_amt", "main_net_ratio",
    "huge_net_amt", "big_net_amt",
    "mid_net_amt", "small_net_amt",
    "ddx", "ddy",
    "source",
]


def fetch_stock_fund_flow(
    client: EastMoneyDataClient,
    ts_code: str,
    trade_date: str,
) -> pd.DataFrame:
    """Fetch daily fund flow for a stock.

    Uses East Money datacenter report RPT_DMSK_FN_INDEXCP.
    """
    symbol = normalize_code(ts_code)
    date_str = str(trade_date).replace("-", "")[:8]
    rows = client.datacenter(
        report_name="RPT_DMSK_FN_INDEXCP",
        filter_str=(
            f'(SECURITY_CODE="{symbol.symbol}")'
            f'(TRADE_DATE>="{date_str}")'
            f'(TRADE_DATE<="{date_str}")'
        ),
        page_size=10,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    if not rows:
        return pd.DataFrame(columns=FF_COLUMNS)

    data = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        trade_dt = str(r.get("TRADE_DATE", ""))[:10]
        if not trade_dt:
            continue
        data.append({
            "ts_code": symbol.ts_code,
            "trade_date": pd.Timestamp(trade_dt),
            "main_net_amt": float(r.get("MAIN_NET_AMT", 0) or 0),
            "main_net_ratio": float(r.get("MAIN_NET_RATIO", 0) or 0),
            "huge_net_amt": float(r.get("HUGE_NET_AMT", 0) or 0),
            "big_net_amt": float(r.get("BIG_NET_AMT", 0) or 0),
            "mid_net_amt": float(r.get("MID_NET_AMT", 0) or 0),
            "small_net_amt": float(r.get("SMALL_NET_AMT", 0) or 0),
            "ddx": float(r.get("DDX", 0) or 0),
            "ddy": float(r.get("DDY", 0) or 0),
            "source": "eastmoney_fund_flow",
        })
    return pd.DataFrame(data)[FF_COLUMNS].reset_index(drop=True)
