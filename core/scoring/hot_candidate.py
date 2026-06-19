"""Conservative hot-candidate scoring rules for short-term A-share selection."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


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
        return 20
    if 0 <= gap < 1:
        return 17
    if -2 <= gap < 0:
        return 14
    if 5 < gap <= 7:
        return 10
    return 0


def _score_capital_persistence(row: pd.Series, reasons: list[str]) -> int:
    ddx = _num(row, "ddx", reasons)
    ddy = _num(row, "ddy", reasons)
    direction = _num(row, "main_direction_5d", reasons)
    if ddx is None or ddy is None or direction is None:
        return 1
    positives = sum([ddx > 0, ddy > 0, direction > 0])
    strong = sum([ddx >= 0.5, ddy >= 0.5, direction >= 0.5])
    if strong == 3:
        return 18
    if positives == 3:
        return 15
    if positives == 2:
        return 12
    if positives == 1:
        return 8
    return 1


def _score_seal_quality(row: pd.Series, reasons: list[str]) -> int:
    seal_ratio = _num(row, "seal_ratio", reasons)
    float_ratio = _num(row, "seal_float_mv_ratio", reasons)
    if seal_ratio is None or float_ratio is None:
        return 2
    if seal_ratio >= 5 and float_ratio >= 2:
        return 15
    if seal_ratio >= 3:
        return 12
    if seal_ratio >= 1.5:
        return 8
    if seal_ratio >= 0.8:
        return 5
    return 2


def _score_support_quality(row: pd.Series, reasons: list[str]) -> int:
    main_buy = _num(row, "main_buy_ratio", reasons)
    volume_ratio = _num(row, "volume_ratio", reasons)
    turnover = _num(row, "turnover_rate", reasons)
    if main_buy is None or volume_ratio is None or turnover is None:
        return 2
    checks = [
        main_buy >= 0.30,
        1.2 <= volume_ratio <= 3.5,
        5 <= turnover <= 25,
    ]
    count = sum(checks)
    if count == 3:
        return 15
    if count == 2:
        return 12
    if count == 1:
        return 9
    if main_buy > 0 or volume_ratio > 0 or turnover > 0:
        return 6
    return 2


def _score_safety(row: pd.Series, reasons: list[str]) -> tuple[int, bool]:
    if _bool(row, "is_st") or _bool(row, "is_delisted"):
        reasons.append("safety_reject")
        return 0, True
    safety = _num(row, "safety_score", reasons)
    if safety is None:
        return 1, False
    if safety >= 92:
        return 10, False
    if safety >= 85:
        return 8, False
    if safety >= 75:
        return 6, False
    if safety >= 65:
        return 4, False
    return 1, False


def _score_liquidity(row: pd.Series, reasons: list[str]) -> int:
    circ_mv = _num(row, "circ_mv", reasons)
    amount = _num(row, "amount", reasons)
    if circ_mv is None or amount is None:
        return 2
    if 20 <= circ_mv <= 160 and amount >= 3:
        return 10
    if 10 <= circ_mv <= 260:
        return 8
    if 5 <= circ_mv <= 400:
        return 5
    return 2


def _score_sector(row: pd.Series, reasons: list[str]) -> int:
    limit_count = _num(row, "sector_limit_up_count", reasons)
    pct_chg = _num(row, "sector_pct_chg", reasons)
    direction = _num(row, "sector_main_direction", reasons)
    score = 0
    if limit_count is not None:
        if limit_count >= 8:
            score += 4
        elif limit_count >= 5:
            score += 3
        elif limit_count >= 3:
            score += 2
        elif limit_count >= 1:
            score += 1
    if pct_chg is not None:
        if pct_chg >= 3:
            score += 3
        elif pct_chg >= 1.5:
            score += 2
        elif pct_chg > 0:
            score += 1
    if direction is not None and direction > 0:
        score += 1
    return min(score, 8)


def _score_leader(row: pd.Series, reasons: list[str]) -> int:
    rank = _num(row, "sector_rank", reasons)
    streak = _num(row, "limit_up_streak", reasons)
    if rank is None or streak is None:
        return 1
    if rank == 1 and streak >= 2:
        return 4
    if rank <= 2 and streak >= 3:
        return 3
    if streak >= 2:
        return 2
    return 1


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
        "capital_persistence_score": _score_capital_persistence(row, reasons),
        "seal_quality_score": _score_seal_quality(row, reasons),
        "support_quality_score": _score_support_quality(row, reasons),
        "safety_filter_score": safety_score,
        "liquidity_structure_score": _score_liquidity(row, reasons),
        "sector_resonance_score": _score_sector(row, reasons),
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
    """Score short-term candidates with conservative missing-field handling."""
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
