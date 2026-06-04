# Feature / Improvement Backlog

Tracked from user session (priority after the `st.page_link` / KeyError fix is done).

## High value / quick wins
- Add the remaining posts from the original 17 X links (full detailed texts for Turkey, Romania, the big South Korea "Model Y is #1 overall", weekly Europe aggregates from @piloly, Japan surge, etc.). Need to parse/seed more rich data so Germany, Australia, China also show market_share / BEV penetration where available.
- Make the "Latest" table always prefer the most detailed source for each country/month (e.g. prefer @piloly full post over a rollup summary so share % and penetration are populated).
- Add a "Europe (fast reporters)" aggregate row or view (the ~60% coverage weekly ones).
- Add a simple total / sum metric for the current month across all ingested countries (with a note "partial — missing many markets").
- Better handling / note for China (wholesale vs retail).

## Discord integration (biggest workflow win)
- Build a discord.py bot that:
  - Watches the specific channel.
  - When the friend posts one of the trusted X links (or text containing "reported" + country), auto-extracts the text, runs the parser, inserts into the shared DB.
  - Replies with a summary + link to the dashboard.
  - Commands like `!tesla latest`, `!tesla germany`, `!tesla add <paste text>`.

## Automation & ingestion
- Script / button to ingest directly from an X post URL (fetch the thread text using available X tools or a lightweight scraper).
- Watch mode: periodic poll of the key accounts (@piloly, @Tslachan, @tslaming, @SawyerMerritt) for new sales posts and auto-ingest.
- Image / vision support for the 4-chart follow-up images (download media, OCR or call vision model to extract the full time-series tables).

## Dashboard UX
- Region grouping / filters (Europe, Asia ex-China, "High BEV markets", Latin America, etc.).
- Time series for market_share_pct and bev_penetration_pct (not just sales).
- "What changed this month" diff view.
- Reconciliation tab: sum of ingested countries vs Tesla's latest quarterly global deliveries (with lag explanation).
- Make the docs link more robust (or embed the content of sources.md in a tab / expander).
- Add "last updated" timestamp based on ingested_at.

## Data quality & backfill
- Backfill script that can take a list of old X post URLs or text files and ingest them.
- Handle data revisions (some months get updated later by the stats offices).
- Track source_type and confidence (X post vs direct scrape).

## Other
- Export to Google Sheets / CSV with good formatting.
- Hosted version (Streamlit Cloud or simple VPS) so the group can all see the same live data without sharing the DB file.
- Add US data when it appears (currently the posters focus more on ex-US markets because Tesla reports NA more aggregated).

When you're ready, say "let's do the Discord bot" or "add the rest of the May posts" or "implement X from the list" and we'll knock them out one by one.
