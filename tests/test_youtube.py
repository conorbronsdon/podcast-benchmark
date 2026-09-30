"""YouTube channel statistics: fetch, config, metrics and report. No network."""

import json
from pathlib import Path

import pytest
import requests

from podcast_benchmark.config import parse_config
from podcast_benchmark.metrics import subscriber_count_is_rounded, youtube_metrics
from podcast_benchmark.report import build_benchmark, render_markdown
from podcast_benchmark.sources import fetch_youtube

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()
FAKE_KEY = "test-key-not-real"

# Channel IDs are "UC" plus 22 characters.
SUBJECT = "UC" + "s" * 22
PEER = "UC" + "p" * 22
HIDDEN = "UC" + "h" * 22
OTHER = "UC" + "o" * 22


class FakeResp:
    def __init__(self, *, json_data=None, content=b"", error=None, status_code=200):
        self._json = json_data
        self.content = content
        self._error = error
        self.status_code = status_code

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._json


def channel(cid=SUBJECT, title="Subject", subs="12345", views="987654", videos="120", hidden=False):
    stats = {"viewCount": views, "videoCount": videos, "hiddenSubscriberCount": hidden}
    if not hidden:
        stats["subscriberCount"] = subs
    return {"items": [{"id": cid, "snippet": {"title": title}, "statistics": stats}]}


class RecordingSession:
    """Answers YouTube calls from a table keyed by id/handle; RSS gets the fixture."""

    def __init__(self, channels=None, error=None, raw=None):
        self.channels = channels or {}
        self.error = error
        self.raw = raw
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "headers": dict(headers or {}), "kwargs": kwargs}
        )
        if "googleapis.com/youtube" in url:
            if self.error:
                return FakeResp(error=self.error)
            if self.raw is not None:
                return self.raw
            key = (params or {}).get("id") or (params or {}).get("forHandle")
            return FakeResp(json_data=self.channels.get(key, {"items": []}))
        if "itunes.apple.com" in url:
            return FakeResp(json_data={"results": [{"trackCount": 10}]})
        return FakeResp(content=FIXTURE)


def yt(payload):
    """fetch_youtube against one canned response body."""
    return fetch_youtube(SUBJECT, None, FAKE_KEY, session=RecordingSession(raw=FakeResp(json_data=payload)))


# --------------------------------------------------------------------------- #
# fetch_youtube
# --------------------------------------------------------------------------- #
def test_fetch_by_id_parses_counts_and_keeps_key_out_of_the_url():
    sess = RecordingSession({SUBJECT: channel()})
    res = fetch_youtube(SUBJECT, None, FAKE_KEY, session=sess)
    assert res.data == {
        "channel_id": SUBJECT,
        "title": "Subject",
        "subscriber_count": 12345,
        "hidden_subscriber_count": False,
        "view_count": 987654,
        "video_count": 120,
    }
    call = sess.calls[0]
    assert call["params"] == {"part": "snippet,statistics", "id": SUBJECT}
    assert call["headers"]["X-Goog-Api-Key"] == FAKE_KEY
    assert call["kwargs"]["allow_redirects"] is False
    assert FAKE_KEY not in call["url"] and FAKE_KEY not in json.dumps(call["params"])


def test_fetch_by_handle_uses_for_handle():
    sess = RecordingSession({"@peer": channel(cid=PEER)})
    res = fetch_youtube(None, "@peer", FAKE_KEY, session=sess)
    assert sess.calls[0]["params"]["forHandle"] == "@peer"
    assert res.data["channel_id"] == PEER


def test_hidden_subscriber_count_is_none_never_zero():
    res = yt(channel(cid=SUBJECT, hidden=True, subs="0"))
    assert res.data["subscriber_count"] is None
    assert res.data["hidden_subscriber_count"] is True
    assert res.data["view_count"] == 987654
    assert any("hides its subscriber count" in w for w in res.warnings)


def test_missing_key_skips_without_a_request():
    sess = RecordingSession({SUBJECT: channel()})
    res = fetch_youtube(SUBJECT, None, None, session=sess)
    assert res.data is None
    assert sess.calls == []
    assert res.warnings == [f"youtube: skipped for {SUBJECT} (YOUTUBE_API_KEY unset)"]


@pytest.mark.parametrize("bad_key", ["FAKE-SECRET\r\n", "has space", "short", "k\x00ey-long-enough"])
def test_malformed_key_is_never_sent_or_echoed(bad_key):
    sess = RecordingSession({SUBJECT: channel()})
    res = fetch_youtube(SUBJECT, None, bad_key, session=sess)
    assert sess.calls == []
    assert res.data is None
    assert res.warnings == [f"youtube: skipped for {SUBJECT} (YOUTUBE_API_KEY is malformed)"]
    assert "SECRET" not in res.warnings[0]


def test_errors_carry_status_not_request_text():
    resp = requests.Response()
    resp.status_code = 403
    err = requests.HTTPError(f"403 Client Error for url ...?key={FAKE_KEY}", response=resp)
    res = fetch_youtube(SUBJECT, None, FAKE_KEY, session=RecordingSession(error=err))
    assert res.data is None
    assert res.warnings == [f"youtube: lookup for {SUBJECT} failed: HTTP 403"]


def test_connection_errors_name_only_the_exception_type():
    err = requests.ConnectionError(f"could not reach host with key {FAKE_KEY}")
    res = fetch_youtube(SUBJECT, None, FAKE_KEY, session=RecordingSession(error=err))
    assert res.warnings == [f"youtube: lookup for {SUBJECT} failed: ConnectionError"]


