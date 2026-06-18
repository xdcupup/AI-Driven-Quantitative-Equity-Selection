"""Financial factor derivation from raw statement rows."""

from __future__ import annotations

import pandas as pd


FINANCIAL_FACTOR_COLUMNS = [
    "ts_code",
    "end_date",
    "ann_date",
    "revenue",
    "net_profit",
    "total_assets",
    "total_liabilities",
    "equity",
    "operating_cashflow",
    "revenue_yoy",
    "net_profit_yoy",
    "debt_to_assets",
    "roe",
    "operating_cashflow_to_profit",
    "source",
]

ITEM_ALIASES = {
    "revenue": ["营业总收入", "营业收入", "主营业务收入"],
    "net_profit": ["净利润", "归属于母公司所有者的净利润"],
    "total_assets": ["资产总计", "总资产"],
    "total_liabilities": ["负债合计", "总负债"],
    "equity": ["所有者权益合计", "股东权益合计", "归属于母公司所有者权益合计"],
    "operating_cashflow": [
        "经营活动产生的现金流量净额",
        "经营活动现金流量净额",
        "经营现金流量净额",
    ],
}


def _empty_factors() -> pd.DataFrame:
    return pd.DataFrame(columns=FINANCIAL_FACTOR_COLUMNS)


def _safe_ratio(numerator, denominator, multiplier: float = 1.0):
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return float("nan")
    return float(numerator) / float(denominator) * multiplier


def _canonical_item(item: str) -> str | None:
    text = str(item)
    for canonical, aliases in ITEM_ALIASES.items():
        if any(alias in text for alias in aliases):
            return canonical
    return None


def derive_financial_factors(statements: pd.DataFrame) -> pd.DataFrame:
    """Derive a compact quarterly factor table from raw financial statements."""
    if statements.empty:
        return _empty_factors()

    df = statements.copy()
    required = {"ts_code", "end_date", "item", "value"}
    if required - set(df.columns):
        return _empty_factors()

    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
    df["ann_date"] = pd.to_datetime(df.get("ann_date", pd.NaT), errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["factor_name"] = df["item"].map(_canonical_item)
    df = df.dropna(subset=["ts_code", "end_date", "factor_name", "value"])
    if df.empty:
        return _empty_factors()

    values = (
        df.sort_values(["ts_code", "end_date", "factor_name"])
        .drop_duplicates(["ts_code", "end_date", "factor_name"], keep="first")
        .pivot(index=["ts_code", "end_date"], columns="factor_name", values="value")
        .reset_index()
    )
    ann_dates = (
        df.groupby(["ts_code", "end_date"], as_index=False)["ann_date"]
        .max()
    )
    result = values.merge(ann_dates, on=["ts_code", "end_date"], how="left")
    for col in ITEM_ALIASES:
        if col not in result.columns:
            result[col] = float("nan")

    result = result.sort_values(["ts_code", "end_date"]).reset_index(drop=True)
    prior = result[["ts_code", "end_date", "revenue", "net_profit"]].copy()
    prior["end_date"] = prior["end_date"] + pd.DateOffset(years=1)
    prior = prior.rename(
        columns={"revenue": "prior_revenue", "net_profit": "prior_net_profit"}
    )
    result = result.merge(prior, on=["ts_code", "end_date"], how="left")

    result["revenue_yoy"] = result.apply(
        lambda row: _safe_ratio(
            row["revenue"] - row["prior_revenue"], row["prior_revenue"], 100
        ),
        axis=1,
    )
    result["net_profit_yoy"] = result.apply(
        lambda row: _safe_ratio(
            row["net_profit"] - row["prior_net_profit"], row["prior_net_profit"], 100
        ),
        axis=1,
    )
    result["debt_to_assets"] = result.apply(
        lambda row: _safe_ratio(row["total_liabilities"], row["total_assets"], 100),
        axis=1,
    )
    result["roe"] = result.apply(
        lambda row: _safe_ratio(row["net_profit"], row["equity"], 100),
        axis=1,
    )
    result["operating_cashflow_to_profit"] = result.apply(
        lambda row: _safe_ratio(row["operating_cashflow"], row["net_profit"]),
        axis=1,
    )
    result["source"] = "financial_statements"

    for col in FINANCIAL_FACTOR_COLUMNS:
        if col not in result.columns:
            result[col] = pd.NaT if col in {"end_date", "ann_date"} else float("nan")
    return result[FINANCIAL_FACTOR_COLUMNS].reset_index(drop=True)
