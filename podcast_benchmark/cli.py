"""Command-line interface for podcast-benchmark."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .config import load_config
from .report import build_benchmark, render_markdown, write_outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="podcast-benchmark",
        description=(
            "Benchmark a podcast against peers using public data "
            "(catalog depth, cadence, duration, transcripts, feed hygiene). "
            "Does not estimate downloads or chart rank."
        ),
    )
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to the YAML config file (omit with --from-json).",
    )
    parser.add_argument(
        "-o",
        "--out-dir",
        default="output",
        help="Directory for benchmark.json and report.md (default: ./output).",
    )
    parser.add_argument(
        "--from-json",
        metavar="BENCHMARK_JSON",
        help=(
            "Re-render report.md from an existing benchmark.json instead of "
            "fetching. No network access; writes report.md to --out-dir."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the warning summary on stderr.",
    )
    args = parser.parse_args(argv)

    if args.from_json:
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
