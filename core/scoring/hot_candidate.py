"""Stable hot-candidate scoring rules for short-term A-share selection."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


DEFAULT_STRATEGY_NAME = "hot_candidate_v2_stable"

SCORE_COLUMNS = [
    "buyability_score",
    "capital_persistence_score",
    "seal_quality_score",
    "support_quality_score",
    "safety_filter_score",
    "liquidity_structure_score",
    "sector_resonance_score",
    "leader_status_score",
]


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except TypeError:
        return False


def _num(row: pd.Series, column: str, reasons: list[str]) -> float | None:
    if column not in row or _missing(row[column]):
        reasons.append(f"missing:{column}")
        return None
    try:
        value = float(row[column])
    except (TypeError, ValueError):
        reasons.append(f"invalid:{column}")
        return None
    if math.isnan(value):
        reasons.append(f"missing:{column}")
        return None
    return value


def _bool(row: pd.Series, column: str) -> bool:
    if column not in row or _missing(row[column]):
        return False
    return bool(row[column])


def _score_buyability(row: pd.Series, reasons: list[str]) -> int:
    gap = _num(row, "open_gap_pct", reasons)
    if gap is None:
        return 0
    if _bool(row, "is_one_price_limit_up") or gap >= 9.5:
        return 0
    if 1 <= gap <= 5:
        return 25
    if 0 <= gap < 1:
        return 21
    if -2 <= gap < 0:
        return 17
    if 5 < gap <= 7:
        return 12
    return 0


def _score_support_quality(row: pd.Series, reasons: list[str]) -> int:
    volume_ratio = _num(row, "volume_ratio", reasons)
    turnover = _num(row, "turnover_rate", reasons)
    amount = _num(row, "amount", reasons)
    if volume_ratio is None or turnover is None or amount is None:
        return 0
    checks = [
        1.2 <= volume_ratio <= 3.5,
        5 <= turnover <= 25,
        amount >= 3,
    ]
    count = sum(checks)
    if count == 3:
        return 20
    if count == 2:
        return 16
    if count == 1:
        return 10
    if volume_ratio > 0 or turnover > 0 or amount > 0:
        return 6
    return 0


def _score_safety(row: pd.Series, reasons: list[str]) -> tuple[int, bool]:
    if _bool(row, "is_st") or _bool(row, "is_delisted"):
        reasons.append("safety_reject")
        return 0, True
    if "safety_score" not in row or _missing(row["safety_score"]):
        return 10, False
    safety = _num(row, "safety_score", reasons)
    if safety is None:
        return 10, False
    if safety >= 92:
        return 15, False
    if safety >= 85:
        return 12, False
    if safety >= 75:
        return 9, False
    if safety >= 65:
        return 6, False
    return 2, False


def _score_liquidity(row: pd.Series, reasons: list[str]) -> int:
    circ_mv = _num(row, "circ_mv", reasons)
    amount = _num(row, "amount", reasons)
    if circ_mv is None or amount is None:
        return 0
    if 20 <= circ_mv <= 160 and amount >= 3:
        return 20
    if 10 <= circ_mv <= 260:
        return 16
    if 5 <= circ_mv <= 400:
        return 10
    return 4


def _score_leader(row: pd.Series, reasons: list[str]) -> int:
    pct_chg = _num(row, "pct_chg", reasons)
    streak = _num(row, "limit_up_streak", reasons)
    if pct_chg is None:
        return 0
    if streak is None:
        streak = 1
    if pct_chg >= 9.8 and streak >= 2:
        return 20
    if pct_chg >= 9.8:
        return 16
    if pct_chg >= 9.0:
        return 12
    if streak >= 2:
        return 10
    if pct_chg >= 7.0:
        return 6
    return 2


def _level(total_score: int, is_rejected: bool) -> str:
    if is_rejected:
        return "REJECT"
    if total_score >= 85:
        return "S"
    if total_score >= 75:
        return "A"
    if total_score >= 60:
        return "B"
    if total_score >= 45:
        return "C"
    return "D"


def _score_row(row: pd.Series) -> dict[str, Any]:
    reasons: list[str] = []
    safety_score, is_rejected = _score_safety(row, reasons)
    scores = {
        "buyability_score": _score_buyability(row, reasons),
        "capital_persistence_score": 0,
        "seal_quality_score": 0,
        "support_quality_score": _score_support_quality(row, reasons),
        "safety_filter_score": safety_score,
        "liquidity_structure_score": _score_liquidity(row, reasons),
        "sector_resonance_score": 0,
        "leader_status_score": _score_leader(row, reasons),
    }
    total = int(sum(scores.values()))
    theme_score = row["theme_score"] if "theme_score" in row and not _missing(row["theme_score"]) else None
    result = {
        **scores,
        "theme_validation_score": theme_score,
        "total_score": total,
        "score_level": _level(total, is_rejected),
        "is_rejected": is_rejected,
        "score_reason": ";".join(dict.fromkeys(reasons)),
    }
    return result


def score_hot_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    """Score short-term candidates using stable locally available market fields."""
    base_columns = ["ts_code", "trade_date"]
    output_columns = (
        base_columns
        + SCORE_COLUMNS
        + [
            "theme_validation_score",
            "total_score",
            "score_level",
            "is_rejected",
            "score_reason",
        ]
    )
    if candidates.empty:
        return pd.DataFrame(columns=output_columns)

    df = candidates.copy()
    for col in base_columns:
        if col not in df.columns:
            df[col] = None
    scored = pd.DataFrame([_score_row(row) for _, row in df.iterrows()])
    result = pd.concat([df[base_columns].reset_index(drop=True), scored], axis=1)
    return result.sort_values(
        ["is_rejected", "total_score", "ts_code"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
