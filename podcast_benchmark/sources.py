"""Public data sources for podcast benchmarking.

Four sources, all public:
  - Apple iTunes lookup API (no auth)
  - Podcast Index API (free key, optional, degrades to None without it)
  - The RSS feed itself (no auth)
  - YouTube Data API channel statistics (free API key, optional, degrades
    to None without it)

Every fetch returns a (data, warnings) shaped result so failures surface
as warnings rather than silent gaps. Nothing here invents numbers.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

import requests

USER_AGENT = "podcast-benchmark/0.1 (+https://github.com/conorbronsdon/podcast-benchmark)"
DEFAULT_TIMEOUT = 30

# XML namespaces used in podcast RSS feeds. Real-world feeds declare these
# under several URI variants, so element lookup matches any URI in the set
# rather than a single canonical one.
PODCAST_NS_URIS = frozenset(
    {
        "https://podcastindex.org/namespace/1.0",
        "http://podcastindex.org/namespace/1.0",
        # Variant used by feeds generated against the original namespace docs.
        "https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md",
        "http://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md",
    }
)
ITUNES_NS_URIS = frozenset(
    {
        "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "https://www.itunes.com/dtds/podcast-1.0.dtd",
    }
)


def _split_tag(tag: Any) -> tuple[str | None, Any]:
    """Split an ElementTree tag into (namespace_uri, local_name)."""
    if isinstance(tag, str) and tag.startswith("{"):
        uri, _, local = tag[1:].partition("}")
        return uri, local
    return None, tag


def _findall_ns(parent: ET.Element, local: str, uris: frozenset[str]) -> list[ET.Element]:
    """All direct children named ``local`` under any of the namespace URIs."""
    out = []
    for child in parent:
        uri, name = _split_tag(child.tag)
        if name == local and uri in uris:
            out.append(child)
    return out


def _find_ns(parent: ET.Element, local: str, uris: frozenset[str]) -> ET.Element | None:
    found = _findall_ns(parent, local, uris)
    return found[0] if found else None


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
# YouTube (optional)
# --------------------------------------------------------------------------- #
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
# A channel ID is "UC" plus 22 URL-safe base64 characters. Handles allow
# international letters with script-specific length rules, so only obvious
# junk (whitespace, separators, control characters) is rejected here and
# YouTube decides the rest.
YOUTUBE_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
YOUTUBE_HANDLE_RE = re.compile(r"^@[^\s,/?#&@\x00-\x1f\x7f]{1,100}$")
# Google API keys are URL-safe tokens. Anything else is rejected before it is
# put in a header, so a malformed key can't surface in an exception message.
YOUTUBE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{10,200}$")


def _redact(text: str, secret: str | None) -> str:
    """Remove a secret from text that may echo a request (e.g. an HTTPError)."""
    return text.replace(secret, "[redacted]") if secret else text


def _count(value: Any) -> int | None:
    """A non-negative integer count, or None.

    YouTube returns counts as decimal strings. Booleans, floats and anything
    that isn't a plain digit string are N/A rather than coerced (int(True) is
    1 and int(0.9) is 0, which would be invented observations).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    # 20 digits covers any real count and keeps int() clear of its
    # digit-length limit, which would raise instead of returning N/A.
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 20:
        return int(value)
    return None


