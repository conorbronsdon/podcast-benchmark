"""YouTube channel statistics: fetch, config, metrics and report. No network."""

import json
from pathlib import Path

import pytest

from podcast_benchmark.config import parse_config
from podcast_benchmark.metrics import subscriber_count_is_rounded, youtube_metrics
from podcast_benchmark.report import build_benchmark, render_markdown
from podcast_benchmark.sources import fetch_youtube

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()
FAKE_KEY = "test-key-not-real"


class FakeResp:
    def __init__(self, *, json_data=None, content=b"", error=None):
        self._json = json_data
        self.content = content
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._json


def channel(cid="UCsubject", title="Subject", subs="12345", views="987654", videos="120", hidden=False):
    stats = {"viewCount": views, "videoCount": videos, "hiddenSubscriberCount": hidden}
    if not hidden:
        stats["subscriberCount"] = subs
    return {"items": [{"id": cid, "snippet": {"title": title}, "statistics": stats}]}


class RecordingSession:
    """Answers YouTube calls from a table keyed by id/handle; RSS gets the fixture."""

    def __init__(self, channels=None, error=None):
        self.channels = channels or {}
        self.error = error
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        if "googleapis.com/youtube" in url:
            if self.error:
                return FakeResp(error=self.error)
            key = (params or {}).get("id") or (params or {}).get("forHandle")
            return FakeResp(json_data=self.channels.get(key, {"items": []}))
        if "itunes.apple.com" in url:
            return FakeResp(json_data={"results": [{"trackCount": 10}]})
        return FakeResp(content=FIXTURE)


# --------------------------------------------------------------------------- #
# fetch_youtube
# --------------------------------------------------------------------------- #
def test_fetch_by_id_parses_counts_and_keeps_key_out_of_the_url():
    sess = RecordingSession({"UCsubject": channel()})
    res = fetch_youtube("UCsubject", None, FAKE_KEY, session=sess)
    assert res.data == {
        "channel_id": "UCsubject",
        "title": "Subject",
        "subscriber_count": 12345,
        "hidden_subscriber_count": False,
        "view_count": 987654,
        "video_count": 120,
    }
    call = sess.calls[0]
    assert call["params"] == {"part": "snippet,statistics", "id": "UCsubject"}
    assert call["headers"]["X-Goog-Api-Key"] == FAKE_KEY
    assert FAKE_KEY not in call["url"] and FAKE_KEY not in json.dumps(call["params"])


def test_fetch_by_handle_uses_for_handle():
    sess = RecordingSession({"@peer": channel(cid="UCpeer")})
    res = fetch_youtube(None, "@peer", FAKE_KEY, session=sess)
    assert sess.calls[0]["params"]["forHandle"] == "@peer"
    assert res.data["channel_id"] == "UCpeer"


def test_hidden_subscriber_count_is_none_never_zero():
    sess = RecordingSession({"UChidden": channel(cid="UChidden", hidden=True, subs="0")})
    res = fetch_youtube("UChidden", None, FAKE_KEY, session=sess)
    assert res.data["subscriber_count"] is None
    assert res.data["hidden_subscriber_count"] is True
    assert res.data["view_count"] == 987654
    assert any("hides its subscriber count" in w for w in res.warnings)


def test_missing_key_skips_without_a_request():
    sess = RecordingSession({"UCsubject": channel()})
    res = fetch_youtube("UCsubject", None, None, session=sess)
    assert res.data is None
    assert sess.calls == []
    assert res.warnings == ["youtube: skipped for UCsubject (YOUTUBE_API_KEY unset)"]


def test_errors_never_echo_the_key():
    err = RuntimeError(f"403 Client Error for url ...?key={FAKE_KEY}")
    res = fetch_youtube("UCsubject", None, FAKE_KEY, session=RecordingSession(error=err))
    assert res.data is None
    assert FAKE_KEY not in " ".join(res.warnings)
    assert "[redacted]" in res.warnings[0]


def test_unknown_channel_warns():
    res = fetch_youtube(None, "@nobody", FAKE_KEY, session=RecordingSession())
    assert res.data is None
    assert res.warnings == ["youtube: no channel found for @nobody"]


def test_malformed_counts_become_none():
    sess = RecordingSession({"UCx": channel(cid="UCx", subs="n/a", views="-5", videos=None)})
    data = fetch_youtube("UCx", None, FAKE_KEY, session=sess).data
    assert (data["subscriber_count"], data["view_count"], data["video_count"]) == (None, None, None)


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
BASE = """
subject:
  name: S
  feed_url: https://example.com/s.xml
{extra}
peers: []
"""


