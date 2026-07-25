"""The scrape → organize workflow.

Stages, in order:
  1. fetch    — pull every enabled source's RSS feeds
  2. dedupe   — drop within-run duplicates, then anything already archived
  3. organize — write each new article into year/month/week/source/
  4. index    — regenerate the catalog + browsable index.md tree
  5. persist  — save the seen-store and catalog

The workflow is idempotent: a second run adds only genuinely new articles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .dedupe import SeenStore
from .fetch import dedupe_by_id, fetch_source
from .organize import Catalog, build_indexes, write_article


@dataclass
class RunReport:
    fetched: int = 0
    new: int = 0
    skipped_existing: int = 0
    per_source_new: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "Scrape complete.",
            f"  fetched (after in-run dedupe): {self.fetched}",
            f"  new articles archived:         {self.new}",
            f"  already archived (skipped):    {self.skipped_existing}",
        ]
        if self.per_source_new:
            lines.append("  new by source:")
            for src, n in sorted(self.per_source_new.items()):
                lines.append(f"    - {src}: {n}")
        if self.errors:
            lines.append(f"  feed errors: {len(self.errors)}")
            for e in self.errors:
                lines.append(f"    ! {e}")
        return "\n".join(lines)


def run(cfg: Config, *, dry_run: bool = False) -> RunReport:
    report = RunReport()

    # 1. fetch
    all_articles = []
    for source in cfg.enabled_sources():
        articles, errors = fetch_source(source, cfg.options)
        all_articles.extend(articles)
        report.errors.extend(errors)

    # 2. dedupe (within run, then against archive)
    all_articles = dedupe_by_id(all_articles)
    report.fetched = len(all_articles)

    seen = SeenStore(cfg.state_dir / "seen.json")
    catalog = Catalog(cfg.state_dir / "catalog.json")
    new_articles = [a for a in all_articles if a.id not in seen]
    report.skipped_existing = report.fetched - len(new_articles)

    if dry_run:
        report.new = len(new_articles)
        for a in new_articles:
            report.per_source_new[a.source_id] = report.per_source_new.get(a.source_id, 0) + 1
        return report

    # 3. organize
    for a in new_articles:
        rel_path = write_article(cfg, a)
        catalog.add(a, rel_path)
        seen.record(a.id, rel_path, a.source_id)
        report.new += 1
        report.per_source_new[a.source_id] = report.per_source_new.get(a.source_id, 0) + 1

    # 4. index (rebuild from catalog so counts stay correct)
    build_indexes(cfg, catalog)

    # 5. persist
    catalog.save()
    seen.save()
    return report


def reindex(cfg: Config) -> int:
    """Rebuild index.md files from the existing catalog without fetching."""
    catalog = Catalog(cfg.state_dir / "catalog.json")
    build_indexes(cfg, catalog)
    return len(catalog)
