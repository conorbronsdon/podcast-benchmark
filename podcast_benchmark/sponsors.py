"""Sponsor-intel extraction from public episode descriptions and titles.

Scans every episode a feed currently serves for sponsorship language
("sponsored by", "brought to you by", promo codes, ...) and aggregates the
candidates across shows: which shows carry a sponsor, how many episodes, and
how recently. Recency and breadth are the buying signals.

Everything here is a heuristic regex over public RSS text. The honest
limitations, stated up front in the report too:

  - Many sponsor reads are AUDIO-ONLY and never appear in the description.
    Absence of a detection is NOT absence of sponsorship.
  - Extracted names are candidates that need human confirmation.
  - The scan only covers episodes the feed currently serves; hosts that cap
    the feed window hide older sponsorships.

Extraction functions are pure (text in, mentions out) so they are testable
on fixture descriptions without any network.
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from . import __version__
from .config import BenchmarkConfig
from .sources import fetch_rss

EVIDENCE_MAX_CHARS = 200
NAME_MAX_WORDS = 8
LINK_EXAMPLES_PER_SHOW = 5

# --------------------------------------------------------------------------- #
# Phrase patterns
# --------------------------------------------------------------------------- #
# Each pattern captures up to 100 chars of raw tail after the phrase; the tail
# is then cleaned down to a candidate name by clean_candidate().
_TAIL = r"(?P<tail>[^\n]{1,100})"

PHRASE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sponsored_by", re.compile(r"\bsponsored\s+by[:\s]+" + _TAIL, re.I)),
    ("brought_to_you_by", re.compile(r"\bbrought\s+to\s+you\s+by[:\s]+" + _TAIL, re.I)),
    (
        "thanks_to_sponsor",
        re.compile(
            r"\bthank(?:s|\s+you)\s+to\s+our\s+sponsors?\b[:,\s]*" + _TAIL, re.I
        ),
    ),
    (
        "supported_by",
        re.compile(r"\b(?:is|are)\s+supported\s+by[:\s]+" + _TAIL, re.I),
    ),
    ("presented_by", re.compile(r"\bpresented\s+by[:\s]+" + _TAIL, re.I)),
    ("partner_label", re.compile(r"\bpartners?:\s*" + _TAIL, re.I)),
    (
        "in_partnership_with",
        re.compile(r"\bin\s+partnership\s+with\s+" + _TAIL, re.I),
    ),
]

# Promo codes are almost always SHOUTED (uppercase/digits), so the code token
# is matched case-sensitively even though the lead-in phrase is not.
PROMO_CODE_PATTERN = re.compile(
    r"\buse\s+(?:promo\s+|coupon\s+|discount\s+|the\s+)?code\s+"
    r"(?P<code>[A-Z0-9][A-Z0-9_-]{2,19})\b",
    re.I,
)
_CODE_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,19}$")
# "use code X at vendor.com" -> the vendor domain is the better candidate name.
_CODE_DOMAIN = re.compile(
    r"^\s*at\s+(?:https?://)?(?:www\.)?(?P<domain>[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})",
    re.I,
)

# Candidate cleaning.
_URL_IN_NAME = re.compile(r"(?:https?://|www\.)\S+", re.I)
_FILLER_PREFIX = re.compile(
    r"^(?:our|the)\s+(?:good\s+|great\s+|fine\s+)?"
    r"(?:friends?|partners?|sponsors?|team|folks|people)\s+"
    r"(?:at|from|over\s+at)\s+",
    re.I,
)
_LEADING_SPONSOR_WORD = re.compile(r"^our\s+sponsors?[,:\s]+", re.I)
# Cut the tail at the first hard delimiter or connector word. Spaced dashes
# only, so hyphenated names (T-Mobile) survive.
_NAME_CUT = re.compile(
    r"[.,;:!?|()\[\]\"]"
    r"|\s+[—–-]\s+"
    r"|\s+(?:for|to|who|whose|where|which|use|visit|go|check|and\s+by|at\s+https?|at\s+www)\b",
    re.I,
)
_TRAILING_JUNK = re.compile(r"[\s.,;:!?|'\"—–-]+$")
_AND_SPLIT = re.compile(r"\s+and\s+", re.I)

# Candidates that are sponsorship language but not sponsors ("supported by
# our listeners"). Matched against the normalized name as exact-or-prefix so
# trailing words ("our listeners too") still get caught.
_NON_SPONSOR_ROOTS = (
    "listeners",
    "our listeners",
    "you",
    "viewers",
    "our viewers",
    "supporters",
    "our supporters",
    "patrons",
    "our patrons",
    "our patreon",
    "our members",
    "people",
    "everyone",
    "our community",
    "the community",
)


def _is_non_sponsor(normalized: str) -> bool:
    return any(
        normalized == root or normalized.startswith(root + " ")
        for root in _NON_SPONSOR_ROOTS
    )


# "presented by" / "supported by" are common outside sponsorship ("challenges
# presented by generative AI", "the slide deck presented by Nathan"). When the
# word right before the phrase is one of these, it is prose, not a sponsor
# read. Confirmed against real peer feeds: TWIML and Latent Space descriptions
# are full of exactly this construction.
_PROSE_PRECEDING_WORDS = {
    "challenges",
    "complexities",
    "issues",
    "opportunities",
    "problems",
    "questions",
    "risks",
    "deck",
    "slides",
    "paper",
    "papers",
    "poster",
    "posters",
    "research",
    "talk",
    "talks",
    "work",
    "works",
}
_PROSE_GUARDED_KINDS = {"presented_by", "supported_by"}


def _preceded_by_prose(text: str, start: int) -> bool:
    before = text[:start].rstrip()
    last_word = re.split(r"[^\w]+", before)[-1] if before else ""
    return last_word.lower() in _PROSE_PRECEDING_WORDS

# Link signals: weak evidence, recorded but never aggregated into sponsors.
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>)]+", re.I)
_SHORTENER_DOMAINS = {
    "bit.ly",
    "buff.ly",
    "geni.us",
    "hubs.la",
    "hubs.ly",
    "lnk.to",
    "rb.gy",
    "shorturl.at",
    "t.co",
    "tinyurl.com",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Pure extraction functions
# --------------------------------------------------------------------------- #
def strip_html(text: str) -> str:
    """Flatten HTML-ish description markup to plain single-line text."""
    if not text:
        return ""
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    return _WS.sub(" ", text).strip()


def normalize_name(name: str) -> str:
    """Casefold and squash punctuation so 'Galileo.' and 'galileo' dedupe."""
    return _WS.sub(" ", re.sub(r"[^a-z0-9&]+", " ", name.casefold())).strip()


def _starts_proper(part: str) -> bool:
    """True when the candidate looks like a proper noun (allowing a leading
    article: 'the Turpentine Media network' is a real sponsor read)."""
    tokens = part.split()
    if tokens[0].lower() in {"the", "a", "an"} and len(tokens) > 1:
        head = tokens[1]
    else:
        head = tokens[0]
    return head[0].isupper() or head[0].isdigit()


def clean_candidate(tail: str) -> list[str]:
    """Clean the raw text after a sponsor phrase into candidate name(s).

    Returns a list because 'sponsored by Foo and Bar' is two sponsors. The
    split is on the word 'and' only; ampersand names (Weights & Biases)
    survive intact. Returns [] when nothing name-like remains.
    """
    tail = _URL_IN_NAME.sub(" ", tail)
    cut = _NAME_CUT.search(tail)
    if cut:
        tail = tail[: cut.start()]
    tail = _FILLER_PREFIX.sub("", tail)
    tail = _LEADING_SPONSOR_WORD.sub("", tail)

    names: list[str] = []
    for part in _AND_SPLIT.split(tail):
        part = _TRAILING_JUNK.sub("", part.strip())
        part = part.lstrip("'\"").strip()
        if len(part) < 2:
            continue
        if len(part.split()) > NAME_MAX_WORDS:
            continue  # ran into a sentence, not a name
        if not _starts_proper(part):
            # Sponsor reads name proper nouns. Lowercase tails ("generative
            # AI", "your keyboard") are prose. Cost: an all-lowercase brand
            # name would be missed; stated in the methodology notes.
            continue
        if _is_non_sponsor(normalize_name(part)):
            continue
        names.append(part)
    return names


def _evidence(text: str, start: int) -> str:
    """Verbatim snippet of the scanned text around a match, <= 200 chars."""
    lo = max(0, start - 40)
    return text[lo : lo + EVIDENCE_MAX_CHARS].strip()[:EVIDENCE_MAX_CHARS]


def extract_sponsor_mentions(text: str) -> list[dict[str, Any]]:
    """Find sponsor mentions in already-flattened text. Pure function.

    Returns a list of {kind, name, normalized, evidence} dicts (promo-code
    hits also carry "code"), deduped by normalized name within the text.
    """
    mentions: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, name: str, start: int, code: str | None = None) -> None:
        norm = normalize_name(name)
        if not norm or norm in seen:
            return
        seen.add(norm)
        m: dict[str, Any] = {
            "kind": kind,
            "name": name,
            "normalized": norm,
            "evidence": _evidence(text, start),
        }
        if code:
            m["code"] = code
        mentions.append(m)

    for kind, pattern in PHRASE_PATTERNS:
        for match in pattern.finditer(text):
            if kind in _PROSE_GUARDED_KINDS and _preceded_by_prose(text, match.start()):
                continue
            for name in clean_candidate(match.group("tail")):
                add(kind, name, match.start())

    for match in PROMO_CODE_PATTERN.finditer(text):
        code = match.group("code")
        if not _CODE_TOKEN.match(code):
            continue  # lowercase word, not a shouted promo code
        after = text[match.end() : match.end() + 60]
        dom = _CODE_DOMAIN.match(after)
        name = dom.group("domain").lower() if dom else code
        add("promo_code", name, match.start(), code=code)

    return mentions


def extract_link_signals(description_html: str) -> list[dict[str, str]]:
    """UTM-tagged and shortener URLs in the raw description.

    These are weak signals (shows tag their own links too), so callers record
    them as supporting evidence and never aggregate them into sponsor rows.
    """
    signals: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _URL_PATTERN.finditer(description_html or ""):
        url = match.group(0).rstrip(".,;:!?")
        if url in seen:
            continue
        host = (urlparse(url).hostname or "").removeprefix("www.")
        reason = None
        if "utm_" in url:
            reason = "utm"
        elif host in _SHORTENER_DOMAINS:
            reason = "shortener"
        if reason:
            seen.add(url)
            signals.append({"url": url[:EVIDENCE_MAX_CHARS], "reason": reason})
    return signals


def scan_episode(title: str, description_html: str) -> dict[str, Any]:
    """Scan one episode's title + description. Pure function."""
    text = strip_html(f"{title or ''}\n{description_html or ''}".replace("\n", " "))
    return {
        "mentions": extract_sponsor_mentions(text),
        "link_signals": extract_link_signals(description_html or ""),
    }


