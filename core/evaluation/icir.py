"""Cross-sectional factor IC/IR evaluation."""

from __future__ import annotations

import pandas as pd


IC_DETAIL_COLUMNS = [
    "factor_name",
    "trade_date",
    "label_name",
    "ic",
    "sample_count",
    "method",
    "source",
]

IC_SUMMARY_COLUMNS = [
    "factor_name",
    "label_name",
    "ic_mean",
    "ic_std",
    "ic_ir",
    "sample_dates",
    "method",
    "source",
]


def _empty_detail() -> pd.DataFrame:
    return pd.DataFrame(columns=IC_DETAIL_COLUMNS)


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=IC_SUMMARY_COLUMNS)


def _corr(left: pd.Series, right: pd.Series, method: str) -> float:
    if method == "spearman":
        return left.rank().corr(right.rank(), method="pearson")
    return left.corr(right, method=method)


def evaluate_factor_ic(
    dataset: pd.DataFrame,
    factor_columns: list[str],
    label_column: str = "forward_return_20d",
    method: str = "spearman",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate cross-sectional IC by trade date and summarize ICIR."""
    if dataset.empty or not factor_columns or label_column not in dataset.columns:
        return _empty_detail(), _empty_summary()

    rows = []
    df = dataset.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for trade_date, group in df.groupby("trade_date", sort=True):
        for factor_name in factor_columns:
            if factor_name not in group.columns:
                continue
            pair = group[[factor_name, label_column]].apply(
                pd.to_numeric, errors="coerce"
            ).dropna()
            if len(pair) < 3:
                continue
            ic = _corr(pair[factor_name], pair[label_column], method)
            if pd.isna(ic):
                continue
            rows.append({
                "factor_name": factor_name,
                "trade_date": trade_date,
                "label_name": label_column,
                "ic": float(ic),
                "sample_count": len(pair),
                "method": method,
                "source": "factor_ic",
            })

    if not rows:
        return _empty_detail(), _empty_summary()

    detail = pd.DataFrame(rows, columns=IC_DETAIL_COLUMNS)
    summary_rows = []
    for (factor_name, label_name), group in detail.groupby(["factor_name", "label_name"]):
        ic_mean = group["ic"].mean()
        ic_std = group["ic"].std(ddof=0)
        summary_rows.append({
            "factor_name": factor_name,
            "label_name": label_name,
            "ic_mean": float(ic_mean),
            "ic_std": float(ic_std),
            "ic_ir": float(ic_mean / ic_std) if ic_std else float("nan"),
            "sample_dates": int(len(group)),
            "method": method,
            "source": "factor_ic",
        })

    summary = pd.DataFrame(summary_rows, columns=IC_SUMMARY_COLUMNS)
    return detail.reset_index(drop=True), summary.reset_index(drop=True)
