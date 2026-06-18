"""mootdx finance snapshot adapter."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from core.astock.symbols import normalize_code


FINANCIAL_COLUMNS = [
    "ts_code",
    "ann_date",
    "end_date",
    "eps",
    "bps",
    "roe",
    "roe_waa",
    "profit_yoy",
    "revenue_yoy",
    "free_cashflow",
    "gross_margin",
    "net_margin",
    "dt_debt_ratio",
    "source",
]


def _empty_financial_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=FINANCIAL_COLUMNS)


def _safe_ratio(numerator, denominator) -> float:
    try:
        numerator = float(numerator)
        denominator = float(denominator)
    except (TypeError, ValueError):
        return float("nan")
    if denominator == 0:
        return float("nan")
    return numerator / denominator * 100


def _value(row: pd.Series, key: str) -> float:
    value = row.get(key, float("nan"))
    return pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]


class MootdxFinanceClient:
    """Normalize mootdx latest finance snapshot to the pipeline schema."""

    def __init__(self, quotes=None):
        self.quotes = quotes

    def _get_quotes(self):
        if self.quotes is None:
            from mootdx.quotes import Quotes

            self.quotes = Quotes.factory(market="std")
        return self.quotes

    def fetch_financial_indicators(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        symbol = normalize_code(ts_code)
        if not symbol.supports_mootdx_stage_one:
            return _empty_financial_frame()
        try:
            raw = self._get_quotes().finance(symbol.symbol)
        except Exception as exc:
            logger.warning(f"mootdx 财务快照获取失败 {symbol.ts_code}: {exc}")
            return _empty_financial_frame()
        if raw is None or raw.empty:
            return _empty_financial_frame()

        row = raw.iloc[0]
        ann_date = pd.to_datetime(
            str(row.get("updated_date", "")),
            format="%Y%m%d",
            errors="coerce",
        )
        if pd.isna(ann_date):
            return _empty_financial_frame()
        start_ts = pd.Timestamp(str(start_date).replace("-", ""))
        end_ts = pd.Timestamp(str(end_date).replace("-", ""))
        if ann_date < start_ts or ann_date > end_ts:
            return _empty_financial_frame()

        zongguben = _value(row, "zongguben")
        jinglirun = _value(row, "jinglirun")
        jingzichan = _value(row, "jingzichan")
        zhuyingshouru = _value(row, "zhuyingshouru")
        zongzichan = _value(row, "zongzichan")
        result = pd.DataFrame([{
            "ts_code": symbol.ts_code,
            "ann_date": ann_date,
            "end_date": ann_date,
            "eps": jinglirun / zongguben if zongguben else float("nan"),
            "bps": _value(row, "meigujingzichan"),
            "roe": _safe_ratio(jinglirun, jingzichan),
            "roe_waa": float("nan"),
            "profit_yoy": float("nan"),
            "revenue_yoy": float("nan"),
            "free_cashflow": _value(row, "jingyingxianjinliu"),
            "gross_margin": _safe_ratio(
                _value(row, "zhuyinglirun"), zhuyingshouru
            ),
            "net_margin": _safe_ratio(jinglirun, zhuyingshouru),
            "dt_debt_ratio": _safe_ratio(zongzichan - jingzichan, zongzichan),
            "source": "mootdx_finance",
        }])
        return result[FINANCIAL_COLUMNS]
