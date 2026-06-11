"""Unit tests for RSS parsing: durations, namespace variants, hygiene tags."""

import pytest

from podcast_benchmark.sources import _parse_duration, parse_rss_bytes


# --------------------------------------------------------------------------- #
# itunes:duration parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3600", 3600),
        ("3600.7", 3600),  # fractional bare seconds truncate
        ("00:30:00", 1800),  # HH:MM:SS
        ("45:30", 2730),  # MM:SS
        ("01:02:03", 3723),
        ("00:45:12.5", 2712),  # fractional seconds in colon form round (half-to-even)
        ("", None),
        ("   ", None),
        (None, None),
        ("abc", None),
        ("1:2:3:4", None),  # more than three components is malformed
        ("-30", None),  # negative durations are junk, not data
        ("-1:30", None),
        ("12:xx", None),
    ],
)
def test_parse_duration(text, expected):
    assert _parse_duration(text) == expected


# --------------------------------------------------------------------------- #
# Namespace variants
# --------------------------------------------------------------------------- #
GITHUB_NS_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="https://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md">
  <channel>
    <title>Variant NS Show</title>
    <itunes:image href="https://example.com/art.jpg"/>
    <itunes:category text="Technology"/>
    <podcast:funding url="https://example.com/support">Support</podcast:funding>
    <podcast:locked>yes</podcast:locked>
    <item>
      <title>Ep 1</title>
      <pubDate>Mon, 01 Jun 2026 10:00:00 +0000</pubDate>
      <itunes:duration>00:30:00</itunes:duration>
      <podcast:transcript url="https://example.com/1.txt" type="text/plain"/>
    </item>
  </channel>
</rss>"""


def test_github_namespace_variant_detected():
    """Feeds declaring the podcast namespace via the GitHub docs URL (and
    itunes via https) must still have transcript/funding/locked/duration
    detected. Missing this silently zeroes published transcript percentages."""
    data = parse_rss_bytes(GITHUB_NS_FEED)
    assert data["has_funding_tag"] is True
    assert data["has_locked_tag"] is True
    assert data["has_artwork"] is True
    assert data["has_categories"] is True
    ep = data["episodes"][0]
    assert ep["has_transcript"] is True
    assert ep["duration_sec"] == 1800


def test_locked_no_does_not_count():
    feed = GITHUB_NS_FEED.replace(
        b"<podcast:locked>yes</podcast:locked>",
        b"<podcast:locked>no</podcast:locked>",
    )
    data = parse_rss_bytes(feed)
    assert data["has_locked_tag"] is False


# --------------------------------------------------------------------------- #
# Malformed input
# --------------------------------------------------------------------------- #
def test_truncated_xml_raises():
    with pytest.raises(Exception):
        parse_rss_bytes(GITHUB_NS_FEED[: len(GITHUB_NS_FEED) // 2])


def test_html_error_page_raises():
    html = b"<html><head><title>503</title></head><body>Service Unavailable</body></html>"
    with pytest.raises(Exception):
        parse_rss_bytes(html)  # no <channel> element


def test_no_channel_raises():
    with pytest.raises(ValueError):
        parse_rss_bytes(b"<rss version='2.0'></rss>")
