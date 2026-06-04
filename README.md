# Tesla Regional Sales Dashboard

A lightweight, local-first dashboard to aggregate and visualize Tesla vehicle sales/registrations by country and region. It turns the manual work your friend does (posting X links in Discord with per-country numbers, charts, growth rates, market share) into a queryable, historical, visual system.

## Why this exists
- Tesla does **not** publish detailed monthly sales by country.
- Data comes from dozens of national registration authorities, industry associations (CPCA, FCAI/VFACTS, KBA, OFV, ACEA, etc.), and is staggered, in different formats (PDFs, websites, tables).
- A small group of dedicated accounts on X (@piloly, @Tslachan, @tslaming, @SawyerMerritt and others) manually find, standardize, and visualize the data with consistent stats + charts every month.
- Your friend reposts the links. This tool lets you (and the Discord group) capture that signal systematically, see trends over time, totals, rankings, without copy-pasting into spreadsheets every time.

## Core idea
1. **Primary ingestion**: Monitor or paste posts from the expert X curators (highest signal + context).
2. **Parser**: Extracts structured data from their consistent post format (headline numbers, bullets for growth/model mix, provenance).
3. **Optional direct sources**: Scrape or note official feeds for key markets (China CPCA, Australia thedriven.io/FCAI, Norway OFV, Germany KBA, ACEA Europe, etc.).
4. **Storage**: Local SQLite (or CSV/Parquet) with full provenance.
5. **Dashboard**: Streamlit app — latest numbers table, time series, YTD aggregates, country groups (Europe, Asia ex-China, etc.), source links back to original X post + official report.
6. **Discord-friendly**: Easy to add via paste or (future) bot.

## Key tracked "regions"
- **China**: Giga Shanghai wholesale (local + exports) via CPCA. Often the biggest single number.
- **Individual European countries** (fast reporters first): Norway (OFV), Germany (KBA), France, UK, Netherlands, Sweden, Denmark, Spain, Portugal, Belgium, Italy, Iceland, Czech Republic, Ireland, Romania, Switzerland, etc.
- **Europe aggregate** (from @piloly weekly from ~10 fast countries covering ~60% of Tesla EU volume).
- **Australia** (FCAI VFACTS + thedriven.io + EVC).
- **Asia ex-China**: Japan (tracked in "Others"), South Korea, Taiwan, Hong Kong.
- **Other**: Turkey, Colombia, and any new markets that appear.

## Current sources (curated by the X accounts + direct)
See [docs/sources.md](docs/sources.md) for detailed per-country links, update cadence, and how to add new ones.

Primary X accounts to watch:
- @piloly — most detailed per-country + charts + weekly Europe.
- @Tslachan — rollups, China, Korea, big updates.
- @tslaming — Japan, Norway daily/strong starts, UK, good-news style.
- @SawyerMerritt — major market records + article sources.

## MVP status & roadmap (current state)
- [x] Project skeleton + data model (Pydantic-ish dataclass + SQLite)
- [x] Robust text parser for the main @piloly detailed format + @Tslachan/@tslaming rollup summaries (tested on the exact posts you linked)
- [x] Seed data from the May/June 2026 wave you shared (China Giga Shanghai, Germany, Australia, UK/Norway/etc rollups, etc.)
- [x] Basic Streamlit dashboard (latest table, interactive time series with Plotly, full data + CSV)
- [x] Sidebar ingestion form: paste post text (and URL) → parses → saves with provenance
- [x] Full docs of sources + the X accounts doing the curation
- Future (see docs/future-ideas.md):
  - Image/vision parsing for the 4-chart follow-ups @piloly posts.
  - Discord bot that auto-ingests when your friend posts links.
  - X API polling or the X tools you have here for auto-watch.
  - Direct scrapers for CPCA, OFV, thedriven.io, KBA, ACEA.
  - Backfill script + reconciliation to Tesla IR quarterly numbers.
  - Nicer cards, heatmaps, region aggregates, hosted version.

The parser already handled all 17 of the example links you gave without errors (detailed per-country + rollups). Adding more is usually just pasting the new text.

## Quick start (local) — already set up for you
The venv and dependencies are pre-installed (see `setup.sh`).

```bash
cd ~/tesla-sales-dashboard
source .venv/bin/activate
streamlit run app/dashboard.py
```

- In the sidebar, click **"Seed with recent examples (May/June 2026)"** — this parses real posts from @piloly and @Tslachan (Germany 5,111, China 85,982 wholesale, Australia 6,433, plus a Europe/Asia rollup) and loads ~13 rows.
- Paste any new post text your friend shares (the main detailed one is best) into the sidebar ingest box + optional URL. Hit "Parse & Save".
- Switch tabs for latest table, interactive trends (Plotly), full data + CSV export.

The DB file is at `data/tesla_sales.db` — you can open it with any SQLite tool or `pandas.read_sql`.

If you ever want a clean re-setup: `./setup.sh` (it will recreate the venv).

See `app/` and `parsers/` for code.

## Data model (simplified)
- `monthly_sales`:
  - country (str, normalized e.g. "Germany", "China (Giga Shanghai wholesale)")
  - year, month (int)
  - period_label (e.g. "May 2026")
  - sales (int)  # Tesla units
  - yoy_pct, vs_prior_q2m_pct (float, optional)
  - market_share_pct, bev_penetration_pct, tesla_of_bev_pct (float)
  - model_y_pct, model_3_pct, other_models (json or separate)
  - ytd_vs_last_ytd_pct, ytd_fraction_of_prior_year (float)
  - notes, records (text)
  - source_type ("x_post", "official", "aggregator")
  - source_url, source_post_id, ingested_at, ingested_from (X author etc.)

- Separate `europe_weekly` for the fast Europe* aggregates.
- `countries` lookup with region tags, flag emoji, typical source.

All numbers come with heavy context from the posters (e.g. "second best May ever", "highest quarter after 2 months since 22Q4").

## Contributing / maintaining
- When friend posts new links in Discord, paste the main post text (and follow-up if charts) into the ingest form.
- For new countries: add to `docs/sources.md`, extend parser if format differs, add region tag.
- Backfill: collect old posts from the accounts (search "reported" from:piloly since:2024-01-01) and ingest.
- Validation: cross-check a few months against Tesla IR quarterly totals (they won't match exactly due to timing, inventory, wholesale vs retail, but directionally useful).

## License / notes
Personal tool. Data belongs to the original publishers (national stats + the X visualizers who do the real work).

Pull requests welcome for parsers, new sources, better charts.

## Credits
Inspired directly by the consistent, high-quality work of @piloly and the other Tesla data accounts who make this possible every month.
