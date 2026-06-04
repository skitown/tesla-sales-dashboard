# Tesla Sales Data Sources by Region

This is the "sources of truth" the X accounts (@piloly etc.) pull from. The goal of the dashboard is to capture their standardized output while noting the originals for verification and direct scraping opportunities.

Update cadence and reliability vary. National sources are usually "registrations" (a very close proxy for sales, with some timing differences). China is wholesale from factory.

## China
- **Primary**: China Passenger Car Association (CPCA) wholesale volumes for Giga Shanghai (includes domestic retail + exports).
  - Reported promptly (often first week of following month) via industry sites: cnevpost.com, teslarati.com, globalchinaev, etc.
  - Exact phrasing in posts: "In May, Tesla's Giga Shanghai wholesale sales (local in China and exports) were 85,982 Model 3 and Model Y."
- **Tesla direct**: Sometimes they announce or show in earnings.
- **Notes**: Wholesale ≠ end-customer retail exactly (inventory, exports to Europe/Australia etc. counted here then again in destination). Very important number because Giga Shanghai is the main volume driver.
- **Dashboard handling**: Tag as "China (Giga Shanghai wholesale)".

## Australia
- **Primary official**: Federal Chamber of Automotive Industries (FCAI) VFACTS new vehicle sales data.
  - Released ~3rd business day of the month. Detailed by brand/model often behind paywall or summarized.
  - https://www.fcai.com.au/ (get VFACTS)
- **Best public analysis**: thedriven.io — excellent timely articles + model-level tables for Tesla/EVs.
  - Example: https://thedriven.io/2026/06/02/tesla-hits-record-month-of-sales-in-may-as-ev-surge-continues/
  - Also Electric Vehicle Council (EVC) for EV-specific.
- **X usage**: @SawyerMerritt and others link thedriven.io + quote Tesla AU statements. @piloly posts detailed with market share/BEV pen.
- **Dashboard**: "Australia". Note Model Y L impact etc.

## Europe (broad + country level)
- **ACEA** (European Automobile Manufacturers’ Association): Monthly passenger car registrations by country + brand (Tesla) + fuel type for EU (sometimes + EFTA/UK).
  - https://www.acea.auto/pc-registrations/
  - Good for overview and YoY, but often lags the fastest national sources and may lack fine model mix or exact market share calculations.
- **Fast national sources** (what @piloly uses for weekly "Europe*" ~60% coverage):
  - Norway: OFV (Opplysningsrådet for Veitrafikken / Norwegian Road Federation) — https://ofv.no/registreringsstatistikk — one of the fastest and most detailed in the world. Daily/weekly possible.
  - Denmark: bilstatistik.dk
  - Germany: KBA (Kraftfahrt-Bundesamt) — https://www.kba.de/ — monthly PDFs + data, model-level.
    - Example May 2026 release referenced in posts.
  - France: PFA / CCFA or similar (posts cite +655% etc.)
  - Spain: ANFAC
  - Portugal: ACAP
  - UK: SMMT (Society of Motor Manufacturers and Traders)
  - Others: Sweden, Netherlands, Belgium, Italy, Iceland, Czech Republic, Ireland, Romania, Switzerland — national vehicle registration authorities or auto associations.
- **Commercial**: Dataforce.de — detailed 30-country EU registrations used by analysts/ICCT.
- **X usage**: @piloly does the heroic work of pulling the fast ones, calculating shares/penetration, making charts, and doing weekly Europe* from the subset. @Tslachan does nice rollup tables with % changes.
- **Dashboard**: 
  - Individual countries.
  - "Europe (fast reporters ~60%)" for the weekly aggregates @piloly posts.
  - Later: full ACEA or Dataforce rollup if scraped.

## Japan
- Tesla sales tracked in the official "Others" (import) category because low volume or reporting method.
- Posts (esp. @tslaming) highlight big % growth (e.g. +181% YoY to ~2k in a month).
- Source: Japan Automobile Importers Association or MLIT statistics.
- Dashboard: "Japan".

## South Korea
- National auto registration / import data (KAMA or equivalent).
- Recent: Model Y became overall #1 best-selling vehicle in a month (huge for an import in Hyundai/Kia home market). @Tslachan breaks these.
- Dashboard: "South Korea".

## Other markets that appear
- Hong Kong: High BEV penetration (89%+), Tesla strong share. Local transport dept or stats.
- Turkey: Lower and volatile (inflation, supply). National stats.
- Colombia: Explosive growth in some months (Latin America emerging). Local registrations.
- Taiwan: Part of Asia rollups.
- Iceland, Czech, Romania, Ireland: See Europe section.

## Global / Tesla official
- Tesla IR: Quarterly vehicle deliveries (global, sometimes by factory or region high-level: e.g. "outside of China").
  - https://ir.tesla.com/
  - Use for reconciliation: sum of many country posts should directionally approach (but not equal) the quarterly number after lags.
- Production vs deliveries vs registrations: Watch for differences (China wholesale includes exports that land later).

## How the X accounts add value (beyond raw numbers)
- Calculate market share, BEV penetration, Tesla's share of BEV segment.
- Model mix (Model Y vs 3 vs others).
- "Records": best month, best May ever, highest after X months since YYYYQX.
- Comparisons: vs same month last year, vs 2nd month of prior quarter, last 3 months vs prior period, YTD fraction of prior full year.
- Context and charts (time series, share evolution).
- Weekly Europe from partial fast data.

The dashboard tries to preserve as much of this derived context as possible in the `notes` / structured fields.

## Adding a new country or better source
1. Note the official source + URL + typical release timing in this file.
2. Add a sample post text to `parsers/tests/`.
3. Extend `parsers/piloly.py` or create `country_specific.py` extractor.
4. Add `region_tags` (e.g. ["Europe", "Western Europe"] or ["Asia", "High BEV"]).
5. For scraping: add a small script in `ingest/` that pulls the source and normalizes (start with manual + note "TODO: scraper").

## Useful aggregator sites / communities (for backfill or verification)
- thedriven.io (AU)
- cnevpost.com (China)
- honestjohn.co.uk or rac.co.uk (UK stats)
- GoodCarBadCar.net (US focused)
- Robbie Andrew's collected data pages (historical EV/brand by country, e.g. Norway, global-ish)
- Tesla Motors Club old Europe registration threads (community spreadsheets)
- IEA Global EV Outlook (annual, broader)
- Wikipedia "Electric car use by country" (citations)

## Maintenance tips
- Data revisions happen (late reports, corrections). Store `as_of` or revision flag if possible.
- Some countries report "sales" (dealer), others "registrations" (plates). Note the difference.
- China exports inflate the Shanghai number but show up in destination country later.
- For Discord: when a new batch drops, the person who usually posts can also paste the key post(s) into the dashboard ingest so everyone benefits from the structured view.

Last updated: 2026-06 (based on May data wave).
