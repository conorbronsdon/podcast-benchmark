"""Public data sources for podcast benchmarking.

Three sources, all public:
  - Apple iTunes lookup API (no auth)
  - Podcast Index API (free key, optional, degrades to None without it)
  - The RSS feed itself (no auth)

Every fetch returns a (data, warnings) shaped result so failures surface
as warnings rather than silent gaps. Nothing here invents numbers.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

import requests

USER_AGENT = "podcast-benchmark/0.1 (+https://github.com/conorbronsdon/podcast-benchmark)"
DEFAULT_TIMEOUT = 30

# XML namespaces used in podcast RSS feeds.
NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "podcast": "https://podcastindex.org/namespace/1.0",
    "atom": "http://www.w3.org/2005/Atom",
}


@dataclass
class SourceResult:
    """A fetch result. ``data`` is None when the fetch failed."""

    data: Any = None
    warnings: list[str] = field(default_factory=list)
    fetched_at: str | None = None

    @property
    def ok(self) -> bool:
        return self.data is not None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Apple iTunes lookup
# --------------------------------------------------------------------------- #
def fetch_apple(apple_id: int | str, session: requests.Session | None = None) -> SourceResult:
    """Look up a podcast in the Apple iTunes API by collection id.

    Note: Apple's public lookup API exposes catalog metadata (trackCount,
    genre, feedUrl, releaseDate) but does NOT return userRatingCount or
    averageUserRating. Those fields are absent from the public response, so
    ratings are reported as N/A. We still read them in case Apple ever
    restores them.
    """
    sess = session or requests
    url = "https://itunes.apple.com/lookup"
    res = SourceResult(fetched_at=_now_iso())
    try:
        resp = sess.get(
            url,
            params={"id": str(apple_id)},
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - degrade, never crash
        res.warnings.append(f"apple: lookup for id {apple_id} failed: {exc}")
        return res

    results = payload.get("results") or []
    if not results:
        res.warnings.append(f"apple: no result for id {apple_id}")
        return res

    item = results[0]
    res.data = {
        "collection_name": item.get("collectionName"),
        "artist_name": item.get("artistName"),
        "track_count": item.get("trackCount"),
        "primary_genre": item.get("primaryGenreName"),
        "feed_url": item.get("feedUrl"),
        "latest_release_date": item.get("releaseDate"),
        # Present only if Apple ever restores ratings on the public API.
        "user_rating_count": item.get("userRatingCount"),
        "average_user_rating": item.get("averageUserRating"),
    }
    if res.data["user_rating_count"] is None:
        res.warnings.append(
            f"apple: ratings not exposed by public API for id {apple_id} (expected)"
        )
    return res


# --------------------------------------------------------------------------- #
# Podcast Index (optional)
# --------------------------------------------------------------------------- #
def _podcastindex_headers(key: str, secret: str) -> dict[str, str]:
    """Auth headers per Podcast Index convention: sha1(key + secret + epoch)."""
    epoch = str(int(time.time()))
    digest = hashlib.sha1((key + secret + epoch).encode("utf-8")).hexdigest()
    return {
        "User-Agent": USER_AGENT,
        "X-Auth-Key": key,
        "X-Auth-Date": epoch,
        "Authorization": digest,
    }


def fetch_podcastindex(
    feed_url: str,
    key: str | None,
    secret: str | None,
    session: requests.Session | None = None,
) -> SourceResult:
    """Look up a feed in Podcast Index by feed URL.

    Returns None data (with a warning) when credentials are absent, so the
    rest of the pipeline degrades gracefully. Used mainly to corroborate
    episode counts and categories for feeds whose Apple id is unknown.
    """
    res = SourceResult(fetched_at=_now_iso())
    if not key or not secret:
        res.warnings.append(
            "podcastindex: skipped (PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET unset)"
        )
        return res

    sess = session or requests
    url = "https://api.podcastindex.org/api/1.0/podcasts/byfeedurl"
    try:
        resp = sess.get(
            url,
            params={"url": feed_url},
            headers=_podcastindex_headers(key, secret),
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        res.warnings.append(f"podcastindex: lookup for {feed_url} failed: {exc}")
        return res

    feed = payload.get("feed") or {}
    if not feed:
        res.warnings.append(f"podcastindex: no feed for {feed_url}")
        return res

    res.data = {
        "feed_id": feed.get("id"),
        "itunes_id": feed.get("itunesId"),
        "episode_count": feed.get("episodeCount"),
        "categories": feed.get("categories"),
        "last_update_time": feed.get("lastUpdateTime"),
        "dead": feed.get("dead"),
        "locked": feed.get("locked"),
        "last_http_status": feed.get("lastHttpStatus"),
    }
    return res


# --------------------------------------------------------------------------- #
# RSS feed
# --------------------------------------------------------------------------- #
def fetch_rss(feed_url: str, session: requests.Session | None = None) -> SourceResult:
    """Fetch and parse an RSS feed into a normalized dict.

    Pulls per-episode pubDate, duration, and transcript presence plus
    channel-level hygiene signals (artwork, categories, funding, locked).
    Parsing is done with the stdlib XML parser so the only third-party
    dependency is requests.
    """
    sess = session or requests
    res = SourceResult(fetched_at=_now_iso())
    try:
        resp = sess.get(feed_url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        raw = resp.content
    except Exception as exc:  # noqa: BLE001
        res.warnings.append(f"rss: fetch for {feed_url} failed: {exc}")
        return res

    try:
        res.data = parse_rss_bytes(raw)
    except Exception as exc:  # noqa: BLE001
        res.warnings.append(f"rss: parse for {feed_url} failed: {exc}")
    return res


def _parse_duration(text: str | None) -> int | None:
    """Parse itunes:duration to seconds. Accepts integer seconds or HH:MM:SS."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return None
        seconds = 0
        for n in nums:
            seconds = seconds * 60 + n
        return seconds
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_pubdate(text: str | None) -> datetime | None:
    """Parse an RFC 2822 pubDate into an aware UTC datetime."""
    if not text:
        return None
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(text.strip())
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_rss_bytes(raw: bytes) -> dict[str, Any]:
    """Parse raw RSS bytes into the normalized feed dict. Pure function."""
    root = ET.fromstring(raw)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("no <channel> element")

    title = channel.findtext("title")

    # Channel-level hygiene signals.
    has_artwork = (
        channel.find("itunes:image", NS) is not None
        or channel.find("image") is not None
    )
    categories = [
        c.get("text")
        for c in channel.findall("itunes:category", NS)
        if c.get("text")
    ]
    has_categories = len(categories) > 0
    has_funding = channel.find("podcast:funding", NS) is not None
    locked_el = channel.find("podcast:locked", NS)
    has_locked = locked_el is not None and (locked_el.text or "").strip().lower() == "yes"

    episodes: list[dict[str, Any]] = []
    for item in channel.findall("item"):
        pub_raw = item.findtext("pubDate")
        pub_dt = _parse_pubdate(pub_raw)
        dur = _parse_duration(item.findtext("itunes:duration", namespaces=NS))
        has_transcript = item.find("podcast:transcript", NS) is not None
        description = (
            item.findtext("description")
            or item.findtext("itunes:summary", namespaces=NS)
            or ""
        )
        episodes.append(
            {
                "pubdate_raw": pub_raw,
                "pubdate": pub_dt.isoformat() if pub_dt else None,
                "duration_sec": dur,
                "has_transcript": has_transcript,
                "description_length": len(description.strip()),
            }
        )

    return {
        "channel_title": title,
        "item_count_in_feed": len(episodes),
        "has_artwork": has_artwork,
        "categories": categories,
        "has_categories": has_categories,
        "has_funding_tag": has_funding,
        "has_locked_tag": has_locked,
        "episodes": episodes,
    }
