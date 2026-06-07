"""
Tesla Regional Sales Dashboard
==============================

Single-file Streamlit app to aggregate Tesla vehicle registrations & deliveries
by country, from national registration agencies, CnEVPost (China weekly),
and Tesla's investor relations quarterly releases.

Replaces the earlier X-post-parsing prototype. No tweet scraping. Manual entry
for agency monthly data (it's a 10-second paste from each release) and an
automated scraper for CnEVPost weekly China insurance registrations.

Install + run:
    pip install streamlit pandas plotly
    python3 -m streamlit run tesla_sales_dashboard.py

Data lives in data/tesla_sales.db (SQLite). Add `data/` to .gitignore.

Schema notes:
- One row per (country, period_start, period_type, metric, source). Period_type
  is 'monthly', 'weekly', or 'quarterly'. Different metrics (registration,
  insurance, wholesale, delivery) are NOT interchangeable -- the dashboard
  keeps them separate.
- For shared multi-user persistence (Streamlit Cloud), swap SQLite for an
  external Postgres -- Neon's free tier works. Only the get_conn() function
  needs to change.
"""

from __future__ import annotations

import re
import sqlite3
import json
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st


# ---- Config ----

DB_PATH = Path(__file__).parent / "data" / "tesla_sales.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

ROBBIE_ANDREW_PAGE = "https://robbieandrew.github.io/carsales/"
CNEVPOST_TAG_URL = "https://cnevpost.com/tag/insurance-registrations/"
TMC_SHEET_ID = "1Vobg29R1t3FphlWjb8dwG4nkAWqyc_qMwkCjUT8SUno"
TMC_SHEET_URL = "https://teslamotorsclub.com/tmc/threads/tesla-europe-registration-stats.61651/"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) tesla-sales-dashboard/0.1"


# Country -> default region, source agency, and source URL. Used by the
# sidebar form so the user only has to pick a country and the rest auto-fills.
COUNTRY_PRESETS = {
    "Germany":     {"region": "Europe", "source": "KBA",             "source_url": "https://www.kba.de"},
    "France":      {"region": "Europe", "source": "PFA",             "source_url": "https://pfa-auto.fr"},
    "UK":          {"region": "Europe", "source": "SMMT",            "source_url": "https://www.smmt.co.uk"},
    "Norway":      {"region": "Europe", "source": "OFV",             "source_url": "https://ofv.no"},
    "Sweden":      {"region": "Europe", "source": "Mobility Sweden", "source_url": "https://mobilitysweden.se"},
    "Denmark":     {"region": "Europe", "source": "bilstatistik.dk", "source_url": "https://bilstatistik.dk"},
    "Netherlands": {"region": "Europe", "source": "RDW",             "source_url": "https://opendata.rdw.nl"},
    "Spain":       {"region": "Europe", "source": "ANFAC",           "source_url": "https://anfac.com"},
    "Italy":       {"region": "Europe", "source": "UNRAE",           "source_url": "https://unrae.it"},
    "Belgium":     {"region": "Europe", "source": "Febiac",          "source_url": "https://febiac.be"},
    "Portugal":    {"region": "Europe", "source": "ACAP",            "source_url": "https://acap.pt"},
    "Switzerland": {"region": "Europe", "source": "auto-suisse",     "source_url": "https://auto.swiss"},
    "Ireland":     {"region": "Europe", "source": "SIMI",            "source_url": "https://simi.ie"},
    "Austria":     {"region": "Europe", "source": "Statistik Austria","source_url": "https://statistik.at"},
}


def _last_n_months(n: int) -> list[str]:
    """Return the last n months as 'YYYY-MM' strings, most recent first."""
    today = date.today()
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out


# ---- Seed data ----
# European registrations are now pulled live from the TMC community sheet
# (see fetch_community_sheet below). The local seed only carries data the
# sheet doesn't cover: Tesla IR quarterly global delivery numbers and a
# couple of China weekly samples to bootstrap until the CnEVPost scraper runs.

