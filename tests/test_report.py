"""End-to-end report test with all network mocked."""

import json
from pathlib import Path

from podcast_benchmark.cli import main as cli_main
from podcast_benchmark.config import parse_config
from podcast_benchmark.report import build_benchmark, render_markdown, write_outputs

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()

CONFIG = """
subject:
  name: Subject Show
  feed_url: https://example.com/subject.xml
  apple_id: 111
peers:
  - name: Peer No Apple
    feed_url: https://example.com/peer.xml
"""


class FakeResp:
    def __init__(self, *, json_data=None, content=b""):
        self._json = json_data
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeSession:
    """Routes by URL so we can mock Apple, Podcast Index, and RSS together."""

    def get(self, url, params=None, headers=None, timeout=None):
        if "itunes.apple.com" in url:
            return FakeResp(
                json_data={
                    "results": [
                        {
                            "collectionName": "Subject Show",
                            "trackCount": 42,
                            "primaryGenreName": "Technology",
                            "feedUrl": "https://example.com/subject.xml",
                            "releaseDate": "2026-06-01T10:00:00Z",
                            # No ratings, mirroring the real API.
                        }
                    ]
                }
            )
        if "podcastindex.org" in url:
            return FakeResp(json_data={"feed": {"id": 1, "episodeCount": 40}})
        # RSS for both shows.
        return FakeResp(content=FIXTURE)


class FailingRssSession(FakeSession):
    """Apple and Podcast Index succeed; the RSS fetch raises."""

    def get(self, url, params=None, headers=None, timeout=None):
        if "itunes.apple.com" in url or "podcastindex.org" in url:
            return super().get(url, params=params, headers=headers, timeout=timeout)
        raise ConnectionError("rss down")


def test_rss_failure_yields_na_not_zeros():
    """A failed RSS fetch must produce N/A feed metrics, never a 0/4 hygiene
    score or 0-item feed that would be ranked as if it were real data."""
    cfg = parse_config(CONFIG)
    doc = build_benchmark(cfg, pi_key="k", pi_secret="s", session=FailingRssSession())

    for show in doc["shows"]:
        m = show["metrics"]
        assert m["hygiene_score"] is None
        assert m["hygiene"] is None
        assert m["feed_items_seen"] is None
        assert m["cadence_per_month"] is None
        assert m["transcript_pct"] is None
        assert m["days_since_last_episode"] is None
        assert any("rss: fetch" in w for w in show["warnings"])

    md = render_markdown(doc)
    # Overview hygiene cell renders N/A, not "0/4" or "None/4".
    assert "None/4" not in md
    assert "0/4" not in md
    # Hygiene ranking is omitted (no show has data), not ranked on zeros.
    assert "No show had data for this metric. Ranking omitted." in md
    json.dumps(doc)


def test_truncated_cadence_excluded_with_distinct_label():
    """Shows excluded for a possibly-truncated window are labeled as such,
    separately from shows excluded for having no data at all."""
    cfg = parse_config(CONFIG)
    doc = build_benchmark(cfg, pi_key="k", pi_secret="s", session=FakeSession())

    # Force the subject's cadence window to look truncated.
    subject = doc["shows"][0]
    subject["metrics"]["cadence_window_truncated"] = True

    md = render_markdown(doc)
    assert (
        "Excluded (feed window possibly truncated by the host; value reported "
        "in the overview but not ranked): Subject Show." in md
    )
    # The truncated show is not lumped into the no-data exclusion line.
    assert "Excluded as N/A (no data, not ranked): Subject Show" not in md


def test_build_and_render_with_mocked_network():
    cfg = parse_config(CONFIG)
    doc = build_benchmark(
        cfg, pi_key="k", pi_secret="s", session=FakeSession()
    )

    assert doc["subject"] == "Subject Show"
    assert len(doc["shows"]) == 2

    subject = doc["shows"][0]
    m = subject["metrics"]
    assert m["catalog_episodes"] == 42  # from Apple trackCount
    assert m["transcript_pct"] == 60.0
    assert m["hygiene_score"] == 4
    # Ratings absent -> None everywhere.
    assert m["apple_rating_count"] is None

    # Peer without apple_id still gets RSS metrics + Podcast Index fallback.
    peer = doc["shows"][1]
    assert peer["metrics"]["catalog_episodes"] == 40  # PI fallback
    assert any("no apple_id" in w for w in peer["warnings"])

    md = render_markdown(doc)
    assert "# Podcast Benchmark: Subject Show vs peers" in md
    assert "Apple ratings: N/A" in md or "N/A" in md
    assert "Methodology" in md
    # JSON is serializable.
    json.dumps(doc)


def test_report_regenerates_from_cached_json(tmp_path):
    """report.md can be reproduced byte-for-byte from a cached benchmark.json
    with no network access (the --from-json CLI path)."""
    cfg = parse_config(CONFIG)
    doc = build_benchmark(cfg, pi_key="k", pi_secret="s", session=FakeSession())
    first = tmp_path / "run1"
    json_path, md_path = write_outputs(doc, str(first))

    second = tmp_path / "run2"
    rc = cli_main(["--from-json", json_path, "-o", str(second)])
    assert rc == 0

    original = Path(md_path).read_text(encoding="utf-8")
    regenerated = (second / "report.md").read_text(encoding="utf-8")
    assert regenerated == original
