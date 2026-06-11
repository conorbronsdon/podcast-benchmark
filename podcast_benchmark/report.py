"""Assemble per-show metrics and render benchmark.json + report.md."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from . import __version__
from .config import BenchmarkConfig, Show
from . import metrics as M
from .ranking import rank_by
from .sources import fetch_apple, fetch_podcastindex, fetch_rss

NA = "N/A"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_show(
    show: Show,
    pi_key: str | None,
    pi_secret: str | None,
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch all sources for one show and compute its metrics."""
    warnings: list[str] = []
    sources_meta: dict[str, Any] = {}

    apple = None
    if show.apple_id:
        ar = fetch_apple(show.apple_id, session=session)
        warnings.extend(f"[{show.name}] {w}" for w in ar.warnings)
        apple = ar.data
        sources_meta["apple"] = {"fetched_at": ar.fetched_at, "ok": ar.ok}
    else:
        warnings.append(f"[{show.name}] apple: no apple_id in config (skipped)")

    pr = fetch_podcastindex(show.feed_url, pi_key, pi_secret, session=session)
    warnings.extend(f"[{show.name}] {w}" for w in pr.warnings)
    pi = pr.data
    sources_meta["podcastindex"] = {"fetched_at": pr.fetched_at, "ok": pr.ok}

    rr = fetch_rss(show.feed_url, session=session)
    warnings.extend(f"[{show.name}] {w}" for w in rr.warnings)
    rss = rr.data
    sources_meta["rss"] = {"fetched_at": rr.fetched_at, "ok": rr.ok}

    # When the RSS fetch/parse failed entirely, feed-derived metrics must be
    # N/A (None), never zeros: a 0/4 hygiene score or 0-item feed would be
    # ranked as if it were real data.
    rss_ok = rss is not None
    rss = rss or {"episodes": []}

    cadence = M.cadence_per_month(rss, now=now)
    checklist = M.hygiene_checklist(rss) if rss_ok else None
    if cadence["future_dated"]:
        warnings.append(
            f"[{show.name}] rss: {cadence['future_dated']} future-dated "
            "episode(s) excluded from cadence window and recency"
        )

    computed = {
        "apple_rating_count": (apple or {}).get("user_rating_count"),
        "apple_avg_rating": (apple or {}).get("average_user_rating"),
        "catalog_episodes": M.catalog_depth(apple, pi),
        "cadence_per_month": cadence["per_month"],
        "cadence_in_window": cadence["in_window"],
        "cadence_window_truncated": cadence["truncated"],
        "cadence_future_dated": cadence["future_dated"],
        "avg_duration_min": M.average_duration_min(rss),
        "transcript_pct": M.transcript_availability_pct(rss),
        "days_since_last_episode": M.days_since_last_episode(rss, now=now),
        "hygiene": checklist,
        "hygiene_score": M.hygiene_score(checklist) if checklist is not None else None,
        "feed_items_seen": rss.get("item_count_in_feed", 0) if rss_ok else None,
    }

    return {
        "name": show.name,
        "feed_url": show.feed_url,
        "apple_id": show.apple_id,
        "raw": {"apple": apple, "podcastindex": pi, "rss": rss},
        "sources_meta": sources_meta,
        "metrics": computed,
        "warnings": warnings,
    }


