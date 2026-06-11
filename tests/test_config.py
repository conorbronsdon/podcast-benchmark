"""Unit tests for config parsing (mini-YAML and PyYAML paths)."""

import pytest

from podcast_benchmark.config import parse_config

SAMPLE = """
subject:
  name: Chain of Thought
  feed_url: https://feeds.transistor.fm/chain-of-thought
  apple_id: 1776879655

peers:
  - name: Latent Space
    feed_url: https://api.substack.com/feed/podcast/1084089.rss
    apple_id: 1674008350
  - name: Practical AI  # has no apple id on purpose
    feed_url: https://feeds.transistor.fm/practical-ai
"""


def test_parse_subject_and_peers():
    cfg = parse_config(SAMPLE)
    assert cfg.subject.name == "Chain of Thought"
    assert cfg.subject.apple_id == 1776879655
    assert len(cfg.peers) == 2
    assert cfg.peers[0].name == "Latent Space"
    assert cfg.peers[0].apple_id == 1674008350
    # Comment stripped, apple_id optional.
    assert cfg.peers[1].name == "Practical AI"
    assert cfg.peers[1].apple_id is None
    assert len(cfg.all_shows) == 3


def test_missing_subject_raises():
    with pytest.raises(ValueError):
        parse_config("peers:\n  - name: X\n    feed_url: http://x\n")


def test_missing_feed_url_raises():
    bad = "subject:\n  name: NoFeed\n"
    with pytest.raises(ValueError):
        parse_config(bad)


def test_hash_in_url_is_not_a_comment():
    cfg_text = (
        "subject:\n"
        "  name: Frag Show\n"
        "  feed_url: https://example.com/feed.rss#fragment  # trailing comment\n"
    )
    cfg = parse_config(cfg_text)
    assert cfg.subject.feed_url == "https://example.com/feed.rss#fragment"
