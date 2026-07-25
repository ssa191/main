"""Fetch and parse RSS/Atom feeds into Article objects.

Network fetching and parsing are deliberately separated so the parser can be
exercised on local fixture bytes with no network access (see tests/).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable

import feedparser
import requests

from .config import Options, Source
from .models import Article, make_id


class FeedError(RuntimeError):
    """Raised when a feed cannot be retrieved after all retries."""


def fetch_feed_bytes(url: str, options: Options) -> bytes:
    """Download a feed with retries and exponential backoff.

    Raises FeedError on network failure or non-2xx status.
    """
    headers = {"User-Agent": options.user_agent, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    last_exc: Exception | None = None
    for attempt in range(1, options.retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=options.request_timeout)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001 - re-raised as FeedError below
            last_exc = exc
            if attempt < options.retries:
                time.sleep(options.backoff_base ** attempt)
    raise FeedError(f"Failed to fetch {url}: {last_exc}") from last_exc


def parse_feed(content: bytes | str, source: Source, section: str) -> list[Article]:
    """Parse raw feed bytes into Articles. Pure function — no network."""
    parsed = feedparser.parse(content)
    fetched_at = datetime.now(timezone.utc)
    articles: list[Article] = []
    for entry in parsed.entries:
        link = entry.get("link", "").strip()
        guid = entry.get("id") or link or entry.get("title", "")
        if not guid:
            continue
        articles.append(
            Article(
                id=make_id(source.id, guid),
                source_id=source.id,
                source_name=source.name,
                section=section,
                title=(entry.get("title") or "").strip(),
                url=link,
                summary=_clean_summary(entry.get("summary", "")),
                authors=_authors(entry),
                tags=[t.get("term", "").strip() for t in entry.get("tags", []) if t.get("term")],
                published=_entry_datetime(entry, fetched_at),
                fetched_at=fetched_at,
            )
        )
    return articles


def fetch_source(source: Source, options: Options) -> tuple[list[Article], list[str]]:
    """Fetch every feed of a source. Returns (articles, errors).

    A failing feed never aborts the source — its error is collected and the
    remaining feeds continue.
    """
    articles: list[Article] = []
    errors: list[str] = []
    for feed in source.feeds:
        try:
            content = fetch_feed_bytes(feed.url, options)
            articles.extend(parse_feed(content, source, feed.section))
        except FeedError as exc:
            errors.append(str(exc))
    return articles, errors


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _entry_datetime(entry, fallback: datetime) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        tm = entry.get(key)
        if tm:
            return datetime(*tm[:6], tzinfo=timezone.utc)
    return fallback


def _authors(entry) -> list[str]:
    names: list[str] = []
    for a in entry.get("authors", []) or []:
        name = (a.get("name") or "").strip()
        if name:
            names.append(name)
    if not names and entry.get("author"):
        names.append(entry["author"].strip())
    return names


def _clean_summary(html: str) -> str:
    """Strip tags and collapse whitespace from a feed summary."""
    import re

    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def dedupe_by_id(articles: Iterable[Article]) -> list[Article]:
    """Collapse duplicate ids within a single fetch (a story can appear in
    more than one section feed)."""
    seen: dict[str, Article] = {}
    for a in articles:
        seen.setdefault(a.id, a)
    return list(seen.values())
