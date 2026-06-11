"""Unit + end-to-end tests for sponsor-intel extraction. No network."""

import json
from pathlib import Path

import pytest

from podcast_benchmark.config import parse_config
from podcast_benchmark.sources import parse_rss_bytes
from podcast_benchmark.sponsors import (
    EVIDENCE_MAX_CHARS,
    aggregate_sponsors,
    build_sponsor_intel,
    extract_link_signals,
    extract_sponsor_mentions,
    render_sponsors_markdown,
    scan_episode,
    scan_show,
    strip_html,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "sponsor_feed.xml").read_bytes()


def names(text):
    return [m["name"] for m in extract_sponsor_mentions(text)]


# --------------------------------------------------------------------------- #
# Phrase patterns
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected_name,expected_kind",
    [
        ("This episode is sponsored by Galileo.", "Galileo", "sponsored_by"),
        (
            "Brought to you by Weights & Biases — try it free",
            "Weights & Biases",
            "brought_to_you_by",
        ),
        (
            "Thanks to our sponsor Datadog for supporting the show",
            "Datadog",
            "thanks_to_sponsor",
        ),
        (
            "Thank you to our sponsors: LaunchDarkly",
            "LaunchDarkly",
            "thanks_to_sponsor",
        ),
        ("This episode is supported by Temporal.", "Temporal", "supported_by"),
        ("Presented by RunPod", "RunPod", "presented_by"),
        ("Partner: Neo4j", "Neo4j", "partner_label"),
        (
            "In partnership with Shopify, we built a storefront.",
            "Shopify",
            "in_partnership_with",
        ),
    ],
)
def test_each_phrase_pattern(text, expected_name, expected_kind):
    mentions = extract_sponsor_mentions(text)
    assert len(mentions) == 1
    assert mentions[0]["name"] == expected_name
    assert mentions[0]["kind"] == expected_kind


# --------------------------------------------------------------------------- #
# Name cleaning
# --------------------------------------------------------------------------- #
def test_cleaning_strips_trailing_punctuation():
    assert names("Sponsored by Vanta!") == ["Vanta"]


def test_cleaning_strips_trailing_link():
    assert names("Brought to you by Sentry https://sentry.io/promo") == ["Sentry"]


def test_cleaning_strips_friends_at_filler():
    assert names("Brought to you by our friends at Modal.") == ["Modal"]


def test_cleaning_keeps_hyphenated_names():
    assert names("Sponsored by T-Mobile.") == ["T-Mobile"]


def test_cleaning_cuts_descriptor_clause():
    assert names("Sponsored by Galileo, the AI evaluation platform.") == ["Galileo"]


def test_sentence_length_tail_is_not_a_name():
    # A tail that cleans to more than NAME_MAX_WORDS words is dropped rather
    # than reported as a garbage "sponsor".
    text = (
        "Sponsored by passionate generous thoughtful brilliant wonderful "
        "amazing fantastic incredible humans everywhere"
    )
    assert names(text) == []


def test_sponsored_by_people_is_not_a_sponsor():
    text = "Sponsored by people who believe machine learning should be open."
    assert names(text) == []


# --------------------------------------------------------------------------- #
# Multi-sponsor and dedup
# --------------------------------------------------------------------------- #
def test_multi_sponsor_and_split():
    assert names("Sponsored by Datadog and LaunchDarkly.") == [
        "Datadog",
        "LaunchDarkly",
    ]


def test_multi_sponsor_separate_phrases():
    text = (
        "Brought to you by Galileo. Later in the show, thanks to our "
        "sponsor Temporal for the support."
    )
    assert names(text) == ["Galileo", "Temporal"]


def test_same_sponsor_twice_dedupes_within_text():
    text = "Sponsored by Galileo. This episode is brought to you by Galileo."
    assert names(text) == ["Galileo"]


def test_dedup_is_case_and_punctuation_insensitive():
    text = "Sponsored by GALILEO. Also brought to you by Galileo."
    assert len(extract_sponsor_mentions(text)) == 1


# --------------------------------------------------------------------------- #
# False-positive guards
# --------------------------------------------------------------------------- #
def test_guest_company_without_sponsor_phrasing_not_extracted():
    text = (
        "We talk with Jane Doe, CTO of Acme Corp, about how Acme Corp "
        "ships evals to production."
    )
    assert extract_sponsor_mentions(text) == []


