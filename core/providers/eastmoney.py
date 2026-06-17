import requests

from core.providers.base import normalize_symbol
from core.providers.rate_limit import EastMoneyLimiter


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


class EastMoneyClient:
    """Low-level East Money HTTP client with serial rate limiting."""

    def __init__(
        self,
        session: requests.Session | None = None,
        limiter: EastMoneyLimiter | None = None,
    ):
        self.session = session or requests.Session()
        self.limiter = limiter or EastMoneyLimiter()

    def get_kline(
        self,
        code: str,
        start: str,
        end: str,
        adjust: str = "none",
        timeout: int = 20,
    ):
        self.limiter.wait()
        symbol = normalize_symbol(code)
        adjust_map = {"none": "0", "qfq": "1", "hfq": "2"}
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": "101",
            "fqt": adjust_map.get(adjust, "0"),
            "secid": f"{symbol.eastmoney_market}.{symbol.symbol}",
            "beg": start,
            "end": end,
        }
        headers = {
            "User-Agent": UA,
            "Referer": "https://quote.eastmoney.com/",
            "Origin": "https://quote.eastmoney.com",
        }
        return self.session.get(
            KLINE_URL,
            params=params,
            headers=headers,
            timeout=timeout,
        )

