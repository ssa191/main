"""Configuration loading and typed access."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Feed:
    section: str
    url: str


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    enabled: bool
    feeds: list[Feed]


@dataclass(frozen=True)
class Options:
    week_scheme: str = "month"          # "month" | "iso"
    fetch_full_text: bool = False
    user_agent: str = "news-scraper/1.0"
    request_timeout: int = 30
    retries: int = 3
    backoff_base: int = 2


@dataclass(frozen=True)
class Config:
    output_dir: Path
    state_dir: Path
    options: Options
    sources: list[Source]
    base_dir: Path = field(default_factory=Path.cwd)

    def enabled_sources(self) -> list[Source]:
        return [s for s in self.sources if s.enabled]


def _as_path(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p)


def load_config(path: str | os.PathLike[str]) -> Config:
    """Load a YAML config file into a typed Config.

    Relative output_dir / state_dir are resolved against the config file's
    directory so the tool behaves the same regardless of the current directory.
    """
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    base_dir = cfg_path.parent
    opts_raw = raw.get("options", {}) or {}
    options = Options(
        week_scheme=str(opts_raw.get("week_scheme", "month")).lower(),
        fetch_full_text=bool(opts_raw.get("fetch_full_text", False)),
        user_agent=str(opts_raw.get("user_agent", "news-scraper/1.0")),
        request_timeout=int(opts_raw.get("request_timeout", 30)),
        retries=int(opts_raw.get("retries", 3)),
        backoff_base=int(opts_raw.get("backoff_base", 2)),
    )
    if options.week_scheme not in ("month", "iso"):
        raise ValueError(
            f"options.week_scheme must be 'month' or 'iso', got {options.week_scheme!r}"
        )

    sources: list[Source] = []
    for s in raw.get("sources", []) or []:
        feeds = [
            Feed(section=str(f["section"]), url=str(f["url"]))
            for f in s.get("feeds", []) or []
        ]
        sources.append(
            Source(
                id=str(s["id"]),
                name=str(s.get("name", s["id"])),
                enabled=bool(s.get("enabled", True)),
                feeds=feeds,
            )
        )

    return Config(
        output_dir=_as_path(base_dir, str(raw.get("output_dir", "articles"))),
        state_dir=_as_path(base_dir, str(raw.get("state_dir", "state"))),
        options=options,
        sources=sources,
        base_dir=base_dir,
    )
