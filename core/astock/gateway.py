"""Pipeline-facing gateway for the a-stock-data source layer."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.astock.eastmoney.client import EastMoneyDataClient
from core.astock.fundamental.mootdx_f10 import MootdxF10Client
from core.astock.fundamental.mootdx_finance import MootdxFinanceClient
from core.astock.market.baidu_kline import BaiduKlineClient
from core.astock.market.mootdx_client import MootdxMarketClient
from core.astock.market.stock_list import MootdxStockListClient
from core.astock.market.tencent_quote import TencentQuoteClient
from core.astock.market.trade_calendar import TencentTradeCalendarClient
from core.astock.symbols import normalize_code


KLINE_COLUMNS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
    "pct_chg",
    "adj_factor",
    "price_type",
    "source",
    "flag_extreme",
    "flag_suspended",
    "flag_aligned",
    "flag_invalid_ohlc",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
]

DAILY_BASIC_COLUMNS = [
    "ts_code",
    "trade_date",
    "pe",
    "pe_ttm",
    "pb",
    "turnover_rate",
    "volume_ratio",
    "circ_mv",
    "total_mv",
]


def _parse_date(value: str | pd.Timestamp) -> str:
    return str(value).replace("-", "")[:8]


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


class AStockDataGateway:
    """Compatibility facade for the rewritten direct-source A-share layer."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        mootdx_client: MootdxMarketClient | None = None,
        tencent_client: TencentQuoteClient | None = None,
        baidu_client: BaiduKlineClient | None = None,
        eastmoney_client: EastMoneyDataClient | None = None,
        calendar_client: TencentTradeCalendarClient | None = None,
        stock_list_client: MootdxStockListClient | None = None,
        finance_client: MootdxFinanceClient | None = None,
        f10_client: MootdxF10Client | None = None,
    ) -> None:
        self.config = config or {}
        self.mootdx = mootdx_client or MootdxMarketClient()
        self.tencent = tencent_client or TencentQuoteClient()
        self.baidu = baidu_client or BaiduKlineClient()
        self.eastmoney = eastmoney_client or EastMoneyDataClient()
        self.calendar = calendar_client or TencentTradeCalendarClient()
        self.stock_list = stock_list_client or MootdxStockListClient()
        self.finance = finance_client or MootdxFinanceClient()
        self.f10 = f10_client or MootdxF10Client()
        self._tushare_pro = None
        self.supports_daily_basic = True
        self.supports_financial_indicators = True

    def fetch_daily_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjust: str = "none",
    ) -> pd.DataFrame:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        df = self.mootdx.fetch_daily_kline(ts_code, start, end)
        if not df.empty:
            return self._normalize_daily_kline(df)

        fallback = self.baidu.fetch_kline_with_ma(ts_code, start_time=start)
        if fallback.empty:
            return _empty_frame(KLINE_COLUMNS)
        fallback = fallback[
            (fallback["trade_date"] >= pd.Timestamp(start))
            & (fallback["trade_date"] <= pd.Timestamp(end))
        ].copy()
        return self._normalize_daily_kline(fallback)

    def fetch_daily_basic(
        self,
        codes_or_trade_date: list[str] | str,
        trade_date: str | None = None,
    ) -> pd.DataFrame:
        if trade_date is None:
            trade_date = str(codes_or_trade_date)
            codes = self._configured_codes()
        elif isinstance(codes_or_trade_date, str):
            codes = [codes_or_trade_date]
        else:
            codes = list(codes_or_trade_date)

        df = self.tencent.fetch_quotes(codes)
        if df.empty:
            return _empty_frame(DAILY_BASIC_COLUMNS)

        result = df.copy()
        for col in [
            "pe_ttm",
            "pb",
            "turnover_rate",
            "volume_ratio",
            "circ_mv",
            "total_mv",
        ]:
            if col not in result.columns:
                result[col] = float("nan")
            result[col] = pd.to_numeric(result[col], errors="coerce")
        result["trade_date"] = pd.Timestamp(_parse_date(trade_date))
        result["pe"] = result["pe_ttm"]
        return result[DAILY_BASIC_COLUMNS].reset_index(drop=True)

    def fetch_stock_list(self) -> pd.DataFrame:
        configured = self._stock_list_from_config()
        if not configured.empty:
            return configured
        return self.stock_list.fetch_stock_list()

    def fetch_trade_calendar(self, year: int) -> pd.DataFrame:
        return self.calendar.fetch_trade_calendar(year)

    def fetch_adj_factor(self, ts_code: str) -> pd.DataFrame:
        return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])

    def fetch_financial_indicators(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        return self.finance.fetch_financial_indicators(ts_code, start_date, end_date)

    def fetch_stock_name_history(self, ts_code: str) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_f10_categories(self, ts_code: str) -> pd.DataFrame:
        return self.f10.fetch_categories(ts_code)

    def fetch_f10_section(self, ts_code: str, section: str) -> dict[str, Any]:
        return self.f10.fetch_section(ts_code, section)

    def compare_market_sources(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        tolerance_pct: float,
        secondary: str = "baidu",
    ) -> dict[str, Any]:
        primary = self.fetch_daily_kline(ts_code, start_date, end_date)
        if secondary == "baidu":
            secondary_df = self.baidu.fetch_kline_with_ma(ts_code, start_time=start_date)
        else:
            secondary_df = pd.DataFrame()
        return self._compare_close(primary, secondary_df, ts_code, start_date, end_date, tolerance_pct, secondary)

    def _normalize_daily_kline(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return _empty_frame(KLINE_COLUMNS)

        result = df.copy()
        result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
        result = result.dropna(subset=["trade_date"])
        if result.empty:
            return _empty_frame(KLINE_COLUMNS)

        result = result.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        for col in ["open", "high", "low", "close", "vol", "amount"]:
            if col not in result.columns:
                result[col] = float("nan")
            result[col] = pd.to_numeric(result[col], errors="coerce")
        if "pct_chg" not in result.columns:
            result["pct_chg"] = result.groupby("ts_code")["close"].pct_change() * 100
        result["adj_factor"] = float("nan")
        result["price_type"] = "none"
        for col in ["flag_extreme", "flag_suspended", "flag_aligned", "flag_invalid_ohlc"]:
            result[col] = False
        for col in ["open", "high", "low", "close"]:
            result[f"raw_{col}"] = result[col]
        for col in KLINE_COLUMNS:
            if col not in result.columns:
                result[col] = None
        return result[KLINE_COLUMNS]

    def _configured_codes(self) -> list[str]:
        pool = self.config.get("stock_pool", {})
        codes = pool.get("codes") or pool.get("symbols") or []
        return [normalize_code(code).ts_code for code in codes]

    def _stock_list_from_config(self) -> pd.DataFrame:
        rows = []
        for code in self._configured_codes():
            symbol = normalize_code(code)
            rows.append({
                "ts_code": symbol.ts_code,
                "symbol": symbol.symbol,
                "name": symbol.ts_code,
                "exchange": symbol.exchange_suffix,
                "area": None,
                "industry": None,
                "list_status": "L",
                "list_date": pd.NaT,
                "delist_date": pd.NaT,
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    def _compare_close(
        self,
        primary: pd.DataFrame,
        secondary_df: pd.DataFrame,
        ts_code: str,
        start_date: str,
        end_date: str,
        tolerance_pct: float,
        secondary: str,
    ) -> dict[str, Any]:
        row = {
            "audit_date": pd.Timestamp.today().normalize(),
            "ts_code": ts_code,
            "start_date": pd.Timestamp(_parse_date(start_date)),
            "end_date": pd.Timestamp(_parse_date(end_date)),
            "primary_source": "astock",
            "secondary_source": secondary,
            "compared_rows": 0,
            "max_close_diff_pct": None,
            "status": "failed",
            "error_msg": None,
        }
        if primary.empty or secondary_df.empty:
            row["error_msg"] = "empty comparison source"
            return row
        merged = primary[["trade_date", "close"]].merge(
            secondary_df[["trade_date", "close"]],
            on="trade_date",
            suffixes=("_primary", "_secondary"),
        )
        if merged.empty:
            row["error_msg"] = "no overlapping dates"
            return row
        diff = (
            (merged["close_primary"] - merged["close_secondary"]).abs()
            / merged["close_primary"].replace(0, pd.NA).abs()
            * 100
        )
        max_diff = float(diff.max())
        row["compared_rows"] = len(merged)
        row["max_close_diff_pct"] = max_diff
        row["status"] = "warning" if max_diff > tolerance_pct else "normal"
        return row
