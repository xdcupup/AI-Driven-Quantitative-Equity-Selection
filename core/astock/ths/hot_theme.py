"""THS (同花顺) hot theme / concept board data source."""

from __future__ import annotations

from typing import Any
from datetime import datetime

import pandas as pd
import requests

from core.astock.symbols import normalize_code

THS_HOT_LIST_URL = "https://d.10jqka.com.cn/v2/plate/hot_rank/list"
THS_HOT_DETAIL_URL = "https://d.10jqka.com.cn/v2/plate/hot_rank/detail"

THEME_COLUMNS = [
    "theme_code", "theme_name", "rank", "heat_score",
    "pct_chg", "leading_stock", "stock_count", "trade_date", "source",
]
THEME_STOCK_COLUMNS = [
    "theme_code", "theme_name", "ts_code", "ts_name",
    "pct_chg", "reason", "trade_date", "source",
]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://www.10jqka.com.cn/",
}


def fetch_hot_themes(trade_date: str | None = None) -> pd.DataFrame:
    """Fetch ranked hot theme list from THS."""
    trade_date = trade_date or datetime.now().strftime("%Y%m%d")
    try:
        resp = requests.get(
            THS_HOT_LIST_URL,
            headers=DEFAULT_HEADERS,
            params={"date": trade_date},
            timeout=10,
        )
        payload = resp.json()
    except (ValueError, requests.RequestException):
        return pd.DataFrame(columns=THEME_COLUMNS)

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return pd.DataFrame(columns=THEME_COLUMNS)

    rows = [
        {
            "theme_code": str(r.get("plate_id", "")),
            "theme_name": str(r.get("plate_name", "")),
            "rank": int(r.get("rank", 0)),
            "heat_score": float(r.get("hot_num", 0)),
            "pct_chg": float(r.get("pct_chg", 0)),
            "leading_stock": str(r.get("lead_stock_name", "")),
            "stock_count": int(r.get("stock_count", 0)),
            "trade_date": pd.Timestamp(trade_date),
            "source": "ths_hot_theme",
        }
        for r in data
        if isinstance(r, dict) and r.get("plate_id")
    ]
    return pd.DataFrame(rows)[THEME_COLUMNS].reset_index(drop=True)


def fetch_theme_stocks(
    theme_code: str,
    trade_date: str | None = None,
) -> pd.DataFrame:
    """Fetch constituent stocks for a THS hot theme."""
    trade_date = trade_date or datetime.now().strftime("%Y%m%d")
    try:
        resp = requests.get(
            THS_HOT_DETAIL_URL,
            headers=DEFAULT_HEADERS,
            params={"plate_id": theme_code, "date": trade_date},
            timeout=10,
        )
        payload = resp.json()
    except (ValueError, requests.RequestException):
        return pd.DataFrame(columns=THEME_STOCK_COLUMNS)

    result = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return pd.DataFrame(columns=THEME_STOCK_COLUMNS)

    stocks = result.get("stocks") if isinstance(result, dict) else result.get("data")
    if not isinstance(stocks, list):
        return pd.DataFrame(columns=THEME_STOCK_COLUMNS)

    theme_name = str(result.get("plate_name", ""))
    rows = [
        {
            "theme_code": theme_code,
            "theme_name": theme_name,
            "ts_code": normalize_code(str(s.get("code", ""))).ts_code,
            "ts_name": str(s.get("name", "")),
            "pct_chg": float(s.get("pct_chg", 0)),
            "reason": str(s.get("reason", "")),
            "trade_date": pd.Timestamp(trade_date),
            "source": "ths_hot_theme",
        }
        for s in stocks
        if isinstance(s, dict) and s.get("code")
    ]
    return pd.DataFrame(rows)[THEME_STOCK_COLUMNS].reset_index(drop=True)
