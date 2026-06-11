"""Unit tests for cadence and duration computation from a fixture RSS."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from podcast_benchmark import metrics as M
from podcast_benchmark.sources import parse_rss_bytes

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"
# Pin "now" so window math is deterministic. Fixture has 3 episodes (Jun/May/Apr
# 2026) inside a 6-month window ending 2026-06-10, and 2 episodes in early 2025
# outside it.
NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)


@pytest.fixture
def feed():
    return parse_rss_bytes(FIXTURE.read_bytes())


def test_parse_counts_all_items(feed):
    assert feed["item_count_in_feed"] == 5
    assert feed["channel_title"] == "Fixture Show"


def test_duration_parsing_seconds_and_hhmmss(feed):
    # Ep5=3600s, Ep4="00:30:00"=1800s, Ep3=1800, Ep2=2400, Ep1=None
    durs = [e["duration_sec"] for e in feed["episodes"]]
    assert durs == [3600, 1800, 1800, 2400, None]


def test_average_duration_ignores_missing(feed):
    # Mean of 3600,1800,1800,2400 = 2400s = 40.0 min
    assert M.average_duration_min(feed) == 40.0


def test_cadence_counts_only_window(feed):
    cadence = M.cadence_per_month(feed, now=NOW)
    # 3 episodes in trailing 183 days; rate = 3 / (183/30) = 0.49
    assert cadence["in_window"] == 3
    assert cadence["per_month"] == pytest.approx(0.49, abs=0.01)


def test_cadence_not_truncated_when_old_episodes_present(feed):
    # Feed has episodes outside the window, so it is not flagged truncated.
    assert M.cadence_per_month(feed, now=NOW)["truncated"] is False


def test_cadence_truncated_flag_when_all_in_window():
    # A feed whose every episode is inside the window gets flagged.
    data = {
        "episodes": [
            {"pubdate": "2026-06-01T00:00:00+00:00"},
            {"pubdate": "2026-05-01T00:00:00+00:00"},
        ]
    }
    c = M.cadence_per_month(data, now=NOW)
    assert c["truncated"] is True
    assert c["in_window"] == 2


def test_cadence_single_item_inside_window_is_truncated():
    # One episode, inside the window: the oldest item is inside the window,
    # so the feed may be capped and must be flagged (excluded from ranking).
    data = {"episodes": [{"pubdate": "2026-06-01T00:00:00+00:00"}]}
    c = M.cadence_per_month(data, now=NOW)
    assert c["truncated"] is True
    assert c["in_window"] == 1
    assert c["per_month"] is not None


def test_cadence_single_item_outside_window_not_truncated():
    # One ancient episode: dormant show, cadence 0, no truncation suspicion.
    data = {"episodes": [{"pubdate": "2020-01-01T00:00:00+00:00"}]}
    c = M.cadence_per_month(data, now=NOW)
    assert c["truncated"] is False
    assert c["in_window"] == 0
    assert c["per_month"] == 0.0


def test_cadence_excludes_future_dated_episodes():
    # A future-dated item has not published in the trailing window; counting
    # it would inflate the published cadence.
    data = {
        "episodes": [
            {"pubdate": "2026-07-01T00:00:00+00:00"},  # future vs NOW
            {"pubdate": "2026-05-01T00:00:00+00:00"},
            {"pubdate": "2025-01-01T00:00:00+00:00"},  # outside window
        ]
    }
    c = M.cadence_per_month(data, now=NOW)
    assert c["in_window"] == 1
    assert c["future_dated"] == 1
    assert c["truncated"] is False
    assert c["per_month"] == pytest.approx(1 / (183 / 30.0), abs=0.01)


def test_days_since_last_ignores_future_dated():
    data = {
        "episodes": [
            {"pubdate": "2026-07-01T00:00:00+00:00"},  # future vs NOW
            {"pubdate": "2026-06-01T00:00:00+00:00"},
        ]
    }
    # Without the guard this would be negative.
    assert M.days_since_last_episode(data, now=NOW) == 9


def test_days_since_last_all_future_is_none():
    data = {"episodes": [{"pubdate": "2026-07-01T00:00:00+00:00"}]}
    assert M.days_since_last_episode(data, now=NOW) is None


def test_transcript_pct(feed):
    # 3 of 5 episodes carry transcript tags.
    assert M.transcript_availability_pct(feed) == 60.0


def test_days_since_last_episode(feed):
    # Newest is 2026-06-01 10:00; now is 2026-06-10 00:00 -> 8 full days.
    assert M.days_since_last_episode(feed, now=NOW) == 8


def test_hygiene_full(feed):
    checklist = M.hygiene_checklist(feed)
    assert checklist == {
        "artwork": True,
        "categories": True,
        "funding_tag": True,
        "locked_tag": True,
    }
    assert M.hygiene_score(checklist) == 4


def test_catalog_depth_prefers_apple():
    assert M.catalog_depth({"track_count": 62}, {"episode_count": 60}) == 62
    assert M.catalog_depth({"track_count": None}, {"episode_count": 60}) == 60
    assert M.catalog_depth(None, None) is None


def test_empty_feed_returns_none_metrics():
    empty = {"episodes": []}
    assert M.average_duration_min(empty) is None
    assert M.transcript_availability_pct(empty) is None
    assert M.days_since_last_episode(empty, now=NOW) is None
    assert M.cadence_per_month(empty, now=NOW)["per_month"] is None
