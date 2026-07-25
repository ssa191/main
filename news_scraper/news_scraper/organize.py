"""Organize articles into a year / month / week folder tree, maintain a JSON
catalog, and (re)generate browsable index.md files at every level.

Tree layout (week_scheme: month)::

    articles/
      index.md                     <- years overview
      2026/
        index.md                   <- months in 2026
        07-Jul/
          index.md                 <- weeks in July 2026
          W3/
            index.md               <- the week's articles, grouped by source
            wsj/2026-07-21-slug.md
            economist/...
            argaam/...
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timezone
from pathlib import Path

from .config import Config
from .models import Article


# ---------------------------------------------------------------------------
# catalog (source of truth for indexes / stats)
# ---------------------------------------------------------------------------

class Catalog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._by_id: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._by_id = {row["id"]: row for row in data.get("articles", [])}
            except (json.JSONDecodeError, OSError, KeyError):
                self._by_id = {}

    def add(self, article: Article, rel_path: str) -> None:
        row = article.to_dict()
        row["path"] = rel_path
        self._by_id[article.id] = row

    def rows(self) -> list[dict]:
        return sorted(
            self._by_id.values(),
            key=lambda r: (r["published"], r["source_id"]),
            reverse=True,
        )

    def __len__(self) -> int:
        return len(self._by_id)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"count": len(self._by_id), "articles": self.rows()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


# ---------------------------------------------------------------------------
# writing article files
# ---------------------------------------------------------------------------

def article_relpath(article: Article, week_scheme: str) -> Path:
    year, month, week = article.bucket(week_scheme)
    return Path(year) / month / week / article.source_id / f"{article.slug()}.md"


def write_article(cfg: Config, article: Article) -> str:
    """Write one article as a markdown file. Returns its path relative to
    output_dir (posix style)."""
    rel = article_relpath(article, cfg.options.week_scheme)
    dest = cfg.output_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_article_markdown(article), encoding="utf-8")
    return rel.as_posix()


def _yaml_escape(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _article_markdown(a: Article) -> str:
    pub = a.published.astimezone(timezone.utc)
    fm = [
        "---",
        f"id: {a.id}",
        f"source: {a.source_id}",
        f"source_name: {_yaml_escape(a.source_name)}",
        f"section: {a.section}",
        f"title: {_yaml_escape(a.title)}",
        f"url: {a.url}",
        f"published: {pub.isoformat()}",
        f"authors: [{', '.join(_yaml_escape(x) for x in a.authors)}]",
        f"tags: [{', '.join(_yaml_escape(x) for x in a.tags)}]",
        "---",
    ]
    body = [
        "",
        f"# {a.title}",
        "",
        f"**{a.source_name}** · {a.section} · {pub.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    if a.authors:
        body.append(f"*By {', '.join(a.authors)}*")
        body.append("")
    if a.summary:
        body.append(a.summary)
        body.append("")
    body.append(f"[Read the full article at {a.source_name}]({a.url})")
    body.append("")
    return "\n".join(fm + body)


# ---------------------------------------------------------------------------
# index generation (rebuilt wholesale from the catalog)
# ---------------------------------------------------------------------------

def _parse_bucket(row: dict, week_scheme: str) -> tuple[str, str, str]:
    return Article.from_dict(row).bucket(week_scheme)


def build_indexes(cfg: Config, catalog: Catalog) -> None:
    """Regenerate every index.md from the catalog. Idempotent."""
    week_scheme = cfg.options.week_scheme
    out = cfg.output_dir
    rows = catalog.rows()

    # group rows -> year -> month -> week -> [rows]
    tree: dict[str, dict[str, dict[str, list[dict]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for row in rows:
        y, m, w = _parse_bucket(row, week_scheme)
        tree[y][m][w].append(row)

    out.mkdir(parents=True, exist_ok=True)

    # ---- root index --------------------------------------------------------
    root_lines = ["# Article archive", "", f"Total articles: **{len(rows)}**", ""]
    root_lines += _source_breakdown(rows)
    root_lines += ["", "## Years", ""]
    for year in sorted(tree, reverse=True):
        n = sum(len(ws) for ms in tree[year].values() for ws in ms.values())
        root_lines.append(f"- [{year}]({year}/index.md) — {n} articles")
    _write(out / "index.md", root_lines)

    # ---- per-year / per-month / per-week ----------------------------------
    for year, months in tree.items():
        y_dir = out / year
        y_lines = [f"# {year}", "", f"[← archive](../index.md)", "", "## Months", ""]
        for month in sorted(months, reverse=True):
            n = sum(len(ws) for ws in months[month].values())
            y_lines.append(f"- [{month}]({month}/index.md) — {n} articles")
        _write(y_dir / "index.md", y_lines)

        for month, weeks in months.items():
            m_dir = y_dir / month
            m_lines = [f"# {month} {year}", "", "[← year](../index.md)", "", "## Weeks", ""]
            for week in sorted(weeks, key=_week_sort_key):
                m_lines.append(
                    f"- [{week}]({week}/index.md) — {len(weeks[week])} articles"
                )
            _write(m_dir / "index.md", m_lines)

            for week, wk_rows in weeks.items():
                _write(
                    m_dir / week / "index.md",
                    _week_index_lines(year, month, week, wk_rows),
                )


def _week_index_lines(year: str, month: str, week: str, rows: list[dict]) -> list[str]:
    lines = [f"# {week} · {month} {year}", "", "[← month](../index.md)", ""]
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_source[r["source_name"]].append(r)
    for source_name in sorted(by_source):
        srows = sorted(by_source[source_name], key=lambda r: r["published"], reverse=True)
        lines.append(f"## {source_name} ({len(srows)})")
        lines.append("")
        for r in srows:
            date = r["published"][:10]
            # path is relative to output_dir; index sits at year/month/week/
            link = "/".join(r["path"].split("/")[3:])
            lines.append(f"- `{date}` [{r['title']}]({link}) — {r['section']}")
        lines.append("")
    return lines


def _source_breakdown(rows: list[dict]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["source_name"]] += 1
    if not counts:
        return []
    lines = ["## By source", ""]
    for name in sorted(counts):
        lines.append(f"- {name}: {counts[name]}")
    return lines


def _week_sort_key(week: str) -> int:
    try:
        return int(week.lstrip("W"))
    except ValueError:
        return 0


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
