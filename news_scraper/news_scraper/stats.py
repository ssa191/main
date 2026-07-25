"""Derive counts from the catalog for the `stats` command."""

from __future__ import annotations

from collections import defaultdict

from .config import Config
from .models import Article
from .organize import Catalog


def render_stats(cfg: Config) -> str:
    catalog = Catalog(cfg.state_dir / "catalog.json")
    rows = catalog.rows()
    if not rows:
        return "No articles archived yet. Run `python -m news_scraper run` first."

    week_scheme = cfg.options.week_scheme
    by_source: dict[str, int] = defaultdict(int)
    by_period: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in rows:
        by_source[r["source_name"]] += 1
        y, m, w = Article.from_dict(r).bucket(week_scheme)
        by_period[(y, m, w)] += 1

    lines = [f"Total articles: {len(rows)}", "", "By source:"]
    for name in sorted(by_source):
        lines.append(f"  {name}: {by_source[name]}")

    lines += ["", "By year / month / week:"]
    for (y, m, w) in sorted(by_period, reverse=True):
        lines.append(f"  {y} / {m} / {w}: {by_period[(y, m, w)]}")
    return "\n".join(lines)
