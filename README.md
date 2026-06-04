"""
Tesla Regional Sales Dashboard
================================

A lightweight Streamlit dashboard (local-first + optional public hosted) to track Tesla vehicle sales/registrations by country and region over time.

It turns the manual X posts (from @piloly, @Tslachan, @tslaming, etc.) that get shared
in Discord into a persistent, searchable, visual history with tables, trends, and exports.

Local: your data stays private in data/tesla_sales.db. Hosted: shared demo instance (ingests update it for everyone — handy for latest drops). No accounts needed.

HOW TO RUN (copy-paste these into Terminal, in the folder holding this project):

    # first time only — create venv and install dependencies:
    ./setup.sh

    # every time — activate and start the app (opens in your browser):
    source .venv/bin/activate
    streamlit run tesla_sales_dashboard.py

On Mac you can also double-click TeslaSalesDashboard.command (after first setup).

To stop it: click the Terminal window and press Ctrl-C.

Data note: The tool ingests the high-quality, already-standardized numbers from
the expert X accounts. It does NOT scrape official government sources directly
(yet). Paste the post text or URL when new data drops.

(We use the full `source .venv/bin/activate` + `streamlit run ...` pattern because
the streamlit launcher isn't reliably on PATH on a default macOS setup.)
"""

## Why this exists
- Tesla does **not** publish detailed monthly sales by country.
- Data comes from dozens of national registration authorities, industry associations (CPCA, FCAI/VFACTS, KBA, OFV, ACEA, etc.), and is staggered, in different formats (PDFs, websites, tables).
- A small group of dedicated accounts on X (@piloly, @Tslachan, @tslaming, @SawyerMerritt and others) manually find, standardize, and visualize the data with consistent stats + charts every month.
- Your friend reposts the links. This tool lets you (and the Discord group) capture that signal systematically, see trends over time, totals, rankings, without copy-pasting into spreadsheets every time.

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

## Quick start (local)
See the top of this file for the exact copy-paste commands.

After starting the app:
- It auto-seeds demo May/June 2026 data (from the example posts) if empty — dashboard shows immediately.
- Use the "Ingest a new post" section (URL + Fetch is easiest) whenever your friend shares a new X link. (On the public hosted version, this updates it for everyone.)
- Explore the tabs: Latest numbers, Trends & Charts, All Data (with export).

The database lives at `data/tesla_sales.db` (gitignored — your local data stays private).

Re-setup anytime with `./setup.sh`.

## Public hosted version (Streamlit Cloud)
The app is deployed publicly (see the exact copy-paste deploy steps you were given).

Live URL (once deployed): https://tesla-sales-dashboard.streamlit.app  (or whatever name you chose in the Streamlit deploy wizard — match your Signal Lab style).

On hosted:
- Auto-loads the demo seed data on start (no need to click).
- The ingest form is live for everyone: paste new X post URLs/text and it updates the dashboard for all visitors. Perfect for staying in sync when @piloly etc post fresh numbers.
- Changes persist across sessions for the app.

Your local clone stays fully private (data/ is gitignored).

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
