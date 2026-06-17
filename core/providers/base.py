from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarketSymbol:
    """Normalized A-share symbol metadata."""

    symbol: str
    exchange_suffix: str
    eastmoney_market: str
    tencent_prefix: str

    @property
    def ts_code(self) -> str:
        return f"{self.symbol}.{self.exchange_suffix}"


@dataclass
class ProviderResult:
    """Small provider response envelope for collector-level diagnostics."""

    source: str
    ok: bool
    data: Any = None
    error: str | None = None


def normalize_symbol(code: str) -> MarketSymbol:
    """Normalize common stock code formats to six-digit A-share metadata."""
    raw = str(code).strip().upper()
    if "." in raw:
        symbol, suffix = raw.split(".", 1)
    elif raw.startswith(("SH", "SZ", "BJ")):
        suffix = raw[:2]
        symbol = raw[2:]
    else:
        symbol = raw
        if symbol.startswith("6"):
            suffix = "SH"
        elif symbol.startswith(("4", "8", "9")):
            suffix = "BJ"
        else:
            suffix = "SZ"

    symbol = symbol.zfill(6)
    if suffix == "SH":
        eastmoney_market = "1"
        tencent_prefix = "sh"
    elif suffix == "BJ":
        eastmoney_market = "0"
        tencent_prefix = "bj"
    else:
        eastmoney_market = "0"
        tencent_prefix = "sz"

    return MarketSymbol(
        symbol=symbol,
        exchange_suffix=suffix,
        eastmoney_market=eastmoney_market,
        tencent_prefix=tencent_prefix,
    )

