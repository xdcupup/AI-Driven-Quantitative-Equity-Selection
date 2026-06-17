import pandas as pd
import requests

from core.providers.base import normalize_symbol


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class TencentKlineClient:
    """Tencent Finance daily K-line client."""

    def __init__(self, session=None):
        self.session = session or requests

    def fetch_daily_kline(
        self, code: str, start: str, end: str, adjust: str = "none"
    ) -> pd.DataFrame:
        symbol = normalize_symbol(code)
        if symbol.exchange_suffix not in {"SZ", "SH"}:
            return pd.DataFrame()

        adjust_map = {
            "none": ("", "day"),
            "qfq": ("qfq", "qfqday"),
            "hfq": ("hfq", "hfqday"),
        }
        fq_param, response_key = adjust_map.get(adjust, adjust_map["none"])
        param = f"{symbol.tencent_prefix}{symbol.symbol},day,,,2000"
        if fq_param:
            param = f"{param},{fq_param}"
            endpoint = "fqkline/get"
        else:
            endpoint = "kline/kline"

        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/"
            f"{endpoint}?param={param}"
        )
        resp = self.session.get(
            url,
            headers={"User-Agent": UA, "Referer": "https://gu.qq.com/"},
            timeout=15,
            proxies={"http": "", "https": ""},
        )
        if resp.status_code != 200:
            return pd.DataFrame()

        data = resp.json()
        if data.get("code") != 0:
            return pd.DataFrame()

        quote_key = f"{symbol.tencent_prefix}{symbol.symbol}"
        quote_data = data.get("data", {}).get(quote_key, {})
        kline_raw = quote_data.get(response_key, [])
        if not kline_raw:
            return pd.DataFrame()

        rows = []
        for item in kline_raw:
            if len(item) < 6:
                continue
            rows.append({
                "trade_date": item[0],
                "open": float(item[1]),
                "close": float(item[2]),
                "high": float(item[3]),
                "low": float(item[4]),
                "vol": float(item[5]) * 100,
            })
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values("trade_date").reset_index(drop=True)
        df["pct_chg"] = df["close"].pct_change() * 100
        df["ts_code"] = symbol.ts_code
        df["amount"] = float("nan")
        df["adj_factor"] = float("nan")
        df["price_type"] = adjust
        df["flag_extreme"] = False
        df["flag_suspended"] = False

        if adjust == "none":
            for col in ["open", "high", "low", "close"]:
                df[f"raw_{col}"] = df[col]

        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)
        df = df[(df["trade_date"] >= start_dt) & (df["trade_date"] <= end_dt)]
        return df.reset_index(drop=True)

