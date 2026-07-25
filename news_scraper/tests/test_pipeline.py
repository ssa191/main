from pathlib import Path

import news_scraper.pipeline as pipeline
from news_scraper.config import Config, Options, Source
from news_scraper.fetch import parse_feed

FIX = Path(__file__).parent / "fixtures"

FIXTURE_MAP = {
    "wsj": ("wsj_markets.xml", "markets"),
    "economist": ("economist_finance.xml", "finance-and-economics"),
    "argaam": ("argaam_mixed.xml", "mixed"),
}


def _make_config(tmp_path: Path, week_scheme="month") -> Config:
    sources = [
        Source(id="wsj", name="The Wall Street Journal", enabled=True, feeds=[]),
        Source(id="economist", name="The Economist", enabled=True, feeds=[]),
        Source(id="argaam", name="Argaam", enabled=True, feeds=[]),
    ]
    return Config(
        output_dir=tmp_path / "articles",
        state_dir=tmp_path / "state",
        options=Options(week_scheme=week_scheme),
        sources=sources,
        base_dir=tmp_path,
    )


def _fake_fetch_source(source, options):
    fname, section = FIXTURE_MAP[source.id]
    arts = parse_feed((FIX / fname).read_bytes(), source, section)
    return arts, []


def test_pipeline_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "fetch_source", _fake_fetch_source)
    cfg = _make_config(tmp_path)

    report = pipeline.run(cfg)
    assert report.fetched == 6
    assert report.new == 6
    assert report.skipped_existing == 0
    assert report.per_source_new == {"wsj": 2, "economist": 2, "argaam": 2}

    # bucketed files exist in the right place
    art = cfg.output_dir
    assert (art / "2026" / "07-Jul" / "W3" / "wsj").is_dir()
    wsj_files = list((art / "2026" / "07-Jul" / "W3" / "wsj").glob("*.md"))
    assert any("stocks-rally" in f.name for f in wsj_files)
    # June economist article lands under its own month
    assert (art / "2026" / "06-Jun").is_dir()

    # indexes generated at every level
    assert (art / "index.md").exists()
    assert (art / "2026" / "index.md").exists()
    assert (art / "2026" / "07-Jul" / "index.md").exists()
    assert (art / "2026" / "07-Jul" / "W3" / "index.md").exists()

    # catalog + seen store persisted
    assert (cfg.state_dir / "catalog.json").exists()
    assert (cfg.state_dir / "seen.json").exists()

    # article markdown carries frontmatter + link, no body scraping
    content = wsj_files[0].read_text(encoding="utf-8")
    assert content.startswith("---")
    assert "Read the full article" in content


def test_pipeline_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "fetch_source", _fake_fetch_source)
    cfg = _make_config(tmp_path)

    first = pipeline.run(cfg)
    assert first.new == 6

    second = pipeline.run(cfg)
    assert second.new == 0
    assert second.skipped_existing == 6


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "fetch_source", _fake_fetch_source)
    cfg = _make_config(tmp_path)

    report = pipeline.run(cfg, dry_run=True)
    assert report.new == 6
    assert not cfg.output_dir.exists()
    assert not (cfg.state_dir / "catalog.json").exists()


def test_feed_errors_are_collected_not_raised(tmp_path, monkeypatch):
    def _one_bad(source, options):
        if source.id == "economist":
            return [], [f"Failed to fetch {source.id}: boom"]
        return _fake_fetch_source(source, options)

    monkeypatch.setattr(pipeline, "fetch_source", _one_bad)
    cfg = _make_config(tmp_path)
    report = pipeline.run(cfg)
    assert report.new == 4  # wsj(2) + argaam(2)
    assert len(report.errors) == 1