def test_config_accepts_handle_with_or_without_at():
    cfg = parse_config(BASE.format(extra='  youtube_handle: "@show"'))
    assert cfg.subject.youtube_handle == "@show"
    cfg = parse_config(BASE.format(extra="  youtube_handle: show"))
    assert cfg.subject.youtube_handle == "@show"


def test_config_rejects_both_and_bad_channel_ids():
    with pytest.raises(ValueError, match="use one"):
        parse_config(BASE.format(extra="  youtube_channel_id: UCabc\n  youtube_handle: show"))
    with pytest.raises(ValueError, match="should start with 'UC'"):
        parse_config(BASE.format(extra="  youtube_channel_id: show"))


def test_config_without_youtube_is_unchanged():
    cfg = parse_config(BASE.format(extra=""))
    assert cfg.subject.youtube_channel_id is None and cfg.subject.youtube_handle is None


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("count", "rounded"), [(None, False), (0, False), (999, False), (1000, True), (12300, True)])
def test_rounding_threshold(count, rounded):
    assert subscriber_count_is_rounded(count) is rounded


def test_youtube_metrics_all_none_without_data():
    assert youtube_metrics(None) == {
        "youtube_subscribers": None,
        "youtube_total_views": None,
        "youtube_video_count": None,
    }


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
CONFIG = """
subject:
  name: Subject Show
  feed_url: https://example.com/subject.xml
  youtube_channel_id: UCsubject
peers:
  - name: Small Peer
    feed_url: https://example.com/small.xml
    youtube_handle: "@small"
  - name: Hidden Peer
    feed_url: https://example.com/hidden.xml
    youtube_channel_id: UChidden
  - name: No Channel Peer
    feed_url: https://example.com/none.xml
"""


def build(yt_key=FAKE_KEY):
    sess = RecordingSession(
        {
            "UCsubject": channel(subs="12300", views="1000000"),
            "@small": channel(cid="UCsmall", subs="850", views="2000000"),
            "UChidden": channel(cid="UChidden", hidden=True, views="500"),
        }
    )
    return build_benchmark(parse_config(CONFIG), session=sess, yt_key=yt_key), sess


def test_report_qualifies_rounded_subscribers_and_ranks_views():
    doc, _ = build()
    md = render_markdown(doc)
    assert "| YouTube subs | YouTube views |" in md
    assert "~12,300 | 1,000,000 |" in md  # rounded: qualified
    assert "| 850 | 2,000,000 |" in md  # under 1,000: exact
    assert "| N/A | 500 |" in md  # hidden: N/A, not 0
    ranking = md.split("### YouTube channel views")[1].split("###")[0]
    assert ranking.index("Small Peer") < ranking.index("Subject Show") < ranking.index("Hidden Peer")
    assert "No YouTube channel configured (not ranked): No Channel Peer." in md
    assert "subscribers about 12,300 (rounded by YouTube)" in md
    assert "ranked 2 of 3 shows with channel data" in md


def test_key_never_reaches_the_document():
    doc, _ = build()
    assert FAKE_KEY not in json.dumps(doc)


def test_no_key_degrades_to_na_with_warnings():
    doc, sess = build(yt_key=None)
    assert not [c for c in sess.calls if "googleapis" in c["url"]]
    subject = doc["shows"][0]
    assert subject["metrics"]["youtube_total_views"] is None
    assert any("YOUTUBE_API_KEY unset" in w for w in doc["warnings"])
    assert "No show had data for this metric" in render_markdown(doc)


def test_reports_without_youtube_config_have_no_youtube_columns():
    cfg = parse_config(BASE.format(extra=""))
    doc = build_benchmark(cfg, session=RecordingSession(), yt_key=FAKE_KEY)
    md = render_markdown(doc)
    assert "YouTube subs" not in md and "YouTube channel views" not in md


def test_cached_json_from_before_youtube_still_renders():
    doc, _ = build()
    for s in doc["shows"]:
        for k in ("youtube_channel_id", "youtube_handle"):
            s.pop(k)
        for k in ("youtube_subscribers", "youtube_total_views", "youtube_video_count"):
            s["metrics"].pop(k)
    md = render_markdown(doc)
    assert "YouTube subs" not in md
