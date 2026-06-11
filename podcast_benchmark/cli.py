"""Command-line interface for podcast-benchmark."""

from __future__ import annotations

import argparse
import os
import sys

from .config import load_config
from .report import build_benchmark, write_outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="podcast-benchmark",
        description=(
            "Benchmark a podcast against peers using public data "
            "(catalog depth, cadence, duration, transcripts, feed hygiene). "
            "Does not estimate downloads or chart rank."
        ),
    )
    parser.add_argument("config", help="Path to the YAML config file.")
    parser.add_argument(
        "-o",
        "--out-dir",
        default="output",
        help="Directory for benchmark.json and report.md (default: ./output).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the warning summary on stderr.",
    )
    args = parser.parse_args(argv)

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
