"""Sina financial statement adapter."""

from __future__ import annotations

from typing import Any

import pandas as pd
import requests
from loguru import logger

from core.astock.symbols import normalize_code


SINA_FINANCE_URL = (
    "https://quotes.sina.cn/cn/api/openapi.php/"
    "CompanyFinanceService.getFinanceReport2022"
)
UA = "Mozilla/5.0"

STATEMENT_COLUMNS = [
    "ts_code",
    "report_type",
    "end_date",
    "ann_date",
    "item_order",
    "item",
    "value",
    "item_yoy",
    "source",
]

STATEMENT_SOURCE_ALIASES = {
    "balance_sheet": "fzb",
    "fzb": "fzb",
    "income_statement": "lrb",
    "income": "lrb",
    "lrb": "lrb",
    "cash_flow": "llb",
    "cashflow": "llb",
    "llb": "llb",
}

CANONICAL_TYPES = {
    "fzb": "balance_sheet",
    "lrb": "income_statement",
    "llb": "cash_flow",
}


def _empty_statement_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STATEMENT_COLUMNS)


def _parse_number_or_text(value: Any) -> Any:
    if value in (None, ""):
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(parsed):
        return float(parsed)
    return value


class SinaFinancialStatementClient:
    """Fetch balance sheet, income statement and cash-flow rows from Sina."""

    def __init__(self, session=None):
        self.session = session or self._build_session()

    @staticmethod
    def _build_session():
        session = requests.Session()
        session.trust_env = False
        return session

    def fetch_statement(
        self,
        ts_code: str,
        statement_type: str,
        start_date: str,
        end_date: str,
        num: int = 80,
    ) -> pd.DataFrame:
        symbol = normalize_code(ts_code)
        source_type = self._source_type(statement_type)
        if source_type is None:
            logger.warning(f"未知新浪财报类型: {statement_type}")
            return _empty_statement_frame()

        try:
            response = self.session.get(
                SINA_FINANCE_URL,
                params={
                    "paperCode": f"{symbol.http_prefix}{symbol.symbol}",
                    "source": source_type,
                    "type": "0",
                    "page": "1",
                    "num": str(num),
                },
                headers={"User-Agent": UA},
                timeout=15,
            )
            if getattr(response, "status_code", 200) != 200:
                return _empty_statement_frame()
            payload = response.json()
        except Exception as exc:
            logger.warning(f"新浪财报获取失败 {symbol.ts_code}/{statement_type}: {exc}")
            return _empty_statement_frame()

        report_list = (
            payload.get("result", {})
            .get("data", {})
            .get("report_list", {})
            or {}
        )
        if not isinstance(report_list, dict):
            return _empty_statement_frame()
        rows = self._parse_report_list(
            symbol.ts_code,
            CANONICAL_TYPES[source_type],
            report_list,
        )
        if not rows:
            return _empty_statement_frame()

        result = pd.DataFrame(rows, columns=STATEMENT_COLUMNS)
        result["end_date"] = pd.to_datetime(result["end_date"], errors="coerce")
        result["ann_date"] = pd.to_datetime(result["ann_date"], errors="coerce")
        start = pd.Timestamp(str(start_date).replace("-", "")[:8])
        end = pd.Timestamp(str(end_date).replace("-", "")[:8])
        result = result[
            (result["end_date"] >= start) & (result["end_date"] <= end)
        ].copy()
        if result.empty:
            return _empty_statement_frame()
        return result.sort_values(["end_date", "item"]).reset_index(drop=True)

    @staticmethod
    def _source_type(statement_type: str) -> str | None:
        key = str(statement_type).strip().lower()
        return STATEMENT_SOURCE_ALIASES.get(key)

    @staticmethod
    def _parse_report_list(
        ts_code: str,
        report_type: str,
        report_list: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows = []
        for period in sorted(report_list.keys(), reverse=True):
            period_text = str(period)
            if len(period_text) != 8 or not period_text.isdigit():
                continue
            end_date = f"{period_text[:4]}-{period_text[4:6]}-{period_text[6:8]}"
            obj = report_list.get(period) or {}
            for item_order, item in enumerate(obj.get("data", []) or [], start=1):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("item_title", "")).strip()
                value = item.get("item_value")
                if not title or value is None:
                    continue
                rows.append({
                    "ts_code": ts_code,
                    "report_type": report_type,
                    "end_date": end_date,
                    "ann_date": pd.NaT,
                    "item_order": item_order,
                    "item": title,
                    "value": _parse_number_or_text(value),
                    "item_yoy": _parse_number_or_text(item.get("item_tongbi")),
                    "source": "sina_finance",
                })
        return rows
