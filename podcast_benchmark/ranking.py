"""Ranking with explicit N/A handling.

A show is only ranked on a metric if it has a non-None value for it. Shows
with N/A are excluded from that metric's ranking and the exclusion is
reported. We never rank a metric where ANY show is missing data without
saying so.
"""

from __future__ import annotations

from typing import Any, Callable


def rank_by(
    shows: list[dict[str, Any]],
    value_fn: Callable[[dict[str, Any]], Any],
    higher_is_better: bool = True,
) -> dict[str, Any]:
    """Rank shows by a metric, excluding those with None values.

    Returns:
        {
          "ranked":   [(name, value), ...]   # sorted, excludes N/A
          "excluded": [name, ...]            # shows with N/A for this metric
        }
    """
    rankable: list[tuple[str, Any]] = []
    excluded: list[str] = []
    for s in shows:
        v = value_fn(s)
        name = s["name"]
        if v is None:
            excluded.append(name)
        else:
            rankable.append((name, v))

    rankable.sort(key=lambda t: t[1], reverse=higher_is_better)
    return {"ranked": rankable, "excluded": excluded}
