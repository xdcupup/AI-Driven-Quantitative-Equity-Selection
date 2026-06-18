"""mootdx-backed A-share stock list adapter."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from core.astock.symbols import normalize_code


STOCK_LIST_COLUMNS = [
    "ts_code",
    "symbol",
    "name",
    "exchange",
    "area",
    "industry",
    "list_status",
    "list_date",
    "delist_date",
    "source",
]


def _empty_stock_list() -> pd.DataFrame:
    return pd.DataFrame(columns=STOCK_LIST_COLUMNS)


def _is_a_share_code(code: str) -> bool:
    if len(code) != 6 or not code.isdigit():
        return False
    return code.startswith((
        "000",
        "001",
        "002",
        "003",
        "300",
        "301",
        "600",
        "601",
        "603",
        "605",
        "688",
    ))


def _clean_name(value) -> str:
    return str(value).replace("\x00", "").strip()


def _is_non_stock_name(name: str) -> bool:
    blocked_tokens = ["指数", "债", "基金", "ETF", "ＥＴＦ", "B股", "Ｂ股"]
    return any(token in name for token in blocked_tokens)


class MootdxStockListClient:
    """Fetch and normalize Shenzhen/Shanghai A-share stock lists from mootdx."""

    def __init__(self, quotes=None):
        self.quotes = quotes

    def _get_quotes(self):
        if self.quotes is None:
            from mootdx.quotes import Quotes

            self.quotes = Quotes.factory(market="std")
        return self.quotes

    def fetch_stock_list(self) -> pd.DataFrame:
        try:
            raw = self._fetch_raw()
        except Exception as exc:
            logger.warning(f"mootdx 股票列表获取失败: {exc}")
            return _empty_stock_list()
        if raw.empty:
            return _empty_stock_list()

        code_col = "code" if "code" in raw.columns else raw.columns[0]
        name_col = "name" if "name" in raw.columns else code_col
        rows = []
        for _, item in raw.iterrows():
            code = str(item[code_col]).strip().zfill(6)
            if not _is_a_share_code(code):
                continue
            name = _clean_name(item.get(name_col, ""))
            if _is_non_stock_name(name):
                continue
            try:
                symbol = normalize_code(code)
            except ValueError:
                continue
            rows.append({
                "ts_code": symbol.ts_code,
                "symbol": symbol.symbol,
                "name": name or symbol.ts_code,
                "exchange": symbol.exchange_suffix,
                "area": None,
                "industry": None,
                "list_status": "L",
                "list_date": pd.NaT,
                "delist_date": pd.NaT,
                "source": "mootdx",
            })

        if not rows:
            return _empty_stock_list()
        result = pd.DataFrame(rows, columns=STOCK_LIST_COLUMNS)
        return (
            result.drop_duplicates("ts_code")
            .sort_values("ts_code")
            .reset_index(drop=True)
        )

    def _fetch_raw(self) -> pd.DataFrame:
        frames = []
        quotes = self._get_quotes()
        for market in [0, 1]:
            stocks = quotes.stocks(market=market)
            if stocks is not None and not stocks.empty:
                frames.append(stocks)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)
