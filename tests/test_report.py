"""End-to-end report test with all network mocked."""

import json
from pathlib import Path

from podcast_benchmark.config import parse_config
from podcast_benchmark.report import build_benchmark, render_markdown

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
