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
    """Fetch dragon tiger board detail for a stock on a given date.

    Uses East Money datacenter report RPT_DAILYBILLBOARD_DETAILSNEW.
    """
    symbol = normalize_code(ts_code)
    date_str = str(trade_date).replace("-", "")[:8]
    rows = client.datacenter(
        report_name="RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=(
            f'(SECURITY_CODE="{symbol.symbol}")'
            f'(TRADE_DATE>="{date_str}")'
            f'(TRADE_DATE<="{date_str}")'
        ),
        page_size=50,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    if not rows:
        return pd.DataFrame(columns=DT_COLUMNS)

    data = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        buy_amt = float(r.get("BUY_AMT", 0) or 0)
        sell_amt = float(r.get("SELL_AMT", 0) or 0)
        net_amt = float(r.get("NET_AMT", 0) or 0)
        reason = str(r.get("REASON", ""))
        trade_dt = str(r.get("TRADE_DATE", ""))[:10]
        if not trade_dt:
            continue
        data.append({
            "ts_code": symbol.ts_code,
            "trade_date": pd.Timestamp(trade_dt),
            "buy_amount": buy_amt,
            "sell_amount": sell_amt,
            "net_amount": net_amt,
            "reason": reason,
            "source": "eastmoney_dragon_tiger",
        })
    return pd.DataFrame(data)[DT_COLUMNS].reset_index(drop=True)
