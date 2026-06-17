import pandas as pd
import requests

from core.providers.base import normalize_symbol


KLINE_URL = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData"
UA = "Mozilla/5.0"


class SinaKlineClient:
    """Sina daily K-line client for lightweight source auditing."""

    def __init__(self, session=None):
        self.session = session or self._build_session()

    @staticmethod
    def _build_session():
        session = requests.Session()
        session.trust_env = False
        return session

    def fetch_daily_kline(self, code: str, start: str, end: str) -> pd.DataFrame:
        symbol = normalize_symbol(code)
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        datalen = max(10, len(pd.bdate_range(start_ts, end_ts)) + 10)
        resp = self.session.get(
            KLINE_URL,
            params={
                "symbol": f"{symbol.tencent_prefix}{symbol.symbol}",
                "scale": "240",
                "ma": "no",
                "datalen": str(datalen),
            },
            headers={"User-Agent": UA},
            timeout=15,
        )
        if resp.status_code != 200:
            return pd.DataFrame()
        rows = resp.json()
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).rename(
            columns={"day": "trade_date", "volume": "vol"}
        )
        for col in ["open", "high", "low", "close", "vol"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df[
            (df["trade_date"] >= start_ts) & (df["trade_date"] <= end_ts)
        ].copy()
        df["ts_code"] = symbol.ts_code
        df["amount"] = float("nan")
        return df.sort_values("trade_date").reset_index(drop=True)

