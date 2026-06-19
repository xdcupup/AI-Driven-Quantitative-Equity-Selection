import pandas as pd

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
    "source",
]
NUMERIC_COLUMNS = ["open", "high", "low", "close", "vol", "amount"]


def _empty_kline_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=KLINE_COLUMNS)


class MootdxMarketClient:
    """mootdx market adapter with injectable quote client for tests."""

    def __init__(self, quotes=None):
        self.quotes = quotes

    def _get_quotes(self):
        if self.quotes is None:
            from mootdx.quotes import Quotes

            self.quotes = Quotes.factory(market="std")
        return self.quotes

    def fetch_daily_kline(
        self, code: str, start: str, end: str, offset: int = 1200
    ) -> pd.DataFrame:
        symbol = normalize_code(code)
        if not symbol.supports_mootdx_stage_one:
            return _empty_kline_frame()

        df = self._get_quotes().bars(
            symbol=symbol.symbol,
            market=symbol.mootdx_market,
            category=4,
            offset=offset,
        )
        if df is None or df.empty:
            return _empty_kline_frame()

        result = df.rename(columns={"datetime": "trade_date"}).copy()
        if "trade_date" not in result.columns:
            return _empty_kline_frame()

        normalized_dates = (
            result["trade_date"]
            .astype(str)
            .str.slice(0, 10)
            .str.replace("-", "", regex=False)
        )
        result["trade_date"] = pd.to_datetime(
            normalized_dates, format="%Y%m%d", errors="coerce"
        )
        result = result.dropna(subset=["trade_date"])
        if result.empty:
            return _empty_kline_frame()

        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        result = result[
            (result["trade_date"] >= start_ts) & (result["trade_date"] <= end_ts)
        ].copy()
        if result.empty:
            return _empty_kline_frame()

        result["ts_code"] = symbol.ts_code
        result["source"] = "mootdx"
        for col in NUMERIC_COLUMNS:
            if col in result.columns:
                result[col] = pd.to_numeric(result[col], errors="coerce")
            else:
                result[col] = float("nan")
        return result[KLINE_COLUMNS].sort_values("trade_date").reset_index(drop=True)
