from collections.abc import Callable
import urllib.request

import pandas as pd

from core.astock.symbols import normalize_code


UA = "Mozilla/5.0"


def _to_float(value: str) -> float:
    try:
        return float(value) if value not in ("", "-") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _value_at(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


class TencentQuoteClient:
    """Tencent quote API client for realtime quote and valuation fields."""

    def __init__(self, opener: Callable[[str], bytes] | None = None):
        self.opener = opener or self._open_url

    @staticmethod
    def _open_url(url: str) -> bytes:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()

    def fetch_quotes(self, codes: list[str]) -> pd.DataFrame:
        symbols = [normalize_code(code) for code in codes]
        url = "https://qt.gtimg.cn/q=" + ",".join(s.tencent_code for s in symbols)
        text = self.opener(url).decode("gbk")
        rows = []
        for line in text.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            values = line.split('"')[1].split("~")
            if len(values) < 51:
                continue
            symbol = normalize_code(key[2:])
            rows.append({
                "ts_code": symbol.ts_code,
                "symbol": symbol.symbol,
                "name": values[1],
                "price": _to_float(values[3]),
                "last_close": _to_float(values[4]),
                "open": _to_float(values[5]),
                "change_amt": _to_float(values[31]),
                "change_pct": _to_float(values[32]),
                "high": _to_float(values[33]),
                "low": _to_float(values[34]),
                "amount": _to_float(values[37]) * 10000,
                "turnover_rate": _to_float(values[38]),
                "pe_ttm": _to_float(values[39]),
                "amplitude_pct": _to_float(values[43]),
                "total_mv": _to_float(values[44]) * 100000000,
                "circ_mv": _to_float(values[45]) * 100000000,
                "pb": _to_float(values[46]),
                "limit_up": _to_float(values[47]),
                "limit_down": _to_float(values[48]),
                "volume_ratio": _to_float(values[49]),
                "pe_static": _to_float(_value_at(values, 52)),
                "source": "tencent",
            })
        return pd.DataFrame(rows)
