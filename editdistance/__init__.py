from __future__ import annotations

from typing import Any

__all__ = ["eval", "distance", "levenshtein"]


def eval(a: Any, b: Any) -> int:
    return levenshtein(a, b)


def distance(a: Any, b: Any) -> int:
    return levenshtein(a, b)


def levenshtein(a: Any, b: Any) -> int:
    sa = "" if a is None else str(a)
    sb = "" if b is None else str(b)
    if sa == sb:
        return 0
    if not sa:
        return len(sb)
    if not sb:
        return len(sa)

    if len(sa) > len(sb):
        sa, sb = sb, sa

    prev = list(range(len(sa) + 1))
    cur = [0] * (len(sa) + 1)

    for j, cb in enumerate(sb, start=1):
        cur[0] = j
        for i, ca in enumerate(sa, start=1):
            cost = 0 if ca == cb else 1
            cur[i] = min(
                prev[i] + 1,
                cur[i - 1] + 1,
                prev[i - 1] + cost,
            )
        prev, cur = cur, prev

    return prev[len(sa)]

