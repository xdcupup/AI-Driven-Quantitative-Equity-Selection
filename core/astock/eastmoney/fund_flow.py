"""East Money individual stock fund flow data source."""

from __future__ import annotations

import pandas as pd

from core.astock.eastmoney.client import EastMoneyDataClient
from core.astock.symbols import normalize_code


HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

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
    """Fetch daily fund flow for a stock."""
    symbol = normalize_code(ts_code)
    date_str = str(trade_date).replace("-", "")[:8]
    history = _fetch_push2his_flow(client, symbol.ts_code, date_str)
    if not history.empty:
        return history

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


def _fetch_push2his_flow(
    client: EastMoneyDataClient,
    ts_code: str,
    date_str: str,
) -> pd.DataFrame:
    symbol = normalize_code(ts_code)
    secid = f"{1 if symbol.exchange_suffix == 'SH' else 0}.{symbol.symbol}"
    response = client.em_get(
        HISTORY_URL,
        params={
            "lmt": "0",
            "klt": "101",
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        },
        timeout=15,
    )
    try:
        payload = response.json()
    except ValueError:
        return pd.DataFrame(columns=FF_COLUMNS)
    if not isinstance(payload, dict):
        return pd.DataFrame(columns=FF_COLUMNS)
    data = payload.get("data")
    if not isinstance(data, dict):
        return pd.DataFrame(columns=FF_COLUMNS)
    klines = data.get("klines")
    if not isinstance(klines, list):
        return pd.DataFrame(columns=FF_COLUMNS)

    target = pd.Timestamp(date_str)
    rows = []
    for line in klines:
        values = str(line).split(",")
        if len(values) < 11:
            continue
        trade_dt = pd.to_datetime(values[0], errors="coerce")
        if pd.isna(trade_dt) or trade_dt != target:
            continue
        main_ratio = _to_float(values[6])
        rows.append({
            "ts_code": symbol.ts_code,
            "trade_date": trade_dt,
            "main_net_amt": _to_float(values[1]),
            "small_net_amt": _to_float(values[2]),
            "mid_net_amt": _to_float(values[3]),
            "big_net_amt": _to_float(values[4]),
            "huge_net_amt": _to_float(values[5]),
            "main_net_ratio": main_ratio,
            "ddx": main_ratio / 10,
            "ddy": main_ratio / 10,
            "source": "eastmoney_fund_flow",
        })
    if not rows:
        return pd.DataFrame(columns=FF_COLUMNS)
    return pd.DataFrame(rows)[FF_COLUMNS].reset_index(drop=True)


def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
