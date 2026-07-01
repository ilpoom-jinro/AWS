"""
mappers/strategy.py — 복구 전략 ↔ contracts strategy 매핑

contracts.models.RemediationPlan.strategy:
    Literal["restart", "scale_out", "rollback", "manual"]

우리 v0.3의 "investigate"는 팀 표준 "manual"에 대응된다.
"""
from __future__ import annotations

from typing import Literal

Strategy = Literal["restart", "scale_out", "rollback", "manual"]

# 내부 표현 → contracts strategy
STRATEGY_MAP: dict[str, Strategy] = {
    "restart": "restart",
    "scale_out": "scale_out",
    "rollback": "rollback",
    "investigate": "manual",  # v0.3 investigate → MAS manual
    "manual": "manual",
}


def to_strategy(internal: str) -> Strategy:
    """내부 전략명을 contracts strategy로 변환 (미지정 시 manual)."""
    return STRATEGY_MAP.get(internal, "manual")
