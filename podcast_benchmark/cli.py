"""Command-line interface for podcast-benchmark."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .config import load_config
from .report import build_benchmark, render_markdown, write_outputs
from .sponsors import build_sponsor_intel, write_sponsor_outputs

_SUBCOMMANDS = {"benchmark", "sponsors"}


def _add_common_args(parser: argparse.ArgumentParser, outputs: str) -> None:
    parser.add_argument(
        "-o",
        "--out-dir",
        default="output",
        help=f"Directory for {outputs} (default: ./output).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the warning summary on stderr.",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Backward compatibility: the original CLI took the config path (or
    # --from-json) directly. If the first arg is not a subcommand, assume
    # benchmark. Top-level help is the only thing left at the top level.
    if argv and argv[0] not in _SUBCOMMANDS and argv[0] not in ("-h", "--help"):
        argv = ["benchmark", *argv]

    parser = argparse.ArgumentParser(
        prog="podcast-benchmark",
        description=(
            "Compare a podcast against peers using public data. "
            "'benchmark' measures catalog depth, cadence, duration, "
            "transcripts, and feed hygiene; 'sponsors' extracts sponsor-read "
            "candidates from episode descriptions. Neither estimates "
            "downloads or chart rank."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    bench = sub.add_parser(
        "benchmark",
        help="Benchmark public signals across the configured shows.",
    )
    bench.add_argument(
        "config",
        nargs="?",
        help="Path to the YAML config file (omit with --from-json).",
    )
    bench.add_argument(
        "--from-json",
        metavar="BENCHMARK_JSON",
        help=(
            "Re-render report.md from an existing benchmark.json instead of "
            "fetching. No network access; writes report.md to --out-dir."
        ),
    )
    _add_common_args(bench, "benchmark.json and report.md")

    spons = sub.add_parser(
        "sponsors",
        help=(
            "Scan episode descriptions for sponsor reads and aggregate "
            "candidates across shows. Heuristic; audio-only reads are missed."
        ),
    )
    spons.add_argument("config", help="Path to the YAML config file.")
    _add_common_args(spons, "sponsors.json and sponsors.md")

    args = parser.parse_args(argv)

    if args.command == "benchmark" and args.from_json:
        try:
            with open(args.from_json, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except FileNotFoundError:
            print(f"error: file not found: {args.from_json}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"error: invalid JSON in {args.from_json}: {exc}", file=sys.stderr)
            return 2
        os.makedirs(args.out_dir, exist_ok=True)
        md_path = os.path.join(args.out_dir, "report.md")
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(doc))
        print(f"wrote {md_path}")
        return 0

    if not args.config:
        parser.error("config is required unless --from-json is given")

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"error: config file not found: {args.config}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "sponsors":
        doc = build_sponsor_intel(config)
        json_path, md_path = write_sponsor_outputs(doc, args.out_dir)
        n_sponsors = len(doc["sponsors"])
        n_shows = len(doc["shows"])
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")
        print(
            f"{n_sponsors} sponsor candidate(s) across {n_shows} show(s). "
            "Audio-only reads are not detectable; see the report caveats."
        )
    else:
        pi_key = os.environ.get("PODCASTINDEX_API_KEY")
        pi_secret = os.environ.get("PODCASTINDEX_API_SECRET")
        doc = build_benchmark(config, pi_key=pi_key, pi_secret=pi_secret)
        json_path, md_path = write_outputs(doc, args.out_dir)
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")

    if not args.quiet and doc["warnings"]:
        print(f"\n{len(doc['warnings'])} warning(s):", file=sys.stderr)
        for w in doc["warnings"]:
            print(f"  - {w}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
