from dataclasses import dataclass


@dataclass(frozen=True)
class AStockSymbol:
    symbol: str
    exchange_suffix: str

    @property
    def ts_code(self) -> str:
        return f"{self.symbol}.{self.exchange_suffix}"

    @property
    def http_prefix(self) -> str:
        if self.exchange_suffix == "SH":
            return "sh"
        if self.exchange_suffix == "BJ":
            return "bj"
        return "sz"

    @property
    def tencent_code(self) -> str:
        return f"{self.http_prefix}{self.symbol}"

    @property
    def mootdx_market(self) -> int:
        return 1 if self.exchange_suffix == "SH" else 0

    @property
    def supports_mootdx_stage_one(self) -> bool:
        return self.exchange_suffix in {"SH", "SZ"}


def normalize_code(code: str) -> AStockSymbol:
    raw = str(code).strip().upper()
    if "." in raw:
        symbol, suffix = raw.split(".", 1)
    elif raw.startswith(("SH", "SZ", "BJ")):
        suffix = raw[:2]
        symbol = raw[2:]
    else:
        symbol = raw
        if symbol.startswith(("6", "9")):
            suffix = "SH"
        elif symbol.startswith(("8", "4")):
            suffix = "BJ"
        else:
            suffix = "SZ"

    return AStockSymbol(symbol=symbol.zfill(6), exchange_suffix=suffix)
