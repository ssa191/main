from pathlib import Path

from news_scraper.config import Source
from news_scraper.fetch import dedupe_by_id, parse_feed

FIX = Path(__file__).parent / "fixtures"


def _src(sid, name):
    return Source(id=sid, name=name, enabled=True, feeds=[])


def test_parse_wsj_rss():
    src = _src("wsj", "The Wall Street Journal")
    arts = parse_feed((FIX / "wsj_markets.xml").read_bytes(), src, "markets")
    assert len(arts) == 2
    top = arts[0]
    assert top.title == "Stocks Rally as Inflation Cools"
    assert top.url.endswith("abc123")
    assert top.authors == ["Jane Trader"]
    assert top.published.year == 2026 and top.published.month == 7


def test_parse_economist_atom():
    src = _src("economist", "The Economist")
    arts = parse_feed((FIX / "economist_finance.xml").read_bytes(), src, "finance")
    assert len(arts) == 2
    assert any("resilience" in a.url for a in arts)
    assert arts[0].summary  # summary carried through


def test_parse_argaam_mixed_language():
    src = _src("argaam", "Argaam")
    arts = parse_feed((FIX / "argaam_mixed.xml").read_bytes(), src, "mixed")
    assert len(arts) == 2
    # Arabic article still parses; slug falls back to id
    ar = [a for a in arts if "ar/article" in a.url][0]
    assert ar.slug().startswith("2026-07-20-argaam-")


def test_dedupe_by_id_collapses_duplicates():
    src = _src("wsj", "WSJ")
    arts = parse_feed((FIX / "wsj_markets.xml").read_bytes(), src, "markets")
    doubled = arts + arts
    assert len(dedupe_by_id(doubled)) == 2
