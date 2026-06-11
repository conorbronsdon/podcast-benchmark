"""Compute per-show metrics from fetched source data.

Pure functions over already-fetched data. No network here. The sentinel
``None`` means "data unavailable" and propagates to the report as N/A.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

CADENCE_WINDOW_DAYS = 183  # trailing ~6 months


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def episode_pubdates(rss_data: dict[str, Any]) -> list[datetime]:
    """Sorted (newest first) list of parsed episode pubdates from RSS."""
    dates: list[datetime] = []
    for ep in rss_data.get("episodes", []):
        dt = _parse_iso(ep.get("pubdate"))
        if dt is not None:
            dates.append(dt)
    dates.sort(reverse=True)
    return dates


def cadence_per_month(
    rss_data: dict[str, Any],
    now: datetime | None = None,
    window_days: int = CADENCE_WINDOW_DAYS,
) -> dict[str, Any]:
    """Episodes per month over the trailing window, computed from RSS pubdates.

    Returns a dict with the rate plus a ``truncated`` flag. The flag is True
    when every episode in the feed falls inside the window, which means the
    feed may be capping its item list and the rate could understate reality.
    In that case the rate is still reported but flagged so the report can note
    the caveat rather than rank on a possibly-truncated value.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    dates = episode_pubdates(rss_data)

    if not dates:
        return {"per_month": None, "in_window": 0, "truncated": False}

    in_window = [d for d in dates if d >= cutoff]
    count = len(in_window)
    per_month = round(count / (window_days / 30.0), 2)

    # If the oldest episode in the feed is itself inside the window, the feed
    # window may be truncated (e.g. Transistor serves only the last N items).
    truncated = dates[-1] >= cutoff and count == len(dates)

    return {
        "per_month": per_month,
        "in_window": count,
        "truncated": truncated,
    }


def average_duration_min(rss_data: dict[str, Any]) -> float | None:
    """Mean episode duration in minutes over episodes that report a duration."""
    durs = [
        ep["duration_sec"]
        for ep in rss_data.get("episodes", [])
        if ep.get("duration_sec")
    ]
    if not durs:
        return None
    return round(sum(durs) / len(durs) / 60.0, 1)


def transcript_availability_pct(rss_data: dict[str, Any]) -> float | None:
    """Percent of in-feed episodes carrying a podcast:transcript tag."""
    eps = rss_data.get("episodes", [])
    if not eps:
        return None
    have = sum(1 for ep in eps if ep.get("has_transcript"))
    return round(100.0 * have / len(eps), 1)


def days_since_last_episode(
    rss_data: dict[str, Any], now: datetime | None = None
) -> int | None:
    now = now or datetime.now(timezone.utc)
    dates = episode_pubdates(rss_data)
    if not dates:
        return None
    return (now - dates[0]).days


def hygiene_checklist(rss_data: dict[str, Any]) -> dict[str, bool]:
    """Boolean feed-hygiene signals from the RSS channel."""
    return {
        "artwork": bool(rss_data.get("has_artwork")),
        "categories": bool(rss_data.get("has_categories")),
        "funding_tag": bool(rss_data.get("has_funding_tag")),
        "locked_tag": bool(rss_data.get("has_locked_tag")),
    }


def hygiene_score(checklist: dict[str, bool]) -> int:
    """Count of hygiene signals present (0-4)."""
    return sum(1 for v in checklist.values() if v)


def catalog_depth(apple_data: dict | None, pi_data: dict | None) -> int | None:
    """Best available episode count. Prefer Apple trackCount, then Podcast Index."""
    if apple_data and apple_data.get("track_count"):
        return apple_data["track_count"]
    if pi_data and pi_data.get("episode_count"):
        return pi_data["episode_count"]
    return None
