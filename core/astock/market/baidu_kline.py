import pandas as pd
import requests

from core.astock.symbols import normalize_code


URL = "https://finance.pae.baidu.com/selfselect/getstockquotation"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/vnd.finance-web.v1+json",
    "Origin": "https://gushitong.baidu.com",
    "Referer": "https://gushitong.baidu.com/",
}
KLINE_COLUMNS = [
    "ts_code",
    "trade_date",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "ma5",
    "ma10",
    "ma20",
    "source",
]
NUMERIC_COLUMNS = ["open", "close", "high", "low", "vol", "amount", "ma5", "ma10", "ma20"]


def _empty_kline_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=KLINE_COLUMNS)


class BaiduKlineClient:
    """Baidu Gushitong K-line client with MA fields."""

    def __init__(self, session=None):
        self.session = session or requests.Session()

    def fetch_kline_with_ma(self, code: str, start_time: str = "") -> pd.DataFrame:
        symbol = normalize_code(code)
        response = self.session.get(
            URL,
            params={
                "all": "1",
                "isIndex": "false",
                "isBk": "false",
                "isBlock": "false",
                "isFutures": "false",
                "isStock": "true",
                "newFormat": "1",
                "group": "quotation_kline_ab",
                "finClientType": "pc",
                "code": symbol.symbol,
                "start_time": start_time,
                "ktype": "1",
            },
            headers=HEADERS,
            timeout=10,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            return _empty_kline_frame()
        if str(payload.get("ResultCode", -1)) != "0":
            return _empty_kline_frame()
        result = payload.get("Result")
        if not isinstance(result, dict):
            return _empty_kline_frame()
        market_data = result.get("newMarketData")
        if not isinstance(market_data, dict):
            return _empty_kline_frame()
        keys = market_data.get("keys", [])
        market_data_raw = market_data.get("marketData", "")
        if not isinstance(keys, list) or not keys or not isinstance(market_data_raw, str):
            return _empty_kline_frame()
        rows_raw = [row for row in market_data_raw.split(";") if row]
        rows = []
        for raw in rows_raw:
            values = raw.split(",")
            if len(values) < len(keys):
                continue
            item = dict(zip(keys, values))
            rows.append(
                {
                    "ts_code": symbol.ts_code,
                    "trade_date": item.get("time", ""),
                    "open": item.get("open"),
                    "close": item.get("close"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "vol": item.get("volume"),
                    "amount": item.get("amount"),
                    "ma5": item.get("ma5avgprice"),
                    "ma10": item.get("ma10avgprice"),
                    "ma20": item.get("ma20avgprice"),
                    "source": "baidu",
                }
            )
        if not rows:
            return _empty_kline_frame()
        df = pd.DataFrame(rows, columns=KLINE_COLUMNS)
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["trade_date"])
        if df.empty:
            return _empty_kline_frame()
        for col in NUMERIC_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.sort_values("trade_date").reset_index(drop=True)