# --------------------------------------------------------------------------- #
# Per-show scan + cross-show aggregation
# --------------------------------------------------------------------------- #
def scan_show(name: str, rss_data: dict[str, Any]) -> dict[str, Any]:
    """Scan every episode of one parsed feed (needs include_text=True data)."""
    hits: list[dict[str, Any]] = []
    link_episodes = 0
    link_examples: list[dict[str, str]] = []

    episodes = rss_data.get("episodes", [])
    for ep in episodes:
        scanned = scan_episode(ep.get("title", ""), ep.get("description", ""))
        if scanned["link_signals"]:
            link_episodes += 1
            for sig in scanned["link_signals"]:
                if len(link_examples) < LINK_EXAMPLES_PER_SHOW:
                    link_examples.append(
                        {"episode_title": ep.get("title", ""), **sig}
                    )
        if scanned["mentions"]:
            hits.append(
                {
                    "episode_title": ep.get("title", ""),
                    "pubdate": ep.get("pubdate"),
                    "mentions": scanned["mentions"],
                }
            )

    return {
        "name": name,
        "episodes_scanned": len(episodes),
        "episodes_with_mentions": len(hits),
        "mention_hits": hits,
        "link_signals": {
            "episodes_with_link_signals": link_episodes,
            "examples": link_examples,
        },
    }


