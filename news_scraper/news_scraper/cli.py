"""Command-line entry point: python -m news_scraper <command>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .pipeline import reindex, run
from .stats import render_stats

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="news_scraper",
        description="Scrape WSJ / Economist / Argaam RSS feeds and organize "
        "articles by year, month and week.",
    )
    p.add_argument(
        "-c", "--config", default=str(DEFAULT_CONFIG),
        help="path to config.yaml (default: bundled config)",
    )
    sub = p.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="fetch + organize (default command)")
    run_p.add_argument(
        "--dry-run", action="store_true",
        help="fetch and report new articles without writing anything",
    )

    sub.add_parser("reindex", help="rebuild index.md files from the catalog")
    sub.add_parser("stats", help="print counts by source and period")
    sub.add_parser("sources", help="list configured sources and feeds")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"

    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if command == "run":
        report = run(cfg, dry_run=getattr(args, "dry_run", False))
        print(report.summary())
        if not getattr(args, "dry_run", False):
            print(f"\nArchive: {cfg.output_dir}")
        return 0

    if command == "reindex":
        n = reindex(cfg)
        print(f"Rebuilt indexes for {n} articles under {cfg.output_dir}")
        return 0

    if command == "stats":
        print(render_stats(cfg))
        return 0

    if command == "sources":
        for s in cfg.sources:
            flag = "on " if s.enabled else "off"
            print(f"[{flag}] {s.id} — {s.name}")
            for f in s.feeds:
                print(f"        {f.section:<24} {f.url}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
