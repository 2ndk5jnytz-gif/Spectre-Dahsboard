"""منطق نظام Counting القابل للاختبار لبوت Spectre."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CountingDecision:
    accepted: bool
    expected: int
    received: int | None
    violation_count: int
    should_timeout: bool
    reason: str


def parse_count(content: str) -> int | None:
    value = content.strip()
    if not value.isdecimal():
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number if 0 <= number <= 2_147_483_647 else None


def evaluate_count(current: int, content: str, violations: int) -> CountingDecision:
    expected = max(1, int(current) + 1)
    received = parse_count(content)
    if received == expected:
        return CountingDecision(True, expected, received, 0, False, "accepted")
    next_violations = max(0, int(violations)) + 1
    return CountingDecision(
        False,
        expected,
        received,
        next_violations,
        next_violations >= 2,
        "عد بشكل متواصل لا تخرب" if next_violations >= 2 else "counting_invalid",
    )