SEED_DATA = [
    # Tesla IR quarterly global deliveries (ground truth from SEC 8-K filings)
    {"country": "Global", "region": "Global", "period_start": "2025-01-01",
     "period_type": "quarterly", "metric": "delivery", "units": 336681,
     "source": "Tesla IR", "source_url": "https://ir.tesla.com",
     "notes": "Q1 2025 reported deliveries"},
    {"country": "Global", "region": "Global", "period_start": "2025-04-01",
     "period_type": "quarterly", "metric": "delivery", "units": 384122,
     "source": "Tesla IR", "source_url": "https://ir.tesla.com",
     "notes": "Q2 2025 reported deliveries"},
    {"country": "Global", "region": "Global", "period_start": "2025-07-01",
     "period_type": "quarterly", "metric": "delivery", "units": 497099,
     "source": "Tesla IR", "source_url": "https://ir.tesla.com",
     "notes": "Q3 2025 reported deliveries (all-time record)"},
    {"country": "Global", "region": "Global", "period_start": "2025-10-01",
     "period_type": "quarterly", "metric": "delivery", "units": 418227,
     "source": "Tesla IR", "source_url": "https://ir.tesla.com",
     "notes": "Q4 2025 reported deliveries"},
    {"country": "Global", "region": "Global", "period_start": "2026-01-01",
     "period_type": "quarterly", "metric": "delivery", "units": 358023,
     "source": "Tesla IR", "source_url": "https://ir.tesla.com",
     "notes": "Q1 2026 reported deliveries; missed 365,645 consensus"},

    # China weekly seed (CnEVPost; will be extended by the scraper)
    {"country": "China", "region": "China", "period_start": "2025-09-08",
     "period_type": "weekly", "metric": "insurance", "units": 15350,
     "source": "CnEVPost", "source_url": "https://cnevpost.com",
     "notes": "Week ending Sept 14, 2025"},
    {"country": "China", "region": "China", "period_start": "2025-09-15",
     "period_type": "weekly", "metric": "insurance", "units": 17300,
     "source": "CnEVPost", "source_url": "https://cnevpost.com",
     "notes": "Week ending Sept 21, 2025; 12-week high"},
]


# ---- DB layer ----

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tesla_sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country TEXT NOT NULL,
                region TEXT,
                period_start TEXT NOT NULL,
                period_type TEXT NOT NULL,
                metric TEXT NOT NULL,
                units INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_url TEXT,
                notes TEXT,
                ingested_at TEXT NOT NULL,
                UNIQUE(country, period_start, period_type, metric, source)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_country_period "
            "ON tesla_sales(country, period_start)"
        )
        conn.commit()


def upsert(rec: dict) -> bool:
    rec = {**rec, "ingested_at": datetime.utcnow().isoformat()}
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO tesla_sales
                (country, region, period_start, period_type, metric, units,
                 source, source_url, notes, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec["country"], rec.get("region"), rec["period_start"],
                rec["period_type"], rec["metric"], int(rec["units"]),
                rec["source"], rec.get("source_url"), rec.get("notes", ""),
                rec["ingested_at"],
            ))
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Insert error: {e}")
        return False


def load_df() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM tesla_sales ORDER BY period_start DESC, country",
            conn,
        )
    if not df.empty:
        df["period_start"] = pd.to_datetime(df["period_start"])
    return df


def seed_baseline() -> None:
    """Upsert every row in SEED_DATA. Idempotent (UNIQUE constraint + INSERT
    OR REPLACE), so this is safe to run on every startup and picks up any
    new seed rows added in code without re-creating the DB."""
    for rec in SEED_DATA:
        upsert(rec)


# ---- TMC community sheet (European registrations) ----

