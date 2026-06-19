"""Enrich candidate DataFrame with concept/theme data for scoring."""

from __future__ import annotations

import pandas as pd


def enrich_sector_info(
    candidates: pd.DataFrame,
    concept_map: pd.DataFrame,
    hot_themes: pd.DataFrame,
    theme_stocks: pd.DataFrame,
) -> pd.DataFrame:
    """Add sector/theme fields to candidate rows from DB lookup tables.

    Input candidates must have ts_code and trade_date columns.
    Concept map: stock_concept_blocks (ts_code, concept_code, concept_name)
    Hot themes: hot_theme_daily (theme_code, trade_date, theme_name, rank, pct_chg, ...)
    Theme stocks: hot_theme_stocks (theme_code, trade_date, ts_code, ...)
    """
    if candidates.empty:
        return candidates

    df = candidates.copy()
    # Ensure expected columns exist
    for col in [
        "sector_limit_up_count", "sector_pct_chg", "sector_main_direction",
        "sector_rank", "limit_up_streak",
    ]:
        if col not in df.columns:
            df[col] = None

    # Enrich from hot themes: match candidate ts_code against theme_stocks
    if not theme_stocks.empty and "ts_code" in theme_stocks.columns:
        merged = df[["ts_code", "trade_date"]].merge(
            theme_stocks,
            on=["ts_code", "trade_date"],
            how="left",
            suffixes=("", "_ths"),
        )
        # Count stocks in same theme
        if "theme_code" in theme_stocks.columns:
            theme_counts = (
                theme_stocks.groupby(["theme_code", "trade_date"])
                .size()
                .reset_index(name="sector_limit_up_count")
            )
            merged = merged.merge(
                theme_counts,
                on=["theme_code", "trade_date"],
                how="left",
            )
            df["sector_limit_up_count"] = merged["sector_limit_up_count"].fillna(0).astype(int)

        # Theme percentage change from hot_themes
        if not hot_themes.empty:
            theme_pct = hot_themes[["theme_code", "trade_date", "pct_chg"]].rename(
                columns={"pct_chg": "sector_pct_chg_ths"}
            )
            merged = merged.merge(theme_pct, on=["theme_code", "trade_date"], how="left")
            df["sector_pct_chg"] = merged["sector_pct_chg_ths"].fillna(
                df.get("sector_pct_chg", 0)
            )

    return df
