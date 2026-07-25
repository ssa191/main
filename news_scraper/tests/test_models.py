from datetime import datetime, timezone

from news_scraper.models import Article, date_bucket, make_id, slugify


def test_slugify_latin():
    assert slugify("Stocks Rally as Inflation Cools!") == "stocks-rally-as-inflation-cools"


def test_slugify_arabic_returns_empty():
    # Arabic-only titles have no ASCII content -> empty slug -> caller uses id
    assert slugify("أرامكو السعودية") == ""


def test_make_id_is_stable_and_scoped():
    a = make_id("wsj", "https://x/1")
    b = make_id("wsj", "https://x/1")
    c = make_id("economist", "https://x/1")
    assert a == b
    assert a != c
    assert a.startswith("wsj-")


def test_date_bucket_month_scheme():
    dt = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    assert date_bucket(dt, "month") == ("2026", "07-Jul", "W3")


def test_date_bucket_iso_scheme():
    dt = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    year, month, week = date_bucket(dt, "iso")
    assert (year, month) == ("2026", "07-Jul")
    assert week == "W30"


def test_article_slug_falls_back_to_id_for_arabic():
    a = Article(
        id="argaam-abc123def456",
        source_id="argaam",
        source_name="Argaam",
        section="arabic",
        title="أرامكو السعودية",
        url="https://x/2",
        published=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    slug = a.slug()
    assert slug == "2026-07-20-argaam-abc"


def test_roundtrip_to_from_dict():
    a = Article(
        id="wsj-1", source_id="wsj", source_name="WSJ", section="markets",
        title="T", url="https://x", summary="s", authors=["A"],
        published=datetime(2026, 7, 21, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )
    b = Article.from_dict(a.to_dict())
    assert b.id == a.id and b.title == a.title and b.published == a.published
