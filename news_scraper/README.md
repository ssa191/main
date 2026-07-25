# news_scraper — WSJ / Economist / Argaam article workflow

A small, runnable agent-style workflow that pulls articles from **The Wall
Street Journal**, **The Economist**, and **Argaam**, then files every article
into a browsable **year → month → week** archive.

```
articles/
  index.md                         ← overview: totals, per-source counts, years
  2026/
    index.md                       ← months in 2026
    07-Jul/
      index.md                     ← weeks in July 2026
      W3/
        index.md                   ← the week's articles, grouped by source
        wsj/2026-07-21-stocks-rally-as-inflation-cools.md
        economist/2026-07-15-the-world-economy-s-surprising-resilience.md
        argaam/2026-07-20-saudi-aramco-reports-higher-quarterly-profit.md
```

Each article becomes a Markdown file with YAML front-matter (title, source,
section, authors, publish time, url) plus the feed summary and a link back to
the publisher.

---

## Quick start

```bash
cd news_scraper
./run.sh run          # first run creates a venv, installs deps, then scrapes
./run.sh stats        # counts by source and by year/month/week
./run.sh sources      # list configured sources & feeds
```

Prefer to drive it yourself:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m news_scraper run
```

Commands:

| Command                    | What it does                                        |
| -------------------------- | --------------------------------------------------- |
| `run`                      | fetch every feed, file new articles, rebuild indexes |
| `run --dry-run`            | show what's new without writing anything            |
| `reindex`                  | rebuild the `index.md` tree from the catalog        |
| `stats`                    | totals by source and by year/month/week             |
| `sources`                  | print the configured sources and feed URLs          |

Add `-c path/to/config.yaml` to any command to use a different config.

---

## How it works — the workflow

```
 fetch ──▶ dedupe ──▶ organize ──▶ index ──▶ persist
```

1. **fetch** — each source's public RSS/Atom feeds are downloaded (with retries
   and exponential backoff) and parsed with `feedparser`.
2. **dedupe** — duplicates within a run are collapsed (a story often appears in
   several section feeds), then anything already in the archive is skipped using
   a JSON *seen-store*. The workflow is **idempotent** — running it twice never
   duplicates a file.
3. **organize** — each new article is written to
   `articles/<year>/<month>/<week>/<source>/<date>-<slug>.md`.
4. **index** — a `catalog.json` (machine-readable) and a full `index.md` tree
   (human-browsable) are regenerated from scratch, so counts always match.
5. **persist** — the catalog and seen-store are saved atomically.

Code map (`news_scraper/`): `config.py` (typed YAML config) · `fetch.py`
(network + feed parsing) · `models.py` (the `Article` model, slugs, bucketing) ·
`dedupe.py` (seen-store) · `organize.py` (file writing + index generation) ·
`stats.py` · `pipeline.py` (the orchestrated workflow) · `cli.py` (entry point).

---

## Configuration

Everything lives in [`config.yaml`](config.yaml). Add/remove feeds, toggle a
whole source with `enabled: false`, or change how weeks are labelled:

```yaml
options:
  week_scheme: month   # W1..W5 week-of-month (default) — or `iso` for W01..W53
```

- **`month`** nests cleanly: a week folder never straddles two months.
- **`iso`** uses ISO-8601 week-of-year numbers (standard, unambiguous). Note the
  usual ISO boundary quirk — a few late-December days fall in week 52/53 of the
  same ISO year, and Jan 1 can land in the previous year's final week.

### About the paywalls (important)

WSJ and The Economist are subscription publications. This tool only consumes
their **public RSS feeds** — headlines, summaries, authors, timestamps, and
links. It does **not** download or store paywalled article bodies. There is an
explicit `options.fetch_full_text` switch that is **off by default and should
stay off** for those sources; the article files always link back to the
publisher so you read the full piece there under your own subscription. Argaam
is ingested the same feed-based way.

Feed URLs in `config.yaml` are the publishers' standard, well-known RSS
endpoints. Verify them on first run — publishers occasionally relocate feeds,
and Argaam's feed path may differ by region/account.

---

## Scheduling (make it recurring)

The scraper is a plain CLI, so schedule it however you like. A weekly cron that
runs Monday 07:00 and keeps a log:

```cron
0 7 * * 1  cd /path/to/news_scraper && ./run.sh run >> scrape.log 2>&1
```

Daily instead? Use `0 7 * * *`. Because runs are idempotent, running more often
just picks up new articles — it never re-files old ones.

If you run this inside **Claude Code on the web**, schedule it with a Routine /
trigger instead of system cron — but note the network requirement below.

---

## Network requirement

Fetching reaches out to `feeds.a.dj.com`, `www.economist.com`, and
`www.argaam.com` over HTTPS. Run it somewhere those hosts are reachable (your
machine, or a environment whose egress policy allows them).

> Built and tested in a locked-down environment whose egress policy blocks
> outbound news hosts, so the live fetch could not be exercised there. The
> parsing, dedupe, bucketing, indexing, and end-to-end pipeline are fully
> covered by offline tests against captured feed fixtures (`tests/fixtures/`).
> On a network-enabled host, `./run.sh run` performs the live scrape with no
> code changes.

---

## Tests

```bash
python -m pytest        # 15 tests: models, feed parsing, and the full pipeline
```

The pipeline tests stub the network with the RSS fixtures in
`tests/fixtures/` (WSJ RSS, Economist Atom, and a mixed English/Arabic Argaam
feed), so they verify real bucketing, dedupe, idempotency, dry-run, index
generation, and per-feed error isolation without touching the internet.
