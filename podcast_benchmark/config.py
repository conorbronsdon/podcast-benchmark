"""Config parsing for podcast-benchmark.

The config is a small YAML document. To keep dependencies to requests +
feedparser-free stdlib, we parse the constrained subset of YAML we need with
a tiny hand-rolled parser rather than pulling in PyYAML. The accepted shape:

    subject:
      name: Chain of Thought
      feed_url: https://feeds.transistor.fm/chain-of-thought
      apple_id: 1776879655   # optional

    peers:
      - name: Latent Space
        feed_url: https://api.substack.com/feed/podcast/1084089.rss
        apple_id: 1674008350
      - name: ...

If PyYAML is installed it is used automatically (more robust); otherwise the
built-in mini-parser handles this exact structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Show:
    name: str
    feed_url: str
    apple_id: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any], where: str) -> "Show":
        name = d.get("name")
        feed_url = d.get("feed_url")
        if not name:
            raise ValueError(f"config: {where} missing 'name'")
        if not feed_url:
            raise ValueError(f"config: {where} ('{name}') missing 'feed_url'")
        apple_id = d.get("apple_id")
        if apple_id is not None:
            apple_id = int(apple_id)
        return cls(name=str(name), feed_url=str(feed_url), apple_id=apple_id)


@dataclass
class BenchmarkConfig:
    subject: Show
    peers: list[Show]

    @property
    def all_shows(self) -> list[Show]:
        return [self.subject, *self.peers]


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ImportError:
        return _mini_yaml(text)


def _coerce_scalar(value: str) -> Any:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.isdigit():
        return int(value)
    return value


def _mini_yaml(text: str) -> dict[str, Any]:
    """Minimal YAML parser for the constrained config shape.

    Supports two-space-indented mappings and a 'peers:' list of '- key: val'
    items. Comments (#) and blank lines are ignored. This is deliberately not
    a general YAML parser; install PyYAML for anything fancier.
    """
    root: dict[str, Any] = {}
    current_top: str | None = None
    current_map: dict[str, Any] | None = None  # subject map
    peers: list[dict[str, Any]] = []
    current_peer: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            key = stripped.rstrip(":")
            current_top = key
            if key == "peers":
                root["peers"] = peers
                current_map = None
            else:
                current_map = {}
                root[key] = current_map
                current_peer = None
            continue

        if current_top == "peers":
            if stripped.startswith("- "):
                current_peer = {}
                peers.append(current_peer)
                stripped = stripped[2:].strip()
            if current_peer is not None and ":" in stripped:
                k, _, v = stripped.partition(":")
                current_peer[k.strip()] = _coerce_scalar(v)
            continue

        if current_map is not None and ":" in stripped:
            k, _, v = stripped.partition(":")
            current_map[k.strip()] = _coerce_scalar(v)

    return root


def parse_config(text: str) -> BenchmarkConfig:
    data = _load_yaml(text)
    if not isinstance(data, dict):
        raise ValueError("config: top level must be a mapping")

    subject_raw = data.get("subject")
    if not isinstance(subject_raw, dict):
        raise ValueError("config: missing 'subject' mapping")
    subject = Show.from_dict(subject_raw, "subject")

    peers_raw = data.get("peers") or []
    if not isinstance(peers_raw, list):
        raise ValueError("config: 'peers' must be a list")
    peers = [Show.from_dict(p, f"peers[{i}]") for i, p in enumerate(peers_raw)]

    return BenchmarkConfig(subject=subject, peers=peers)


def load_config(path: str) -> BenchmarkConfig:
    with open(path, "r", encoding="utf-8") as fh:
        return parse_config(fh.read())