def _failure(exc: Exception) -> str:
    """Describe a request failure without echoing request text (URL, headers)."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


def fetch_youtube(
    channel_id: str | None,
    handle: str | None,
    key: str | None,
    session: requests.Session | None = None,
) -> SourceResult:
    """Channel-level statistics from the YouTube Data API (channels.list).

    API key only, no OAuth; one quota unit per call. The key travels in the
    ``X-Goog-Api-Key`` header, not the URL; redirects are refused so the
    header can't be forwarded to another host; and failure warnings carry
    only an HTTP status or exception type, so the key never lands in
    warnings or benchmark.json.

    Returns None data (with a warning) when the key is absent or malformed,
    or the response isn't the one channel asked for. A channel that hides its
    subscriber count yields ``subscriber_count`` None, never 0.
    """
    res = SourceResult(fetched_at=_now_iso())
    label = channel_id or handle
    if not label:
        return res
    if channel_id and not YOUTUBE_CHANNEL_ID_RE.match(channel_id):
        res.warnings.append(f"youtube: {channel_id!r} is not a single channel ID (skipped)")
        return res
    if not channel_id and not YOUTUBE_HANDLE_RE.match(handle):
        res.warnings.append(f"youtube: {handle!r} is not a valid handle (skipped)")
        return res
    if not key:
        res.warnings.append(f"youtube: skipped for {label} (YOUTUBE_API_KEY unset)")
        return res
    if not YOUTUBE_KEY_RE.match(key):
        res.warnings.append(f"youtube: skipped for {label} (YOUTUBE_API_KEY is malformed)")
        return res

    params = {"part": "snippet,statistics"}
    if channel_id:
        params["id"] = channel_id
    else:
        params["forHandle"] = handle
    sess = session or requests
    try:
        resp = sess.get(
            YOUTUBE_CHANNELS_URL,
            params=params,
            headers={"User-Agent": USER_AGENT, "X-Goog-Api-Key": key},
            timeout=DEFAULT_TIMEOUT,
            allow_redirects=False,
        )
        status = getattr(resp, "status_code", 200)
        if 300 <= status < 400:
            res.warnings.append(f"youtube: lookup for {label} redirected (HTTP {status}); refused")
            return res
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - degrade, never crash
        res.warnings.append(_redact(f"youtube: lookup for {label} failed: {_failure(exc)}", key))
        return res

    items = payload.get("items") if isinstance(payload, dict) else None
    if not items:
        res.warnings.append(f"youtube: no channel found for {label}")
        return res
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        res.warnings.append(f"youtube: unexpected response shape for {label} (N/A)")
        return res

    item = items[0]
    if channel_id and item.get("id") != channel_id:
        res.warnings.append(f"youtube: response for {label} named a different channel (N/A)")
        return res
    stats = item.get("statistics")
    snippet = item.get("snippet")
    stats = stats if isinstance(stats, dict) else {}
    snippet = snippet if isinstance(snippet, dict) else {}
    hidden = stats.get("hiddenSubscriberCount") is True
    res.data = {
        "channel_id": item.get("id") if isinstance(item.get("id"), str) else None,
        "title": snippet.get("title") if isinstance(snippet.get("title"), str) else None,
        "subscriber_count": None if hidden else _count(stats.get("subscriberCount")),
        "hidden_subscriber_count": hidden,
        "view_count": _count(stats.get("viewCount")),
        "video_count": _count(stats.get("videoCount")),
    }
    if hidden:
        res.warnings.append(f"youtube: {label} hides its subscriber count (N/A)")
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
    """Parse itunes:duration to seconds.

    Accepts bare seconds ("3600", "3600.5") and colon forms MM:SS / HH:MM:SS
    (fractional seconds tolerated). Negative or malformed values return None.
    """
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        if len(parts) > 3:
            return None
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        if any(n < 0 for n in nums):
            return None
        seconds = 0.0
        for n in nums:
            seconds = seconds * 60 + n
        return int(round(seconds))
    try:
        value = float(text)
    except ValueError:
        return None
    if value < 0:
        return None
    return int(value)


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
        _find_ns(channel, "image", ITUNES_NS_URIS) is not None
        or channel.find("image") is not None
    )
    categories = [
        c.get("text")
        for c in _findall_ns(channel, "category", ITUNES_NS_URIS)
        if c.get("text")
    ]
    has_categories = len(categories) > 0
    has_funding = _find_ns(channel, "funding", PODCAST_NS_URIS) is not None
    locked_el = _find_ns(channel, "locked", PODCAST_NS_URIS)
    has_locked = locked_el is not None and (locked_el.text or "").strip().lower() == "yes"

    episodes: list[dict[str, Any]] = []
    for item in channel.findall("item"):
        pub_raw = item.findtext("pubDate")
        pub_dt = _parse_pubdate(pub_raw)
        dur_el = _find_ns(item, "duration", ITUNES_NS_URIS)
        dur = _parse_duration(dur_el.text if dur_el is not None else None)
        has_transcript = _find_ns(item, "transcript", PODCAST_NS_URIS) is not None
        summary_el = _find_ns(item, "summary", ITUNES_NS_URIS)
        description = (
            item.findtext("description")
            or (summary_el.text if summary_el is not None else None)
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