def _date_of(pubdate_iso: str | None) -> str | None:
    return pubdate_iso[:10] if pubdate_iso else None


def aggregate_sponsors(show_scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate mentions across shows into ranked sponsor candidates.

    Sorted by (number of shows desc, last-seen date desc, episode count desc,
    name asc) so the output is deterministic and the strongest buying signals
    (breadth + recency) come first.
    """
    by_norm: dict[str, dict[str, Any]] = {}
    for scan in show_scans:
        for hit in scan.get("mention_hits", []):
            date = _date_of(hit.get("pubdate"))
            for m in hit["mentions"]:
                entry = by_norm.setdefault(
                    m["normalized"],
                    {
                        "name": m["name"],
                        "normalized": m["normalized"],
                        "shows": [],
                        "episode_count": 0,
                        "first_seen": None,
                        "last_seen": None,
                        "kinds": [],
                        "evidence": [],
                    },
                )
                if scan["name"] not in entry["shows"]:
                    entry["shows"].append(scan["name"])
                entry["episode_count"] += 1
                if m["kind"] not in entry["kinds"]:
                    entry["kinds"].append(m["kind"])
                if date:
                    if entry["first_seen"] is None or date < entry["first_seen"]:
                        entry["first_seen"] = date
                    if entry["last_seen"] is None or date > entry["last_seen"]:
                        entry["last_seen"] = date
                entry["evidence"].append(
                    {
                        "show": scan["name"],
                        "episode_title": hit["episode_title"],
                        "date": date,
                        "kind": m["kind"],
                        "snippet": m["evidence"],
                    }
                )

    sponsors = list(by_norm.values())
    for s in sponsors:
        s["shows"].sort()
        s["kinds"].sort()
    # Stable sorts, applied lowest-priority first: name asc, episode count
    # desc, last-seen desc, show breadth desc.
    sponsors.sort(key=lambda s: s["normalized"])
    sponsors.sort(key=lambda s: s["episode_count"], reverse=True)
    sponsors.sort(key=lambda s: s["last_seen"] or "", reverse=True)
    sponsors.sort(key=lambda s: len(s["shows"]), reverse=True)
    return sponsors


# --------------------------------------------------------------------------- #
# Build + render
# --------------------------------------------------------------------------- #
METHODOLOGY_NOTES = [
    "Detection is heuristic regex over public episode descriptions and "
    "titles fetched from each show's live RSS feed. Nothing is scraped from "
    "players or charts.",
    "MANY SPONSOR READS ARE AUDIO-ONLY and never appear in the description. "
    "Absence of a detection is NOT absence of sponsorship. Treat this list "
    "as a floor, not a census.",
    "Extracted names are candidates, not confirmations. A human should "
    "verify each one against the actual episode before outreach.",
    "The scan covers only the episodes a feed currently serves. Hosts that "
    "cap the feed window hide older sponsorships.",
    "Promo codes with no adjacent vendor domain are listed under the code "
    "itself and need a human to map them to the company.",
    "UTM-tagged and shortener links are recorded per show as weak signals "
    "but never aggregated into sponsor rows, because shows tag their own "
    "marketing links too.",
    "Multi-sponsor reads of the form 'X and Y' are split on the word 'and'; "
    "ampersand names (e.g. Weights & Biases) are kept intact.",
    "Candidates must start with a capital letter or digit (after an optional "
    "article), and 'presented by'/'supported by' preceded by prose nouns "
    "('challenges presented by') are skipped. An all-lowercase brand name "
    "would be missed by the first guard.",
]


def build_sponsor_intel(
    config: BenchmarkConfig,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch every show's feed, scan it, and aggregate sponsor candidates."""
    sess = session or requests.Session()
    warnings: list[str] = []
    show_scans: list[dict[str, Any]] = []

    for show in config.all_shows:
        rr = fetch_rss(show.feed_url, session=sess, include_text=True)
        warnings.extend(f"[{show.name}] {w}" for w in rr.warnings)
        if not rr.ok:
            # Degrade per feed: the show appears with zero episodes scanned
            # and the failure is in warnings, never dropped silently.
            show_scans.append(scan_show(show.name, {"episodes": []}))
            continue
        show_scans.append(scan_show(show.name, rr.data))

    return {
        "generated_at": _now_iso(),
        "tool_version": __version__,
        "subject": config.subject.name,
        "shows": show_scans,
        "sponsors": aggregate_sponsors(show_scans),
        "warnings": warnings,
        "methodology": {"notes": METHODOLOGY_NOTES},
    }


def render_sponsors_markdown(doc: dict[str, Any]) -> str:
    out: list[str] = []
    out.append(f"# Sponsor Intel: {doc['subject']} peer set")
    out.append("")
    out.append(
        f"Generated {doc['generated_at']} by podcast-benchmark "
        f"v{doc['tool_version']}."
    )
    out.append("")
    out.append(
        "**Read this first:** many sponsor reads are audio-only and never "
        "appear in episode descriptions, so absence of a detection here is "
        "NOT absence of sponsorship. This list is a floor, not a census, and "
        "every name below is a heuristic candidate that needs human "
        "confirmation."
    )
    out.append("")

    out.append("## Scan summary")
    out.append("")
    out.append("| Show | Episodes scanned | Episodes with sponsor signals |")
    out.append("| ---- | ---- | ---- |")
    for s in doc["shows"]:
        out.append(
            f"| {s['name']} | {s['episodes_scanned']} | "
            f"{s['episodes_with_mentions']} |"
        )
    out.append("")

    out.append("## Sponsor candidates")
    out.append("")
    sponsors = doc["sponsors"]
    if not sponsors:
        out.append(
            "No sponsor language was detected in any scanned description. "
            "Given the audio-only caveat above, that means these shows keep "
            "sponsor reads out of their show notes, not that they have no "
            "sponsors."
        )
        out.append("")
    else:
        out.append(
            "Ranked by number of shows, then by most recent appearance. "
            "Breadth and recency are the buying signals."
        )
        out.append("")
        out.append(
            "| Sponsor (candidate) | Shows | Episodes | First seen | "
            "Last seen | Evidence (one snippet) |"
        )
        out.append("| ---- | ---- | ---- | ---- | ---- | ---- |")
        for sp in sponsors:
            latest = max(
                sp["evidence"], key=lambda e: (e["date"] or "", e["snippet"])
            )
            snippet = latest["snippet"].replace("|", "\\|")
            out.append(
                f"| {sp['name']} | {', '.join(sp['shows'])} | "
                f"{sp['episode_count']} | {sp['first_seen'] or 'N/A'} | "
                f"{sp['last_seen'] or 'N/A'} | {snippet} |"
            )
        out.append("")

    out.append("## Promo / tracking link signals")
    out.append("")
    out.append(
        "Weak signals, listed per show and deliberately not aggregated into "
        "the table above (shows UTM-tag their own links too). See "
        "sponsors.json for example URLs."
    )
    out.append("")
    out.append("| Show | Episodes with UTM/shortener links |")
    out.append("| ---- | ---- |")
    for s in doc["shows"]:
        out.append(
            f"| {s['name']} | "
            f"{s['link_signals']['episodes_with_link_signals']} |"
        )
    out.append("")

    out.append("## Warnings")
    out.append("")
    if doc["warnings"]:
        for w in doc["warnings"]:
            out.append(f"- {w}")
    else:
        out.append("- None.")
    out.append("")

    out.append("## Methodology and caveats")
    out.append("")
    for note in doc["methodology"]["notes"]:
        out.append(f"- {note}")
    out.append("")

    return "\n".join(out)


def write_sponsor_outputs(doc: dict[str, Any], out_dir: str) -> tuple[str, str]:
    """Write sponsors.json and sponsors.md to out_dir. Returns their paths."""
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "sponsors.json")
    md_path = os.path.join(out_dir, "sponsors.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_sponsors_markdown(doc))
    return json_path, md_path