def test_supported_by_listeners_not_extracted():
    assert extract_sponsor_mentions("This show is supported by our listeners too.") == []


def test_prose_presented_by_not_extracted():
    # Real construction from peer feeds: a topic, not a sponsor.
    assert names("We explore the challenges presented by Generative AI.") == []
    assert names("Link to the slide deck presented by Nathan Labenz.") == []


def test_announcement_presented_by_is_extracted():
    # Same phrase without a prose noun before it is a real sponsor read.
    assert names("The Expo has been announced, presented by AutoGPT.") == ["AutoGPT"]


def test_lowercase_tail_is_prose_not_a_sponsor():
    assert names("These owners are supported by armies of AI agents.") == []
    assert names("In partnership with philanthropic and OpenAI") == ["OpenAI"]


def test_leading_article_with_proper_noun_is_kept():
    assert names("Brought to you by the Turpentine Media network.") == [
        "the Turpentine Media network"
    ]


def test_lowercase_use_code_phrase_is_not_a_promo_code():
    # "use code" followed by a plain lowercase word is prose, not a code.
    assert extract_sponsor_mentions("We use code review heavily on the team.") == []


# --------------------------------------------------------------------------- #
# Promo codes
# --------------------------------------------------------------------------- #
def test_promo_code_with_domain_uses_domain_as_candidate():
    mentions = extract_sponsor_mentions("Use code FIXTURE20 at galileo.ai for 20% off.")
    assert len(mentions) == 1
    assert mentions[0]["kind"] == "promo_code"
    assert mentions[0]["name"] == "galileo.ai"
    assert mentions[0]["code"] == "FIXTURE20"


def test_promo_code_without_domain_falls_back_to_code():
    mentions = extract_sponsor_mentions("Use code COTPOD at checkout.")
    assert len(mentions) == 1
    assert mentions[0]["name"] == "COTPOD"
    assert mentions[0]["code"] == "COTPOD"


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #
def test_evidence_is_verbatim_and_capped():
    text = "x " * 100 + "Sponsored by Galileo. " + "y " * 200
    mentions = extract_sponsor_mentions(text)
    assert len(mentions) == 1
    ev = mentions[0]["evidence"]
    assert len(ev) <= EVIDENCE_MAX_CHARS
    assert ev in text  # verbatim substring of the scanned text
    assert "Sponsored by Galileo" in ev


def test_html_is_stripped_before_matching():
    desc = '<p>Sponsored by <a href="https://galileo.ai?utm_source=x">Galileo</a></p>'
    scanned = scan_episode("Ep", desc)
    assert [m["name"] for m in scanned["mentions"]] == ["Galileo"]
    assert "<a" not in scanned["mentions"][0]["evidence"]


def test_strip_html_unescapes_entities():
    assert strip_html("Weights &amp; Biases <br/> rocks") == "Weights & Biases rocks"


# --------------------------------------------------------------------------- #
# Link signals
# --------------------------------------------------------------------------- #
def test_link_signals_utm_and_shortener_detected_plain_link_ignored():
    desc = (
        'Visit <a href="https://vendor.com/?utm_source=pod">here</a> or '
        "https://bit.ly/xyz or https://example.com/plain"
    )
    signals = extract_link_signals(desc)
    reasons = {s["reason"] for s in signals}
    assert reasons == {"utm", "shortener"}
    assert all("example.com/plain" not in s["url"] for s in signals)


def test_link_signals_never_become_sponsor_rows():
    rss = parse_rss_bytes(FIXTURE, include_text=True)
    scan = scan_show("Fixture", rss)
    sponsors = aggregate_sponsors([scan])
    assert scan["link_signals"]["episodes_with_link_signals"] == 2
    for sp in sponsors:
        assert sp["kinds"] != ["link_signal"]
        assert "bit.ly" not in sp["name"]


# --------------------------------------------------------------------------- #
# Show scan + aggregation
# --------------------------------------------------------------------------- #
def test_scan_show_on_fixture_feed():
    rss = parse_rss_bytes(FIXTURE, include_text=True)
    scan = scan_show("Fixture", rss)
    assert scan["episodes_scanned"] == 4
    # Ep 4, Ep 3, and Ep 1 carry sponsor language; Ep 2 (guest only) does not.
    assert scan["episodes_with_mentions"] == 3
    titles = [h["episode_title"] for h in scan["mention_hits"]]
    assert "Ep 2: A guest, no sponsor" not in titles