def test_redirects_are_refused():
    sess = RecordingSession(raw=FakeResp(status_code=302))
    res = fetch_youtube(SUBJECT, None, FAKE_KEY, session=sess)
    assert res.data is None
    assert res.warnings == [f"youtube: lookup for {SUBJECT} redirected (HTTP 302); refused"]


def test_real_session_does_not_follow_a_cross_host_redirect():
    """Transport-level check: requests itself must not re-send the key elsewhere."""
    seen = []

    class Adapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            seen.append((request.url, request.headers.get("X-Goog-Api-Key")))
            resp = requests.Response()
            resp.status_code = 302
            resp.headers["Location"] = "https://evil.example/steal"
            resp.url = request.url
            resp.request = request
            resp._content = b""
            return resp

        def close(self):
            pass

    sess = requests.Session()
    sess.mount("https://", Adapter())
    res = fetch_youtube(SUBJECT, None, FAKE_KEY, session=sess)
    assert res.data is None
    assert [host for host, _ in seen] == [seen[0][0]] and "googleapis.com" in seen[0][0]


def test_unknown_channel_warns():
    res = fetch_youtube(None, "@nobody", FAKE_KEY, session=RecordingSession())
    assert res.data is None
    assert res.warnings == ["youtube: no channel found for @nobody"]


@pytest.mark.parametrize("payload", [None, [], {"items": [None]}, {"items": "x"}, {"items": [{}, {}]}])
def test_malformed_response_shapes_degrade(payload):
    res = yt(payload)
    assert res.data is None
    assert len(res.warnings) == 1


def test_response_for_another_channel_is_rejected():
    res = yt(channel(cid=OTHER))
    assert res.data is None
    assert res.warnings == [f"youtube: response for {SUBJECT} named a different channel (N/A)"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("123", 123), ("0", 0), (5, 5), (True, None), (False, None), (0.9, None), (1.9, None),
     (float("inf"), None), ("-5", None), ("1e3", None), ("n/a", None), (None, None), ("１２", None)],
)
def test_count_coercion_never_invents_values(value, expected):
    data = yt(channel(views=value)).data
    assert data["view_count"] == expected


def test_bad_shapes_in_one_show_do_not_stop_the_others():
    class MixedSession(RecordingSession):
        def get(self, url, params=None, headers=None, timeout=None, **kwargs):
            if "googleapis.com/youtube" in url and (params or {}).get("id") == SUBJECT:
                return FakeResp(json_data={"items": [None]})
            return super().get(url, params=params, headers=headers, timeout=timeout, **kwargs)

    cfg = parse_config(CONFIG)
    doc = build_benchmark(cfg, session=MixedSession({"@small": channel(cid=PEER, views="10")}), yt_key=FAKE_KEY)
    by_name = {s["name"]: s["metrics"] for s in doc["shows"]}
    assert by_name["Subject Show"]["youtube_total_views"] is None
    assert by_name["Small Peer"]["youtube_total_views"] == 10


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


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (f"  youtube_channel_id: {SUBJECT}\n  youtube_handle: show", "use one"),
        ("  youtube_channel_id: show", "one channel ID"),
        (f"  youtube_channel_id: {SUBJECT},{PEER}", "one channel ID"),
        ('  youtube_handle: "@a b"', "not a valid handle"),
    ],
)
def test_config_rejects_ambiguous_or_malformed_channels(extra, message):
    with pytest.raises(ValueError, match=message):
        parse_config(BASE.format(extra=extra))


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
        "youtube_subscribers_hidden": False,
    }


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
CONFIG = f"""
subject:
  name: Subject Show
  feed_url: https://example.com/subject.xml
  youtube_channel_id: {SUBJECT}
peers:
  - name: Small Peer
    feed_url: https://example.com/small.xml
    youtube_handle: "@small"
  - name: Hidden Peer
    feed_url: https://example.com/hidden.xml
    youtube_channel_id: {HIDDEN}
  - name: No Channel Peer
    feed_url: https://example.com/none.xml
"""


def build(yt_key=FAKE_KEY, subject=None):
    sess = RecordingSession(
        {
            SUBJECT: subject or channel(subs="12300", views="1000000"),
            "@small": channel(cid=PEER, subs="850", views="2000000"),
            HIDDEN: channel(cid=HIDDEN, hidden=True, views="500"),
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


def test_findings_say_hidden_only_when_youtube_says_so():
    stats_without_subs = {"items": [{"id": SUBJECT, "statistics": {"viewCount": "7", "hiddenSubscriberCount": False}}]}
    md = render_markdown(build(subject=stats_without_subs)[0])
    assert "subscribers N/A." in md and "hidden by the channel" not in md
    md = render_markdown(build(subject=channel(hidden=True, views="7"))[0])
    assert "subscribers hidden by the channel." in md


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
        for k in ("youtube_subscribers", "youtube_total_views", "youtube_video_count", "youtube_subscribers_hidden"):
            s["metrics"].pop(k)
    md = render_markdown(doc)
    assert "YouTube subs" not in md


def test_handle_lookup_with_several_channels_is_rejected():
    two = {"items": channel(cid=PEER)["items"] + channel(cid=OTHER)["items"]}
    res = fetch_youtube(None, "@peer", FAKE_KEY, session=RecordingSession({"@peer": two}))
    assert res.data is None
    assert res.warnings == ["youtube: unexpected response shape for @peer (N/A)"]