# Column layout in the main tab of the community sheet. The columns are:
# 0=blank, 1=section labels, 2=country, 3=YTD, 4=Jan, 5=Feb, 6=Mar, 7=Q1,
# 8=Apr, 9=May, 10=Jun, 11=Q2, 12=Jul, 13=Aug, 14=Sep, 15=Q3, 16=Oct,
# 17=Nov, 18=Dec, 19=Q4.
_TMC_MONTH_COLS = {1: 4, 2: 5, 3: 6, 4: 8, 5: 9, 6: 10,
                   7: 12, 8: 13, 9: 14, 10: 16, 11: 17, 12: 18}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_community_sheet() -> Optional[pd.DataFrame]:
    """Pull European registration data live from the TMC-hosted community
    Google Sheet. Returns a long-format dataframe with columns: country,
    model, period_start, units. None on failure."""
    api_key = st.secrets.get("GOOGLE_API_KEY", "")
    if not api_key:
        st.error("GOOGLE_API_KEY not found in .streamlit/secrets.toml. "
                 "European data will be unavailable until that's set.")
        return None

    # Step 1: discover the first tab's title (varies by year)
    meta_url = (f"https://sheets.googleapis.com/v4/spreadsheets/"
                f"{TMC_SHEET_ID}?key={api_key}")
    try:
        req = urllib.request.Request(meta_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            meta = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        st.warning(f"Community sheet metadata fetch failed: {e}")
        return None

    sheets_meta = meta.get("sheets", [])
    if not sheets_meta:
        return None
    first_tab = sheets_meta[0]["properties"]["title"]

    # Step 2: fetch values from the main tab
    rng = urllib.parse.quote(f"{first_tab}!A1:T250")
    values_url = (f"https://sheets.googleapis.com/v4/spreadsheets/"
                  f"{TMC_SHEET_ID}/values/{rng}?key={api_key}")
    try:
        req = urllib.request.Request(values_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        st.warning(f"Community sheet values fetch failed: {e}")
        return None

    values = data.get("values", [])
    if not values:
        return None
    return _parse_tmc_main_tab(values)


def _parse_tmc_main_tab(values: list[list[str]]) -> pd.DataFrame:
    """Parse the multi-section CSV-like layout. Each model has its own
    section, separated by 'Model X Registrations in Europe in YYYY' headers."""
    # Pad ragged rows so iat() doesn't fall off the end
    width = max((len(r) for r in values), default=0)
    rows = [r + [""] * (width - len(r)) for r in values]

    section_pat = re.compile(
        r"Model\s+(\S+)\s+Registrations in Europe in (\d{4})", re.I
    )
    sections = []
    for i, row in enumerate(rows):
        cell = row[1] if len(row) > 1 else ""
        m = section_pat.search(str(cell))
        if m:
            sections.append((i, m.group(1), int(m.group(2))))

    records = []
    for s_idx, (start_row, model, year) in enumerate(sections):
        end_row = sections[s_idx + 1][0] if s_idx + 1 < len(sections) else len(rows)
        # Country data rows start 2 rows below the section header
        # (header + column-name row)
        for r in range(start_row + 2, end_row):
            country = str(rows[r][2]).strip() if len(rows[r]) > 2 else ""
            if not country:
                continue
            if country == "Total" or country.lower().startswith("tesla fans"):
                break
            display_country = "Other Europe" if country == "Other" else country

            for month_num, col in _TMC_MONTH_COLS.items():
                if col >= len(rows[r]):
                    continue
                cell = str(rows[r][col]).replace(",", "").strip()
                if not cell or cell == "0":
                    continue
                try:
                    units = int(cell)
                except ValueError:
                    continue
                records.append({
                    "country": display_country,
                    "model": f"Model {model}",
                    "period_start": date(year, month_num, 1).isoformat(),
                    "units": units,
                })
    return pd.DataFrame(records)


def load_combined_df() -> pd.DataFrame:
    """Combine local SQLite (China weekly + Tesla IR) with the live TMC
    community pull (European monthly registrations). Returns a dataframe
    with the same schema as load_df() so existing tab code keeps working."""
    local = load_df()
    community = fetch_community_sheet()
    if community is None or community.empty:
        return local

    # Aggregate community: sum across models per country/month for total Tesla
    agg = (community.groupby(["country", "period_start"])["units"]
                    .sum().reset_index())
    agg["region"] = "Europe"
    agg["period_type"] = "monthly"
    agg["metric"] = "registration"
    agg["source"] = "TMC community sheet"
    agg["source_url"] = TMC_SHEET_URL
    agg["notes"] = ""
    agg["ingested_at"] = datetime.utcnow().isoformat()
    agg["id"] = -1
    agg["period_start"] = pd.to_datetime(agg["period_start"])

    # Drop any local European monthly registration rows that the community
    # sheet covers; community is authoritative for that data slice.
    if not local.empty:
        local_mask = (
            (local["region"] == "Europe") &
            (local["period_type"] == "monthly") &
            (local["metric"] == "registration")
        )
        local = local[~local_mask]

    return pd.concat([agg, local], ignore_index=True)


# ---- CnEVPost scraper ----

def _parse_week_ending(url: str, html: str, pub_date: date) -> Optional[date]:
    """Extract the week-ending date. URL slug is the most reliable signal."""
    # URL: .../china-ev-insurance-registrations-week-ending-sept-14-2025/
    m = re.search(r"week-ending-([a-z]+)-(\d{1,2})-(\d{4})", url, re.I)
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y"
            ).date()
        except ValueError:
            pass
    # Title/body fallback: "week ending Sept 14"
    m = re.search(r"week ending\s+([A-Za-z]+)\s+(\d{1,2})", html, re.I)
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)[:3]} {m.group(2)} {pub_date.year}", "%b %d %Y"
            ).date()
        except ValueError:
            pass
    return None