def test_aggregate_dedupes_across_episodes_and_tracks_dates():
    rss = parse_rss_bytes(FIXTURE, include_text=True)
    sponsors = aggregate_sponsors([scan_show("Fixture", rss)])
    galileo = next(s for s in sponsors if s["name"] == "Galileo")
    # Mentioned in Ep 4 (2026-06-01) and Ep 3 (2026-05-04): one row, two eps.
    assert galileo["episode_count"] == 2
    assert galileo["shows"] == ["Fixture"]
    assert galileo["first_seen"] == "2026-05-04"
    assert galileo["last_seen"] == "2026-06-01"
    assert len(galileo["evidence"]) == 2


def test_aggregate_ranks_breadth_then_recency_deterministically():
    def show(name, sponsor, date):
        return {
            "name": name,
            "mention_hits": [
                {
                    "episode_title": "ep",
                    "pubdate": f"{date}T00:00:00+00:00",
                    "mentions": [
                        {
                            "kind": "sponsored_by",
                            "name": sponsor,
                            "normalized": sponsor.lower(),
                            "evidence": f"Sponsored by {sponsor}",
                        }
                    ],
                }
            ],
        }

    scans = [
        show("Show A", "Solo", "2026-06-01"),
        show("Show B", "Wide", "2026-01-01"),
        show("Show C", "Wide", "2026-03-01"),
        show("Show A", "Older", "2026-06-01"),
    ]
    ranked = [s["name"] for s in aggregate_sponsors(scans)]
    # Wide is on two shows -> first despite older dates. Solo vs Older tie on
    # breadth, recency, and episode count -> name (normalized) ascending.
    assert ranked == ["Wide", "Older", "Solo"]


# --------------------------------------------------------------------------- #
# End-to-end with mocked network
# --------------------------------------------------------------------------- #
CONFIG = """
subject:
  name: Subject Show
  feed_url: https://example.com/subject.xml
peers:
  - name: Peer Show
    feed_url: https://example.com/peer.xml
  - name: Broken Feed
    feed_url: https://example.com/broken.xml
"""


class FakeResp:
    def __init__(self, content=b""):
        self.content = content

    def raise_for_status(self):
        pass


class FakeSession:
    """Serves the sponsor fixture for two shows and fails the third."""

    def get(self, url, params=None, headers=None, timeout=None):
        if "broken" in url:
            raise ConnectionError("boom")
        return FakeResp(content=FIXTURE)


def test_build_sponsor_intel_end_to_end():
    cfg = parse_config(CONFIG)
    doc = build_sponsor_intel(cfg, session=FakeSession())

    assert [s["name"] for s in doc["shows"]] == [
        "Subject Show",
        "Peer Show",
        "Broken Feed",
    ]
    # Both healthy shows carry the same sponsors -> breadth of 2.
    galileo = next(s for s in doc["sponsors"] if s["name"] == "Galileo")
    assert galileo["shows"] == ["Peer Show", "Subject Show"]
    assert galileo["episode_count"] == 4  # 2 episodes x 2 shows

    # The broken feed degrades to zero episodes plus a warning, not a crash.
    broken = doc["shows"][2]
    assert broken["episodes_scanned"] == 0
    assert any("broken" in w for w in doc["warnings"])

    # JSON-serializable and stable.
    assert json.loads(json.dumps(doc)) == json.loads(json.dumps(doc))

    md = render_sponsors_markdown(doc)
    assert "# Sponsor Intel: Subject Show peer set" in md
    assert "audio-only" in md  # the big caveat is in the report
    assert "| Galileo |" in md
    assert "Methodology and caveats" in md


def test_no_hits_is_reported_honestly():
    doc = {
        "generated_at": "2026-06-11T00:00:00Z",
        "tool_version": "0.2.0",
        "subject": "Quiet Show",
        "shows": [
            {
                "name": "Quiet Show",
                "episodes_scanned": 10,
                "episodes_with_mentions": 0,
                "mention_hits": [],
                "link_signals": {"episodes_with_link_signals": 0, "examples": []},
            }
        ],
        "sponsors": [],
        "warnings": [],
        "methodology": {"notes": ["note"]},
    }
    md = render_sponsors_markdown(doc)
    assert "No sponsor language was detected" in md
    assert "not that they have no sponsors" in md
