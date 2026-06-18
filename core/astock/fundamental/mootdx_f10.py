"""mootdx F10 company information adapter."""

from __future__ import annotations

from typing import Any

import pandas as pd
from loguru import logger

from core.astock.symbols import normalize_code


F10_CATEGORY_COLUMNS = [
    "ts_code",
    "name",
    "filename",
    "start",
    "length",
    "source",
]


def _empty_categories() -> pd.DataFrame:
    return pd.DataFrame(columns=F10_CATEGORY_COLUMNS)


def _empty_section(ts_code: str, section: str, error: str | None = None) -> dict[str, Any]:
    return {
        "ts_code": ts_code,
        "section": section,
        "content": "",
        "source": "mootdx_f10",
        "error": error,
    }


class MootdxF10Client:
    """Fetch F10 category directory and selected text sections from mootdx."""

    def __init__(self, quotes=None):
        self.quotes = quotes

    def _get_quotes(self):
        if self.quotes is None:
            from mootdx.quotes import Quotes

            self.quotes = Quotes.factory(market="std")
        return self.quotes

    def fetch_categories(self, ts_code: str) -> pd.DataFrame:
        symbol = normalize_code(ts_code)
        if not symbol.supports_mootdx_stage_one:
            return _empty_categories()
        try:
            raw = self._get_quotes().F10C(symbol.symbol)
        except Exception as exc:
            logger.warning(f"mootdx F10目录获取失败 {symbol.ts_code}: {exc}")
            return _empty_categories()
        if not raw:
            return _empty_categories()

        rows = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            rows.append({
                "ts_code": symbol.ts_code,
                "name": name,
                "filename": item.get("filename"),
                "start": item.get("start"),
                "length": item.get("length"),
                "source": "mootdx_f10",
            })
        if not rows:
            return _empty_categories()
        return pd.DataFrame(rows, columns=F10_CATEGORY_COLUMNS)

    def fetch_section(self, ts_code: str, section: str) -> dict[str, Any]:
        symbol = normalize_code(ts_code)
        if not symbol.supports_mootdx_stage_one:
            return _empty_section(symbol.ts_code, section)
        try:
            content = self._get_quotes().F10(symbol.symbol, name=section)
        except Exception as exc:
            logger.warning(f"mootdx F10章节获取失败 {symbol.ts_code}/{section}: {exc}")
            return _empty_section(symbol.ts_code, section, error=str(exc))
        if content is None:
            return _empty_section(symbol.ts_code, section)
        return {
            "ts_code": symbol.ts_code,
            "section": section,
            "content": str(content),
            "source": "mootdx_f10",
            "error": None,
        }