def _extract_tesla_units(html: str) -> Optional[int]:
    """Find the weekly Tesla insurance number. Title first, then body."""
    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = title_m.group(1) if title_m else ""
    # Title pattern is consistent: "...insurance registrations for week ending
    # Sept 21: Nio Inc 6,670, Tesla 17,300, Xiaomi 10,800..." Only trust
    # the title number when the title is clearly about insurance registrations.
    m = None
    if re.search(r"insurance registrations", title, re.I):
        m = re.search(r"Tesla\s+(\d{1,3}(?:,\d{3})+|\d{4,5})", title)
    if not m:
        # Body fallback, anchored by an action verb to avoid false positives
        m = re.search(
            r"Tesla(?:\s*\([^)]+\))?\s+(?:had|recorded|reached|saw|posted)\s+"
            r"(\d{1,3}(?:,\d{3})+|\d{4,5})\s+(?:insurance|new|vehicle)",
            html,
        )
    if not m:
        return None
    try:
        units = int(m.group(1).replace(",", ""))
    except ValueError:
        return None
    # Sanity: Tesla weekly China is roughly 5k-25k. Bound loosely.
    if 1000 <= units <= 100_000:
        return units
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_cnevpost(limit: int = 10) -> list[dict]:
    """Scrape the CnEVPost insurance-registrations tag page for recent
    weekly posts. Returns a list of upsertable record dicts."""
    try:
        req = urllib.request.Request(CNEVPOST_TAG_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            index_html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        st.warning(f"CnEVPost index fetch failed: {e}")
        return []

    url_pat = (
        r'href="(https://cnevpost\.com/(\d{4})/(\d{2})/(\d{2})/'
        r'[^"]*insurance-registrations[^"]*)"'
    )
    seen, posts = set(), []
    for m in re.finditer(url_pat, index_html):
        url = m.group(1)
        if url in seen:
            continue
        seen.add(url)
        posts.append({
            "url": url,
            "pub_date": date(int(m.group(2)), int(m.group(3)), int(m.group(4))),
        })
        if len(posts) >= limit:
            break

    records = []
    for p in posts:
        try:
            req = urllib.request.Request(p["url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                post_html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            continue

        week_end = _parse_week_ending(p["url"], post_html, p["pub_date"])
        units = _extract_tesla_units(post_html)
        if not week_end or not units:
            continue

        period_start = week_end - timedelta(days=6)
        records.append({
            "country": "China",
            "region": "China",
            "period_start": period_start.isoformat(),
            "period_type": "weekly",
            "metric": "insurance",
            "units": units,
            "source": "CnEVPost",
            "source_url": p["url"],
            "notes": f"Week ending {week_end.isoformat()}",
        })

    return records


# ---- UI ----

def _sidebar_refresh() -> None:
    st.header("Data sources")
    st.caption("European data pulls live from the TMC community sheet. "
               "China weekly pulls from CnEVPost. Both can be refreshed below.")

    if st.button("Refresh European data (TMC sheet)", use_container_width=True):
        fetch_community_sheet.clear()
        with st.spinner("Pulling TMC community sheet..."):
            community = fetch_community_sheet()
        if community is not None and not community.empty:
            n_rows = len(community)
            n_countries = community["country"].nunique()
            st.success(f"Loaded {n_rows} model-country-month rows across "
                       f"{n_countries} countries.")
        else:
            st.warning("No data returned — check your API key and that the "
                       "Sheets API is enabled.")
        st.rerun()
    st.caption("Cached for 1 hour. Click to force a fresh pull.")

    if st.button("Refresh China weekly (CnEVPost)", use_container_width=True):
        with st.spinner("Scraping CnEVPost..."):
            new = fetch_cnevpost(limit=10)
        n = sum(1 for r in new if upsert(r))
        if n:
            st.success(f"Inserted/updated {n} weekly records")
            st.cache_data.clear()
            st.rerun()
        else:
            st.info("No new records (already current, or parser couldn't match the page).")
    st.caption("New data posts Mon/Tue Beijing time "
               "(Sun night / Mon morning US Pacific). Once a week is enough.")


def _quarter_of(d: date) -> tuple[int, int]:
    """Return (year, quarter_number) for a date."""
    return d.year, (d.month - 1) // 3 + 1


def _quarter_bounds(year: int, q: int) -> tuple[date, date]:
    """First day and last day of a quarter."""
    start = date(year, (q - 1) * 3 + 1, 1)
    if q == 4:
        end = date(year, 12, 31)
    else:
        end = date(year, q * 3 + 1, 1) - timedelta(days=1)
    return start, end


def _tab_quarter(df: pd.DataFrame) -> None:
    today = date.today()
    cur_year, cur_q = _quarter_of(today)
    q_start, q_end = _quarter_bounds(cur_year, cur_q)
    quarter_label = f"Q{cur_q} {cur_year}"

    st.subheader(f"{quarter_label} delivery tracker")
    st.caption(
        f"Building a bottom-up estimate of Tesla's {quarter_label} global "
        f"deliveries from publicly reported registration data. Tesla reports "
        f"the official global number ~3 days after quarter-end "
        f"({q_end.strftime('%b %d')})."
    )

    if df.empty:
        st.info("No data loaded.")
        return

    # Slice: anything whose period_start falls inside the current quarter.
    in_q = df[(df["period_start"] >= pd.Timestamp(q_start)) &
              (df["period_start"] <= pd.Timestamp(q_end))]

    # Monthly registrations (the main bottom-up signal for non-China markets)
    monthly = in_q[(in_q["period_type"] == "monthly") &
                   (in_q["metric"] == "registration")]
    monthly_total = int(monthly["units"].sum())
    countries_reporting = monthly["country"].nunique()

    # China weekly insurance (separate retail proxy; don't add to monthly)
    china_weekly = in_q[(in_q["country"] == "China") &
                        (in_q["period_type"] == "weekly") &
                        (in_q["metric"] == "insurance")]
    china_weekly_total = int(china_weekly["units"].sum())
    china_weeks = len(china_weekly)

    # Reference: Tesla's reported delivery for the same quarter last year
    prior_year_q = df[
        (df["country"] == "Global") &
        (df["metric"] == "delivery") &
        (df["period_start"] == pd.Timestamp(date(cur_year - 1, q_start.month, 1)))
    ]
    prior_year_total = int(prior_year_q["units"].iloc[0]) if not prior_year_q.empty else None

    # Reference: previous quarter's reported delivery
    prev_year = cur_year if cur_q > 1 else cur_year - 1
    prev_q = cur_q - 1 if cur_q > 1 else 4
    prev_q_start, _ = _quarter_bounds(prev_year, prev_q)
    prev_q_row = df[
        (df["country"] == "Global") &
        (df["metric"] == "delivery") &
        (df["period_start"] == pd.Timestamp(prev_q_start))
    ]
    prev_q_total = int(prev_q_row["units"].iloc[0]) if not prev_q_row.empty else None

    # Headline metrics
    c1, c2, c3 = st.columns(3)
    c1.metric(
        f"{quarter_label} Europe-tracked",
        f"{monthly_total:,}",
        f"{countries_reporting} countries reporting",
    )
    c2.metric(
        f"{quarter_label} China weekly (CnEVPost)",
        f"{china_weekly_total:,}",
        f"{china_weeks} weeks of insurance data",
    )
    if prior_year_total:
        c3.metric(
            f"Q{cur_q} {cur_year - 1} reported (Tesla IR)",
            f"{prior_year_total:,}",
            "global delivery total",
        )

    if prev_q_total:
        st.caption(
            f"Previous quarter (Q{prev_q} {prev_year}) reported delivery: "
            f"**{prev_q_total:,}** (global, Tesla IR). The tracked numbers above "
            f"are a partial bottom-up read of {quarter_label}; they will always be "
            f"smaller than the global figure because they only cover the markets "
            f"with public registration data."
        )

    # Coverage matrix: country x month
    st.markdown("#### Country × month matrix (monthly registrations)")
    if monthly.empty:
        st.info("No monthly registrations recorded in this quarter yet.")
    else:
        m = monthly.copy()
        m["month_label"] = m["period_start"].dt.strftime("%b")
        # Build column order matching quarter months
        month_cols = []
        for i in range(3):
            mo = (q_start.month + i - 1) % 12 + 1
            yr = q_start.year + ((q_start.month + i - 1) // 12)
            month_cols.append(date(yr, mo, 1).strftime("%b"))
        matrix = m.pivot_table(
            index="country", columns="month_label", values="units",
            aggfunc="sum", fill_value=0,
        ).reindex(columns=month_cols, fill_value=0)
        matrix["Q total"] = matrix.sum(axis=1)
        # Display 0s as dashes
        display = matrix.replace(0, "—").astype(str)
        for col in matrix.columns:
            display[col] = matrix[col].apply(
                lambda x: f"{int(x):,}" if x else "—"
            )
        st.dataframe(display, use_container_width=True)

    # China weekly bars
    if not china_weekly.empty:
        st.markdown("#### China weekly insurance (CnEVPost, this quarter)")
        cw = china_weekly.sort_values("period_start")
        fig = px.bar(
            cw, x="period_start", y="units",
            title=f"China weekly insurance registrations during {quarter_label}",
        )
        fig.update_layout(height=320, yaxis_title="Units", xaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

    # Historical quarterly Tesla IR context
    st.markdown("#### Tesla reported quarterly deliveries (for context)")
    hist = df[
        (df["country"] == "Global") &
        (df["metric"] == "delivery")
    ].sort_values("period_start")
    if not hist.empty:
        hist_display = hist[["period_start", "units", "notes"]].copy()
        hist_display["quarter"] = hist_display["period_start"].apply(
            lambda d: f"Q{(d.month - 1) // 3 + 1} {d.year}"
        )
        hist_display = hist_display[["quarter", "units", "notes"]]
        hist_display.columns = ["Quarter", "Deliveries", "Notes"]
        hist_display["Deliveries"] = hist_display["Deliveries"].apply(
            lambda x: f"{int(x):,}"
        )
        st.dataframe(hist_display, use_container_width=True, hide_index=True)


def _tab_latest(df: pd.DataFrame) -> None:
    st.subheader("Most recent record per country / metric")
    if df.empty:
        st.info("No data loaded.")
        return
    latest = (
        df.sort_values("period_start", ascending=False)
          .drop_duplicates(subset=["country", "metric"], keep="first")
    )
    st.dataframe(
        latest[["country", "region", "period_start", "period_type",
                "metric", "units", "source", "notes"]],
        use_container_width=True, hide_index=True,
        column_config={
            "period_start": st.column_config.DateColumn("Period start"),
            "units": st.column_config.NumberColumn("Units", format="%d"),
        },
    )


def _tab_monthly(df: pd.DataFrame) -> None:
    st.subheader("Monthly registrations by country")
    monthly = df[(df["period_type"] == "monthly") &
                 (df["metric"] == "registration")]
    if monthly.empty:
        st.info("No monthly registration data yet. Add some via the sidebar.")
        return
    countries = sorted(monthly["country"].unique())
    default = countries[: min(6, len(countries))]
    chosen = st.multiselect("Countries", countries, default=default)
    sub = monthly[monthly["country"].isin(chosen)].sort_values("period_start")
    if sub.empty:
        return
    fig = px.line(
        sub, x="period_start", y="units", color="country", markers=True,
        title="Tesla monthly registrations (national agencies)",
    )
    fig.update_layout(
        height=480, hovermode="x unified",
        yaxis_title="Units", xaxis_title="",
    )
    st.plotly_chart(fig, use_container_width=True)


def _tab_china(df: pd.DataFrame) -> None:
    st.subheader("China weekly insurance registrations (CnEVPost)")
    weekly = df[(df["country"] == "China") & (df["period_type"] == "weekly")]
    if weekly.empty:
        st.info(
            "No weekly China data yet. Click 'Pull latest from CnEVPost' "
            "in the sidebar."
        )
        return
    weekly = weekly.sort_values("period_start").copy()
    weekly["rolling_4w"] = weekly["units"].rolling(4).mean()
    fig = px.bar(
        weekly, x="period_start", y="units",
        title="Tesla weekly insurance registrations in China",
    )
    fig.add_scatter(
        x=weekly["period_start"], y=weekly["rolling_4w"],
        mode="lines", name="4-week avg", line=dict(width=3),
    )
    fig.update_layout(
        height=480, yaxis_title="Units", xaxis_title="", showlegend=True,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(
        weekly[["period_start", "units", "notes", "source_url"]]
            .sort_values("period_start", ascending=False),
        use_container_width=True, hide_index=True,
    )


def _tab_all(df: pd.DataFrame) -> None:
    st.subheader("All ingested data")
    st.dataframe(df, use_container_width=True, hide_index=True)
    if not df.empty:
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV", csv, "tesla_sales.csv", "text/csv"
        )


def _tab_about() -> None:
    st.markdown(f"""
### Sources

- **TMC community sheet** (auto-pulled hourly via Google Sheets API):
  *Tesla Europe Registration Stats*, maintained by volunteers in the
  [Tesla Motors Club forum]({TMC_SHEET_URL}). Per-country, per-model,
  per-month Tesla registrations across ~16 European markets. Credit goes
  to the maintainers (Darkandstormy, Mrdoubleb, Hobbes, Troy, and others
  listed in each section of the sheet).
- **CnEVPost** (auto-scraped): China weekly Tesla insurance registrations,
  published Mondays/Tuesdays. <{CNEVPOST_TAG_URL}>
- **Tesla IR** (in-code seed): quarterly global delivery numbers, used as
  the ground-truth reference row. Update `SEED_DATA` once per quarter
  after the press release. <https://ir.tesla.com>

### Metrics — these are not interchangeable

- `registration`: vehicle entered in a national database. Lags delivery
  by days/weeks. (European national agencies, via TMC sheet.)
- `insurance`: vehicle insured. China-specific retail proxy. (CnEVPost.)
- `delivery`: Tesla's reported deliveries (quarterly press release;
  global ground truth).
- `wholesale`: factory-to-dealer shipment. CPCA China wholesale includes
  Giga Shanghai exports, which is not the same as China retail demand.

### Limitations

- The TMC sheet typically lags individual X aggregators (Roland Pircher
  et al.) by a day or two because the community validates each entry
  before approving it. For a real-time read, the X feeds are faster;
  this dashboard prioritizes validated data over speed.
- The CnEVPost scraper depends on their HTML layout. If they change it,
  no records are inserted (it fails closed, not silently wrong). Fix the
  regex in `_extract_tesla_units` and `_parse_week_ending`.
- SQLite at `data/tesla_sales.db` is local-only and now only stores
  China weekly + Tesla IR. European data is never written to disk; it's
  fetched fresh from the TMC sheet every hour.
""")


def main() -> None:
    st.set_page_config(
        page_title="Tesla Regional Sales",
        layout="wide",
        page_icon="🚗",
    )
    st.title("🚗 Tesla Regional Sales Dashboard")
    st.caption(
        "Tesla vehicle registrations and deliveries by country, aggregated "
        "from national agencies, CnEVPost weekly insurance data, and "
        "Tesla IR. Local SQLite store."
    )

    init_db()
    seed_baseline()

    with st.sidebar:
        _sidebar_refresh()

    df = load_combined_df()
    tab_q, tab_latest, tab_monthly, tab_china, tab_all, tab_about = st.tabs(
        ["🎯 Quarter tracker", "📊 Latest", "📈 Monthly trends",
         "🇨🇳 China weekly", "🗂 All data", "ℹ️ About"]
    )
    with tab_q:
        _tab_quarter(df)
    with tab_latest:
        _tab_latest(df)
    with tab_monthly:
        _tab_monthly(df)
    with tab_china:
        _tab_china(df)
    with tab_all:
        _tab_all(df)
    with tab_about:
        _tab_about()


if __name__ == "__main__":
    main()
