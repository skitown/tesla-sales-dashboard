# Next Steps & Ideas

## Discord integration (highest value for your use case)
- Write a small `bot/discord_bot.py` using `discord.py`.
- On message in the channel:
  - If from your friend (or contains trusted X links + "sales" / "reported"), auto-fetch the thread or just take the text.
  - Run the parser.
  - Store in the shared DB.
  - Reply with a nice embed: "Parsed Germany +5,111 (+322% YoY). Dashboard updated: [link to streamlit or hosted]".
- Commands: `!tesla latest`, `!tesla germany`, `!tesla sum May 2026`.
- Bonus: periodic "monthly summary" post with top growers, China number, Europe partial total.

## Better / more automated ingestion
1. **X polling** (no full stream needed):
   - Use `tweepy` + bearer token (or free tier search) every 15-60 min for `from:piloly "reported" OR "Giga Shanghai" since:YYYY-MM-DD`.
   - Same for the other 3 accounts.
   - On new post IDs, fetch full text (or use the tool you have here), parse, store.
2. **Direct source scrapers** (supplement the X layer):
   - China: simple requests + parse cnevpost.com monthly article, or watch their RSS.
   - Australia: thedriven.io has consistent URLs; beautifulsoup the tables.
   - Norway: OFV has public stats pages — scrape the latest month table.
   - Germany: KBA press releases (PDFs are parseable with pdfplumber or camelot for tables).
   - ACEA: their monthly press release pages have tables.
   - Start with one or two high-volume ones.
3. **Image parsing for the 4-chart follow-ups**:
   - When ingesting, if the post has media, download the images.
   - Use `pytesseract` (after `brew install tesseract`) or EasyOCR for the clean charts @piloly posts.
   - Or call a vision LLM (Grok / OpenAI / local llava) with "extract the table of monthly sales numbers and labels from this chart image. Return JSON".
   - This would give you the full historical series per country automatically.

## Dashboard enhancements (easy wins)
- Region groupings: "Europe (all reported)", "Asia ex-China", "High-growth markets".
- Reconciliation view: sum of countries vs Tesla quarterly delivery number (with lag note).
- Growth heatmap (countries x months).
- Model mix trends (once you parse the follow-up images or more text).
- "What changed this month" diff vs previous ingest.
- Export ready for Google Sheets / Notion.
- Dark theme toggle or nicer cards for the headline numbers (China, Germany, Australia, "Europe fast").

## Backfill
- Use the X tools (or your own) to search historical posts:
  - `from:piloly "reported" since:2024-01-01 until:2025-01-01`
  - Collect 20-30 good ones, paste a batch into the ingest box or write a small script.
- Old TMC Europe registration spreadsheets can be imported as CSV.

## Hosting / sharing
- The DB is a single file — easy to rsync or put in Dropbox.
- Streamlit Community Cloud: push the repo (ignore .venv and service keys), one-click deploy. Point your Discord to the public URL.
- Or self-host on a cheap VPS / Raspberry Pi with `streamlit run ...` + nginx or just local network share.
- For multi-user: move storage to Postgres/Supabase + simple auth.

## Data quality / modeling
- Add `source_confidence` or `is_wholesale` flag.
- Track "as_of_date" (when the registration data was released).
- Handle revisions (some months get updated later).
- Separate "deliveries" vs "registrations" when we know the difference.

## Non-X signals to watch
- Tesla IR quarterly calls / updates (global + factory).
- Earnings transcripts for color on "strong demand in Europe ex some markets" etc.
- Regulatory filings or local news for new market entries (e.g. more LatAm or SEA).

This prototype already removes most of the manual drudgery. The X accounts will keep doing the hard discovery work; your system just captures and surfaces it better.
