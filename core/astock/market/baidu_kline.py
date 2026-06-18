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
        if str(payload.get("ResultCode", -1)) != "0":
            return pd.DataFrame()
        market_data = payload.get("Result", {}).get("newMarketData", {})
        keys = market_data.get("keys", [])
        rows_raw = [row for row in market_data.get("marketData", "").split(";") if row]
        rows = []
        for raw in rows_raw:
            values = raw.split(",")
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
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        for col in ["open", "close", "high", "low", "vol", "amount", "ma5", "ma10", "ma20"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.sort_values("trade_date").reset_index(drop=True)
