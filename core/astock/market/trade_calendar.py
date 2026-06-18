"""Tencent-derived A-share trading calendar."""

from __future__ import annotations

import pandas as pd
import requests


URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
CALENDAR_COLUMNS = [
    "exchange",
    "trade_date",
    "is_open",
    "pretrade_date",
    "source",
]


def _business_day_fallback(year: int) -> pd.DataFrame:
    dates = pd.bdate_range(f"{year}-01-01", f"{year}-12-31")
    df = pd.DataFrame({
        "exchange": "SSE",
        "trade_date": dates,
        "is_open": 1,
        "source": "business_day_fallback",
    })
    df["pretrade_date"] = df["trade_date"].shift(1)
    return df[CALENDAR_COLUMNS]


class TencentTradeCalendarClient:
    """Build an A-share open-day calendar from Tencent index daily bars."""

    def __init__(self, session=None, index_code: str = "sh000001"):
        self.session = session or requests.Session()
        self.index_code = index_code

    def fetch_trade_calendar(self, year: int) -> pd.DataFrame:
        response = self.session.get(
            URL,
            params={"param": f"{self.index_code},day,{year}-01-01,{year}-12-31,400"},
            headers=HEADERS,
            timeout=15,
            proxies={"http": "", "https": ""},
        )
        if response.status_code != 200:
            return _business_day_fallback(year)
        try:
            payload = response.json()
        except ValueError:
            return _business_day_fallback(year)
        if not isinstance(payload, dict) or payload.get("code") != 0:
            return _business_day_fallback(year)

        quote_data = payload.get("data", {}).get(self.index_code, {})
        rows = quote_data.get("day", [])
        if not isinstance(rows, list) or not rows:
            return _business_day_fallback(year)

        dates = []
        for row in rows:
            if not isinstance(row, list) or not row:
                continue
            trade_date = pd.to_datetime(row[0], errors="coerce")
            if pd.isna(trade_date) or trade_date.year != year:
                continue
            dates.append(trade_date)

        if not dates:
            return _business_day_fallback(year)

        df = pd.DataFrame({
            "exchange": "SSE",
            "trade_date": sorted(pd.Series(dates).drop_duplicates()),
            "is_open": 1,
            "source": "tencent_index_kline",
        })
        df["pretrade_date"] = df["trade_date"].shift(1)
        return df[CALENDAR_COLUMNS].reset_index(drop=True)
