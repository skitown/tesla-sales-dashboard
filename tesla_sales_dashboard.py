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
# Curated from agency releases reported in May-June 2026. Replace/extend by
# pasting from KBA, OFV, SMMT, PFA, Mobility Sweden, bilstatistik.dk, etc.

SEED_DATA = [
    # Germany (KBA)
    {"country": "Germany", "region": "Europe", "period_start": "2026-05-01",
     "period_type": "monthly", "metric": "registration", "units": 5111,
     "source": "KBA", "source_url": "https://www.kba.de",
     "notes": "+322% YoY"},
    {"country": "Germany", "region": "Europe", "period_start": "2026-03-01",
     "period_type": "monthly", "metric": "registration", "units": 9252,
     "source": "KBA", "source_url": "https://www.kba.de",
     "notes": "Best-ever March in Germany; +315% YoY"},

    # France (PFA)
    {"country": "France", "region": "Europe", "period_start": "2026-05-01",
     "period_type": "monthly", "metric": "registration", "units": 5446,
     "source": "PFA", "source_url": "https://pfa-auto.fr",
     "notes": "+655% YoY; best May ever in France"},
    {"country": "France", "region": "Europe", "period_start": "2026-03-01",
     "period_type": "monthly", "metric": "registration", "units": 9569,
     "source": "PFA", "source_url": "https://pfa-auto.fr",
     "notes": "+203% YoY; near all-time monthly record"},

    # Norway (OFV)
    {"country": "Norway", "region": "Europe", "period_start": "2026-05-01",
     "period_type": "monthly", "metric": "registration", "units": 3345,
     "source": "OFV", "source_url": "https://ofv.no",
     "notes": "+29% YoY; 21.5% market share"},
    {"country": "Norway", "region": "Europe", "period_start": "2026-03-01",
     "period_type": "monthly", "metric": "registration", "units": 6150,
     "source": "OFV", "source_url": "https://ofv.no",
     "notes": "+178% YoY"},

    # Sweden (Mobility Sweden)
    {"country": "Sweden", "region": "Europe", "period_start": "2026-05-01",
     "period_type": "monthly", "metric": "registration", "units": 858,
     "source": "Mobility Sweden", "source_url": "https://mobilitysweden.se",
     "notes": "+71% YoY"},
    {"country": "Sweden", "region": "Europe", "period_start": "2026-03-01",
     "period_type": "monthly", "metric": "registration", "units": 1447,
     "source": "Mobility Sweden", "source_url": "https://mobilitysweden.se",
     "notes": "+144% YoY"},

    # Denmark (bilstatistik.dk)
    {"country": "Denmark", "region": "Europe", "period_start": "2026-05-01",
     "period_type": "monthly", "metric": "registration", "units": 1750,
     "source": "bilstatistik.dk", "source_url": "https://bilstatistik.dk",
     "notes": "+136% YoY; Model Y top-selling vehicle"},
    {"country": "Denmark", "region": "Europe", "period_start": "2026-03-01",
     "period_type": "monthly", "metric": "registration", "units": 1784,
     "source": "bilstatistik.dk", "source_url": "https://bilstatistik.dk",
     "notes": "+96% YoY"},

    # UK (SMMT)
    {"country": "UK", "region": "Europe", "period_start": "2026-03-01",
     "period_type": "monthly", "metric": "registration", "units": 8599,
     "source": "SMMT", "source_url": "https://www.smmt.co.uk",
     "notes": "+20% YoY; 5,177 Model Y"},

    # April 2026 partial fill for Q2 tracker (more to add)
    {"country": "Germany", "region": "Europe", "period_start": "2026-04-01",
     "period_type": "monthly", "metric": "registration", "units": 3149,
     "source": "KBA", "source_url": "https://www.kba.de",
     "notes": "+256% YoY; best-ever April in Germany (via ACEA)"},

    # Norway full-quarter history (good case study; OFV publishes 1st of month)
    {"country": "Norway", "region": "Europe", "period_start": "2026-01-01",
     "period_type": "monthly", "metric": "registration", "units": 83,
     "source": "OFV", "source_url": "https://ofv.no",
     "notes": "Subsidy expiration crater; lowest in 3 years"},
    {"country": "Norway", "region": "Europe", "period_start": "2026-02-01",
     "period_type": "monthly", "metric": "registration", "units": 1210,
     "source": "OFV", "source_url": "https://ofv.no",
     "notes": "+75.6% YoY; rebound from January"},

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
    st.header("Auto-refresh")
    st.caption("Only China weekly data is auto-scraped. European monthly "
               "figures go in via the form below.")
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


def _sidebar_manual_entry() -> None:
    st.divider()
    st.header("Manual entry")
    st.caption("Monthly figures from European agencies (KBA, OFV, SMMT, PFA, "
               "etc.). Pick a country and the source fills in automatically.")
    with st.form("manual_add", clear_on_submit=True):
        country = st.selectbox("Country", list(COUNTRY_PRESETS.keys()))
        month = st.selectbox("Month", _last_n_months(18))
        units = st.number_input("Tesla units", min_value=1, step=1, value=None,
                                placeholder="e.g. 5111")
        notes = st.text_input("Notes (optional)",
                              placeholder="e.g. +75% YoY, record month")
        submitted = st.form_submit_button("Add", use_container_width=True)
        if not submitted:
            return
        if units is None or units < 1:
            st.error("Please enter a units value greater than 0.")
            return
        preset = COUNTRY_PRESETS[country]
        year_str, month_str = month.split("-")
        ok = upsert({
            "country": country,
            "region": preset["region"],
            "period_start": date(int(year_str), int(month_str), 1).isoformat(),
            "period_type": "monthly",
            "metric": "registration",
            "units": int(units),
            "source": preset["source"],
            "source_url": preset["source_url"],
            "notes": notes.strip() if notes else "",
        })
        if ok:
            st.success(f"Added {country} {month}: {int(units):,} units "
                       f"(source: {preset['source']})")
            st.rerun()
        else:
            st.error("Insert failed — check the terminal for details.")


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

- **National registration agencies** (manual entry): KBA (Germany), OFV (Norway),
  SMMT (UK), PFA (France), Mobility Sweden, bilstatistik.dk (Denmark),
  ANFAC (Spain), RDW (Netherlands). Monthly, 1-5 days after month-end.
- **CnEVPost** (auto-scraped): China weekly Tesla insurance registrations,
  published Mondays/Tuesdays. <{CNEVPOST_TAG_URL}>
- **Tesla IR** (manual): quarterly global delivery numbers, reconciliation row.
  <https://ir.tesla.com>
- **Robbie Andrew** (optional context, not yet ingested): pre-aggregated
  monthly car-sales CSV, ~25 countries, CC-BY 4.0. <{ROBBIE_ANDREW_PAGE}>

### Metrics - these are not interchangeable

- `registration`: vehicle entered in a national database. Lags delivery
  by days/weeks.
- `insurance`: vehicle insured. China-specific retail proxy.
- `wholesale`: factory-to-dealer shipment. CPCA wholesale includes
  Giga Shanghai exports, which is not the same as China retail demand.
- `delivery`: Tesla's reported deliveries (quarterly press release;
  global ground truth).

### Limitations

- Manual seed data covers a partial slice of recent European months.
  Backfill by pasting each agency's monthly figure via the sidebar form.
- The CnEVPost scraper depends on their HTML layout. If they change it,
  no records are inserted (it fails closed, not silently wrong). Fix the
  regex in `_extract_tesla_units` and `_parse_week_ending`.
- SQLite at `data/tesla_sales.db` is local-only. For shared multi-user
  persistence (e.g. Streamlit Cloud), swap `get_conn()` for a Postgres
  connection (Neon, Supabase, or Turso libSQL).
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
        _sidebar_manual_entry()

    df = load_df()
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