def build_benchmark(
    config: BenchmarkConfig,
    pi_key: str | None = None,
    pi_secret: str | None = None,
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch and compute for every show. Returns the full benchmark document."""
    sess = session or requests.Session()
    if session is None:
        sess.headers.update({"Accept": "application/json, application/xml, */*"})

    shows = [
        collect_show(s, pi_key, pi_secret, session=sess, now=now)
        for s in config.all_shows
    ]
    all_warnings: list[str] = []
    for s in shows:
        all_warnings.extend(s["warnings"])

    return {
        "generated_at": _now_iso(),
        "tool_version": __version__,
        "subject": config.subject.name,
        "shows": shows,
        "warnings": all_warnings,
        "methodology": {
            "sources": [
                "Apple iTunes lookup API (https://itunes.apple.com/lookup)",
                "Podcast Index API (https://api.podcastindex.org)",
                "Direct RSS feed fetch",
            ],
            "cadence_window_days": M.CADENCE_WINDOW_DAYS,
            "notes": [
                "Apple's public lookup API does not expose ratings; rating "
                "fields are N/A unless Apple restores them.",
                "Cadence, duration, and transcript percentages are computed "
                "from the episodes present in the live RSS feed window. "
                "Future-dated episodes are excluded from cadence and recency.",
                "Feeds whose oldest item falls inside the cadence window are "
                "flagged as possibly truncated and excluded from cadence "
                "ranking.",
                "Feed hygiene counts four channel-level signals: artwork "
                "(itunes:image or image), at least one itunes:category, a "
                "podcast:funding tag, and podcast:locked with value 'yes'. "
                "It is N/A when the feed could not be fetched or parsed.",
                "Catalog depth uses Apple trackCount, falling back to "
                "Podcast Index episodeCount.",
                "Downloads and chart positions are private/ToS-restricted and "
                "are deliberately not collected.",
            ],
        },
    }


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #
def _fmt(value: Any) -> str:
    if value is None:
        return NA
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _metric(show: dict, key: str) -> Any:
    return show["metrics"].get(key)


def _ranking_block(
    title: str,
    ranked: dict,
    unit: str,
    subject_name: str,
    truncated_names: list[str] | None = None,
) -> list[str]:
    """Render one ranking table.

    ``truncated_names`` separates shows excluded because their feed window is
    possibly truncated (they HAVE a value, it just can't be ranked fairly)
    from shows excluded because the data is missing outright.
    """
    truncated_names = truncated_names or []
    lines = [f"### {title}", ""]
    if not ranked["ranked"]:
        lines.append("No show had data for this metric. Ranking omitted.")
        lines.append("")
        return lines
    lines.append("| Rank | Show | Value |")
    lines.append("| ---- | ---- | ----- |")
    for i, (name, value) in enumerate(ranked["ranked"], start=1):
        mark = " (subject)" if name == subject_name else ""
        lines.append(f"| {i} | {name}{mark} | {value}{unit} |")
    lines.append("")
    if truncated_names:
        lines.append(
            "Excluded (feed window possibly truncated by the host; value "
            "reported in the overview but not ranked): "
            + ", ".join(truncated_names)
            + "."
        )
        lines.append("")
    na_names = [n for n in ranked["excluded"] if n not in truncated_names]
    if na_names:
        lines.append(
            "Excluded as N/A (no data, not ranked): " + ", ".join(na_names) + "."
        )
        lines.append("")
    return lines


def render_markdown(doc: dict[str, Any]) -> str:
    shows = doc["shows"]
    subject_name = doc["subject"]
    out: list[str] = []

    out.append(f"# Podcast Benchmark: {subject_name} vs peers")
    out.append("")
    out.append(f"Generated {doc['generated_at']} by podcast-benchmark v{doc['tool_version']}.")
    out.append("")
    out.append(
        "This report benchmarks PUBLIC signals only: catalog depth, publishing "
        "cadence, episode duration, transcript availability, and feed hygiene. "
        "It does not estimate downloads or chart rank. Those are private or "
        "ToS-restricted and are out of scope by design."
    )
    out.append("")

    # Master table.
    out.append("## Overview")
    out.append("")
    headers = [
        "Show",
        "Catalog eps",
        "Eps/month (6mo)",
        "Avg min",
        "Transcripts %",
        "Days since last",
        "Hygiene /4",
        "Apple rating",
    ]
    out.append("| " + " | ".join(headers) + " |")
    out.append("| " + " | ".join(["----"] * len(headers)) + " |")
    for s in shows:
        m = s["metrics"]
        cadence = _fmt(m["cadence_per_month"])
        if m["cadence_per_month"] is not None and m["cadence_window_truncated"]:
            cadence += " *"
        rating = m["apple_rating_count"]
        rating_cell = NA if rating is None else f"{rating} ({_fmt(m['apple_avg_rating'])})"
        hygiene_cell = NA if m["hygiene_score"] is None else f"{m['hygiene_score']}/4"
        name = s["name"] + (" (subject)" if s["name"] == subject_name else "")
        row = [
            name,
            _fmt(m["catalog_episodes"]),
            cadence,
            _fmt(m["avg_duration_min"]),
            _fmt(m["transcript_pct"]),
            _fmt(m["days_since_last_episode"]),
            hygiene_cell,
            rating_cell,
        ]
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    out.append(
        "`*` cadence computed from a feed window that may be truncated by the "
        "host (every episode in the feed falls inside the 6-month window), so "
        "the true rate may be higher. These values are reported but excluded "
        "from cadence ranking."
    )
    out.append("")

    # Rankings.
    out.append("## Rankings")
    out.append("")

    out.extend(
        _ranking_block(
            "Catalog depth (episodes)",
            rank_by(shows, lambda s: _metric(s, "catalog_episodes")),
            "",
            subject_name,
        )
    )
    truncated_names = [
        s["name"]
        for s in shows
        if s["metrics"]["cadence_window_truncated"]
        and s["metrics"]["cadence_per_month"] is not None
    ]
    out.extend(
        _ranking_block(
            "Publishing cadence (episodes/month, trailing 6 months)",
            rank_by(
                shows,
                lambda s: None
                if s["metrics"]["cadence_window_truncated"]
                else _metric(s, "cadence_per_month"),
            ),
            "",
            subject_name,
            truncated_names=truncated_names,
        )
    )
    out.extend(
        _ranking_block(
            "Transcript availability",
            rank_by(shows, lambda s: _metric(s, "transcript_pct")),
            "%",
            subject_name,
        )
    )
    out.extend(
        _ranking_block(
            "Feed hygiene",
            rank_by(shows, lambda s: _metric(s, "hygiene_score")),
            "/4",
            subject_name,
        )
    )
    out.extend(
        _ranking_block(
            "Apple ratings count",
            rank_by(shows, lambda s: _metric(s, "apple_rating_count")),
            "",
            subject_name,
        )
    )

    # Findings: computable facts only.
    out.append("## Findings")
    out.append("")
    out.extend(_findings(doc))
    out.append("")

    # Warnings.
    out.append("## Warnings")
    out.append("")
    if doc["warnings"]:
        for w in doc["warnings"]:
            out.append(f"- {w}")
    else:
        out.append("- None.")
    out.append("")

    # Methodology footer.
    out.append("## Methodology")
    out.append("")
    meth = doc["methodology"]
    out.append("Sources, fetched at the timestamps recorded in benchmark.json:")
    for src in meth["sources"]:
        out.append(f"- {src}")
    out.append("")
    out.append(f"Cadence window: trailing {meth['cadence_window_days']} days.")
    out.append("")
    for note in meth["notes"]:
        out.append(f"- {note}")
    out.append("")

    return "\n".join(out)


def _findings(doc: dict[str, Any]) -> list[str]:
    """Generate findings that state only computable facts about the subject."""
    shows = doc["shows"]
    subject_name = doc["subject"]
    subject = next((s for s in shows if s["name"] == subject_name), None)
    lines: list[str] = []
    if subject is None:
        return ["Subject not found in results."]

    sm = subject["metrics"]

    def rank_of(metric_value_fn) -> tuple[int, int] | None:
        ranked = rank_by(shows, metric_value_fn)["ranked"]
        names = [n for n, _ in ranked]
        if subject_name not in names:
            return None
        return names.index(subject_name) + 1, len(names)

    # Catalog depth.
    r = rank_of(lambda s: s["metrics"]["catalog_episodes"])
    if r and sm["catalog_episodes"] is not None:
        lines.append(
            f"- Catalog depth: {sm['catalog_episodes']} episodes, "
            f"ranked {r[0]} of {r[1]} shows with data."
        )

    # Cadence (only when the subject's own window is not truncated).
    r = rank_of(
        lambda s: None
        if s["metrics"]["cadence_window_truncated"]
        else s["metrics"]["cadence_per_month"]
    )
    if r and sm["cadence_per_month"] is not None and not sm["cadence_window_truncated"]:
        lines.append(
            f"- Publishing cadence: {sm['cadence_per_month']} episodes/month "
            f"over the trailing 6 months, ranked {r[0]} of {r[1]} shows with "
            f"non-truncated feed windows."
        )

    # Transcripts.
    r = rank_of(lambda s: s["metrics"]["transcript_pct"])
    if r and sm["transcript_pct"] is not None:
        lines.append(
            f"- Transcript availability: {sm['transcript_pct']}% of in-feed "
            f"episodes, ranked {r[0]} of {r[1]}."
        )

    # Hygiene.
    r = rank_of(lambda s: s["metrics"]["hygiene_score"])
    if r and sm["hygiene"] is not None:
        present = [k for k, v in sm["hygiene"].items() if v]
        absent = [k for k, v in sm["hygiene"].items() if not v]
        lines.append(
            f"- Feed hygiene: {sm['hygiene_score']}/4 signals present "
            f"({', '.join(present) or 'none'}; missing: "
            f"{', '.join(absent) or 'none'}), ranked {r[0]} of {r[1]}."
        )

    # Duration.
    if sm["avg_duration_min"] is not None:
        lines.append(
            f"- Average episode duration in the feed window: "
            f"{sm['avg_duration_min']} minutes."
        )

    # Recency.
    if sm["days_since_last_episode"] is not None:
        lines.append(
            f"- Days since last episode: {sm['days_since_last_episode']}."
        )

    # Ratings caveat.
    if sm["apple_rating_count"] is None:
        lines.append(
            "- Apple ratings: N/A for all shows (Apple's public API does not "
            "expose ratings counts)."
        )

    if not lines:
        lines.append("- No computable facts available for the subject.")
    return lines


def write_outputs(doc: dict[str, Any], out_dir: str) -> tuple[str, str]:
    """Write benchmark.json and report.md to out_dir. Returns their paths."""
    import json

    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "benchmark.json")
    md_path = os.path.join(out_dir, "report.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(doc))
    return json_path, md_path
