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


# Rest-of-World countries tracked by X aggregators (@piloly, @Tslachan,
# @TheEVuniverse, @hxm_196_44, etc.). These show as placeholder rows in the
# country matrix until manual entry is implemented. Sources noted per country.
ROW_PLACEHOLDER_COUNTRIES = [
    "Australia",   # @piloly (VFACTS, ~5th of following month)
    "Korea",       # @Tslachan
    "Japan",       # @TheEVuniverse
    "Hong Kong",   # @piloly
    "Taiwan",      # @hxm_196_44
    "Colombia",    # @piloly
    "Turkey",      # @piloly
    "USA",         # no real-time public source; estimate from Cox/KBB analysts
]


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

    # Tesla China monthly seed (CPCA via CnEVPost). These will be auto-extended
    # by fetch_cnevpost_monthly. Wholesale = CPCA total (includes Giga Shanghai
    # exports); retail = CPCA domestic-only.
    {"country": "China", "region": "China", "period_start": "2026-04-01",
     "period_type": "monthly", "metric": "wholesale", "units": 79478,
     "source": "CPCA via CnEVPost", "source_url": "https://cnevpost.com",
     "notes": "April 2026 wholesale (includes Giga Shanghai exports)"},
    {"country": "China", "region": "China", "period_start": "2026-05-01",
     "period_type": "monthly", "metric": "wholesale", "units": 85982,
     "source": "CPCA via CnEVPost", "source_url": "https://cnevpost.com",
     "notes": "May 2026 wholesale; +39.4% YoY; highest of 2026 so far"},
    {"country": "China", "region": "China", "period_start": "2026-04-01",
     "period_type": "monthly", "metric": "retail", "units": 25956,
     "source": "CPCA via CnEVPost", "source_url": "https://cnevpost.com",
     "notes": "April 2026 domestic retail (excludes 53,522 exports)"},
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


def delete_row(country: str, period_start: str, period_type: str,
               metric: str, source: str) -> int:
    """Delete a row matching the unique key. Returns the number of rows
    deleted (0 if no match, 1 if deleted). Used to clear manual entries."""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                """DELETE FROM tesla_sales
                   WHERE country=? AND period_start=? AND period_type=?
                     AND metric=? AND source=?""",
                (country, period_start, period_type, metric, source),
            )
            conn.commit()
            return cur.rowcount
    except Exception as e:
        st.error(f"Delete error: {e}")
        return 0


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


# ---- CnEVPost monthly Tesla China scraper ----
#
# CnEVPost stopped publishing weekly Tesla insurance registrations in Oct 2025.
# What they DO still publish, monthly, ~3-5 days after each month-end:
#
#   - "Tesla China {Month} wholesale volume reaches {N} units" (CPCA wholesale,
#     includes Giga Shanghai exports). URL: /tesla-china-{month}-{year}-wholesale
#   - "Tesla's {Month} China retail breakdown" (CPCA domestic retail, by model).
#     URL: /tesla-{month}-{year}-china-retail-breakdown
#
# Wholesale comes out first. Retail breakdown follows a few days later.

_MONTH_NAME_TO_NUM = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _extract_china_wholesale(html: str) -> Optional[int]:
    """Pull the wholesale number from a tesla-china-{month}-{year}-wholesale
    post. The number is reliably in the title."""
    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = title_m.group(1) if title_m else ""
    # "Tesla China May wholesale volume reaches 85,982 units, ..."
    patterns = [
        r"wholesale\s+volume\s+(?:reache[sd]|hits?)\s+(\d{1,3}(?:,\d{3})+)",
        r"wholesale\s+(?:sales\s+)?reache[sd]\s+(\d{1,3}(?:,\d{3})+)",
        r"Tesla\s+China\s+sold\s+(\d{1,3}(?:,\d{3})+)\s+vehicles",
    ]
    for pat in patterns:
        m = re.search(pat, title, re.I)
        if m:
            try:
                val = int(m.group(1).replace(",", ""))
            except ValueError:
                continue
            # Sanity: Tesla China monthly wholesale is roughly 30k-100k.
            if 10_000 <= val <= 200_000:
                return val
    return None


def _extract_china_retail(html: str) -> Optional[int]:
    """Pull the retail number from a tesla-{month}-{year}-china-retail-breakdown
    post. The total is usually in the body in the format 'Tesla's {N} retail
    sales in China' or 'Model Y accounted for X% of Tesla's {N} retail sales'."""
    patterns = [
        r"Tesla'?s?\s+(\d{1,3}(?:,\d{3})+)\s+retail\s+sales\s+in\s+China",
        r"Tesla'?s?\s+domestic\s+retail\s+sales\s+in\s+China\s+(?:in\s+\w+\s+)?"
        r"(?:were|came in at|stood at|totaled|reached)\s+(\d{1,3}(?:,\d{3})+)",
        r"retail\s+sales\s+in\s+China\s+(?:for\s+\w+\s+)?"
        r"(?:totaled|came in at|stood at|reached|were)\s+(\d{1,3}(?:,\d{3})+)",
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            try:
                val = int(m.group(1).replace(",", ""))
            except ValueError:
                continue
            # Sanity: Tesla China monthly retail is roughly 15k-100k.
            if 5_000 <= val <= 150_000:
                return val
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_cnevpost_monthly(limit: int = 12) -> list[dict]:
    """Scrape CnEVPost's Tesla category for monthly wholesale + retail posts."""
    try:
        req = urllib.request.Request(
            "https://cnevpost.com/tesla/",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            index_html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        st.warning(f"CnEVPost Tesla index fetch failed: {e}")
        return []

    wholesale_pat = re.compile(
        r'href="(https://cnevpost\.com/\d{4}/\d{2}/\d{2}/'
        r'tesla-china-([a-z]+)-(\d{4})-wholesale/?)"',
        re.I,
    )
    retail_pat = re.compile(
        r'href="(https://cnevpost\.com/\d{4}/\d{2}/\d{2}/'
        r'tesla-([a-z]+)-(\d{4})-china-retail-breakdown/?)"',
        re.I,
    )

    posts, seen = [], set()
    for m in wholesale_pat.finditer(index_html):
        if m.group(1) in seen:
            continue
        seen.add(m.group(1))
        posts.append({"url": m.group(1), "month": m.group(2),
                      "year": int(m.group(3)), "metric": "wholesale"})
    for m in retail_pat.finditer(index_html):
        if m.group(1) in seen:
            continue
        seen.add(m.group(1))
        posts.append({"url": m.group(1), "month": m.group(2),
                      "year": int(m.group(3)), "metric": "retail"})
    posts = posts[:limit]

    records = []
    for p in posts:
        month_num = _MONTH_NAME_TO_NUM.get(p["month"].lower())
        if not month_num:
            continue
        try:
            req = urllib.request.Request(p["url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                post_html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            continue
        units = (_extract_china_wholesale(post_html) if p["metric"] == "wholesale"
                 else _extract_china_retail(post_html))
        if not units:
            continue
        records.append({
            "country": "China",
            "region": "China",
            "period_start": date(p["year"], month_num, 1).isoformat(),
            "period_type": "monthly",
            "metric": p["metric"],
            "units": units,
            "source": "CPCA via CnEVPost",
            "source_url": p["url"],
            "notes": f"Tesla China {p['metric']} for {p['month']} {p['year']}",
        })

    return records


# ---- UI ----

def _sidebar_refresh() -> None:
    st.header("Data sources")

    if st.button("Refresh all data sources", width="stretch"):
        msg_parts, warnings = [], []

        # TMC community sheet (European registrations)
        fetch_community_sheet.clear()
        with st.spinner("Pulling TMC sheet and CnEVPost..."):
            community = fetch_community_sheet()
            fetch_cnevpost_monthly.clear()
            cn_records = fetch_cnevpost_monthly(limit=12)

        if community is not None and not community.empty:
            n_rows = len(community)
            n_countries = community["country"].nunique()
            msg_parts.append(
                f"**TMC:** {n_rows:,} rows · {n_countries} countries"
            )
        else:
            warnings.append("TMC: no data returned (check API key)")

        # CnEVPost monthly Tesla China
        n_cn = sum(1 for r in cn_records if upsert(r))
        if n_cn:
            msg_parts.append(
                f"**CnEVPost:** {n_cn} monthly record{'s' if n_cn != 1 else ''}"
            )
        else:
            warnings.append("CnEVPost: no new records "
                            "(already current or parser miss)")

        if msg_parts:
            st.success(" · ".join(msg_parts))
        if warnings:
            for w in warnings:
                st.info(w)

        st.cache_data.clear()
        st.rerun()

    st.caption(
        "**Europe** via TMC sheet — agencies report the first week of each "
        "month. **China** via CnEVPost — CPCA wholesale ~3 days after "
        "month-end, retail ~10 days later. Cached for 1 hour."
    )

    # ── Manual entry for Rest-of-World countries ─────────────────────────
    st.markdown("---")
    st.subheader("Add RoW data")
    st.caption(
        "For countries without an auto-feed (Australia, Korea, Japan, "
        "Hong Kong, Taiwan, Colombia, Turkey, USA). Paste numbers from "
        "@piloly / @Tslachan / @TheEVuniverse / @hxm_196_44 X posts."
    )

    # Build current quarter month options
    today_d = date.today()
    cur_q_num = (today_d.month - 1) // 3 + 1
    q_first_month = (cur_q_num - 1) * 3 + 1
    quarter_months = []
    for i in range(3):
        mo = q_first_month + i
        quarter_months.append({
            "label": date(today_d.year, mo, 1).strftime("%B %Y"),
            "year": today_d.year,
            "month": mo,
        })

    with st.form("row_manual_entry", clear_on_submit=True):
        country = st.selectbox("Country", ROW_PLACEHOLDER_COUNTRIES)
        month_label = st.selectbox(
            "Month", [m["label"] for m in quarter_months]
        )
        units = st.number_input(
            "Units (vehicles)", min_value=0, max_value=50_000, value=0,
            step=1,
            help="Set to 0 to clear/remove a previously-entered value for "
                 "this country and month.",
        )
        source_url = st.text_input(
            "Source URL (X post link)",
            placeholder="https://x.com/piloly/status/...",
        )
        submitted = st.form_submit_button("Submit", width="stretch")

        if submitted:
            sel = next(m for m in quarter_months
                       if m["label"] == month_label)
            period_start_iso = date(sel["year"], sel["month"], 1).isoformat()

            if units == 0:
                # Clear any existing manual entry for this country/month
                n = delete_row(
                    country=country,
                    period_start=period_start_iso,
                    period_type="monthly",
                    metric="registration",
                    source="X aggregator (manual)",
                )
                if n:
                    st.success(f"✓ Cleared {country} {month_label}")
                else:
                    st.info(f"No existing entry for {country} {month_label} "
                            "to clear.")
                st.cache_data.clear()
                st.rerun()
            else:
                record = {
                    "country": country,
                    "region": "RoW",
                    "period_start": period_start_iso,
                    "period_type": "monthly",
                    "metric": "registration",
                    "units": int(units),
                    "source": "X aggregator (manual)",
                    "source_url": source_url or "",
                    "notes": f"Manual entry for {country} {month_label}",
                }
                if upsert(record):
                    st.success(
                        f"✓ Added {country} {month_label}: {int(units):,} units"
                    )
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Failed to save (unknown SQLite error).")

    st.caption(
        "**Note:** On Streamlit Cloud, manual entries persist only until "
        "the container restarts (apps sleep after inactivity). For permanent "
        "values, add them to `SEED_DATA` in the code and commit."
    )


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

    # Monthly registrations (the main bottom-up signal for non-China markets).
    # Split into Europe (TMC auto-pull) vs RoW (manual entry).
    monthly = in_q[(in_q["period_type"] == "monthly") &
                   (in_q["metric"] == "registration")]
    row_monthly = monthly[monthly["country"].isin(ROW_PLACEHOLDER_COUNTRIES)]
    europe_monthly = monthly[~monthly["country"].isin(ROW_PLACEHOLDER_COUNTRIES)]

    europe_total = int(europe_monthly["units"].sum())
    europe_countries = europe_monthly["country"].nunique()
    row_total = int(row_monthly["units"].sum())
    row_countries = row_monthly["country"].nunique()

    # China monthly wholesale (CPCA total, includes Giga Shanghai exports)
    china_wholesale = in_q[(in_q["country"] == "China") &
                           (in_q["period_type"] == "monthly") &
                           (in_q["metric"] == "wholesale")]
    china_wholesale_total = int(china_wholesale["units"].sum())
    china_wholesale_months = china_wholesale["period_start"].nunique()

    # China monthly retail (CPCA domestic-only; the cleaner global-delivery
    # comparable, but published a few days later than wholesale)
    china_retail = in_q[(in_q["country"] == "China") &
                        (in_q["period_type"] == "monthly") &
                        (in_q["metric"] == "retail")]
    china_retail_total = int(china_retail["units"].sum())
    china_retail_months = china_retail["period_start"].nunique()

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

    # ── HEADLINE: ONE total tracked deliveries number ────────────────────
    # The bottom-up sum of all delivery-comparable data points:
    # Europe registrations + China retail + RoW manual entries.
    # We do NOT add wholesale here — it's Shanghai production and would
    # double-count exports that already show up in European registrations.
    total_tracked = europe_total + china_retail_total + row_total

    st.metric(
        f"{quarter_label} total tracked deliveries",
        f"{total_tracked:,}",
        help="Bottom-up sum: Europe registrations (TMC) + China retail (CPCA) "
             "+ Rest of World (manual entry). Does NOT include China wholesale "
             "(that includes Shanghai exports already counted in Europe).",
    )

    # Smaller breakdown row
    b1, b2, b3 = st.columns(3)
    b1.metric("Europe (TMC)", f"{europe_total:,}",
              f"{europe_countries} countries")
    b2.metric("China retail (CPCA)", f"{china_retail_total:,}",
              f"{china_retail_months} of 3 months")
    if row_countries:
        b3.metric("Rest of World", f"{row_total:,}",
                  f"{row_countries} of 8 countries (manual)")
    else:
        b3.metric("Rest of World", "0",
                  "manual entry available in sidebar")

    # ── Country × month matrix ───────────────────────────────────────────
    st.markdown("#### Country × month breakdown")

    # Build the quarter's month column labels
    month_cols = []
    for i in range(3):
        mo = (q_start.month + i - 1) % 12 + 1
        yr = q_start.year + ((q_start.month + i - 1) // 12)
        month_cols.append(date(yr, mo, 1).strftime("%b"))

    # Assemble matrix data: Europe rows + China (Retail) row + RoW placeholders
    matrix_rows = []
    if not monthly.empty:
        m = monthly.copy()
        m["month_label"] = m["period_start"].dt.strftime("%b")
        for (country, label), grp in m.groupby(["country", "month_label"]):
            matrix_rows.append({"country": country, "month_label": label,
                                "units": int(grp["units"].sum())})

    if not china_retail.empty:
        cr = china_retail.copy()
        cr["month_label"] = cr["period_start"].dt.strftime("%b")
        for (_, label), grp in cr.groupby(["country", "month_label"]):
            matrix_rows.append({"country": "China (Retail)",
                                "month_label": label,
                                "units": int(grp["units"].sum())})

    # RoW placeholders — visible coverage gaps for non-Europe/China markets
    for country in ROW_PLACEHOLDER_COUNTRIES:
        # Add a stub row for the first month so the country shows up
        matrix_rows.append({"country": country,
                            "month_label": month_cols[0], "units": 0})

    mdf = pd.DataFrame(matrix_rows)
    matrix = (mdf.pivot_table(index="country", columns="month_label",
                              values="units", aggfunc="sum", fill_value=0)
                .reindex(columns=month_cols, fill_value=0))
    matrix["Q total"] = matrix.sum(axis=1)
    matrix = matrix.sort_values("Q total", ascending=False)

    display = matrix.copy().astype(str)
    for col in matrix.columns:
        display[col] = matrix[col].apply(
            lambda x: f"{int(x):,}" if x else "—"
        )
    st.dataframe(display, width="stretch",
                 height=35 * (len(display) + 1) + 3)

    # ── Reference comparison (less prominent) ────────────────────────────
    ref_lines = []
    if prior_year_total:
        ref_lines.append(
            f"Q{cur_q} {cur_year - 1} reported delivery: **{prior_year_total:,}**"
        )
    if prev_q_total:
        ref_lines.append(
            f"Previous quarter (Q{prev_q} {prev_year}): **{prev_q_total:,}**"
        )
    if ref_lines:
        st.caption("Reference (global, Tesla IR) — " + " · ".join(ref_lines) +
                   ". Tracked total above is partial because we only cover "
                   "the markets with public data.")

    # ── Shanghai production (leading indicator, not in delivery total) ───
    if not china_wholesale.empty:
        st.markdown("---")
        st.markdown("#### Shanghai production (leading indicator)")
        st.caption(
            "CPCA wholesale = Giga Shanghai's monthly output. Includes "
            "domestic deliveries AND vehicles in transit to export markets. "
            "Leads delivery numbers by 1-2 months because exported vehicles "
            "show up in Europe's registration data later. Useful as a "
            "forward signal — **do NOT add to the tracked total above**."
        )
        cw_display = china_wholesale.copy().sort_values("period_start")
        cw_display["Month"] = cw_display["period_start"].dt.strftime("%b %Y")
        cw_display["Units"] = cw_display["units"].apply(lambda x: f"{int(x):,}")
        st.dataframe(cw_display[["Month", "Units", "notes"]]
                       .rename(columns={"notes": "Notes"}),
                     width="stretch", hide_index=True,
                     height=35 * (len(cw_display) + 1) + 3)

    # ── Historical Tesla IR context ──────────────────────────────────────
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
        st.dataframe(hist_display, width="stretch", hide_index=True,
                     height=35 * (len(hist_display) + 1) + 3)


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
        width="stretch", hide_index=True,
        height=35 * (len(latest) + 1) + 3,
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
    st.plotly_chart(fig, width="stretch")


def _tab_china(df: pd.DataFrame) -> None:
    st.subheader("China monthly (CPCA via CnEVPost)")
    china = df[(df["country"] == "China") &
               (df["period_type"] == "monthly") &
               (df["metric"].isin(["wholesale", "retail"]))]
    if china.empty:
        st.info(
            "No monthly China data yet. Click 'Refresh China monthly (CnEVPost)' "
            "in the sidebar."
        )
        return
    china = china.sort_values("period_start").copy()
    fig = px.line(
        china, x="period_start", y="units", color="metric", markers=True,
        title="Tesla China monthly: wholesale (incl. exports) vs. retail (domestic)",
    )
    fig.update_layout(
        height=480, yaxis_title="Units", xaxis_title="",
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")
    st.dataframe(
        china[["period_start", "metric", "units", "notes", "source_url"]]
            .sort_values("period_start", ascending=False),
        width="stretch", hide_index=True,
        height=35 * (len(china) + 1) + 3,
    )
    st.caption("**Wholesale** is CPCA's total figure for Giga Shanghai — "
               "includes both domestic deliveries and exports to Europe and "
               "elsewhere. **Retail** is CPCA domestic only. The gap between "
               "the two is roughly equal to Tesla's monthly Shanghai exports.")


def _tab_all(df: pd.DataFrame) -> None:
    st.subheader("All ingested data")
    st.dataframe(df, width="stretch", hide_index=True)
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
- **CnEVPost** (auto-scraped): Tesla China monthly wholesale (CPCA total,
  includes Giga Shanghai exports) and retail breakdown (CPCA domestic only).
  Published 1-3 days after month-end (wholesale) and ~10 days after (retail).
  <https://cnevpost.com/tesla/>
- **Tesla IR** (in-code seed): quarterly global delivery numbers, used as
  the ground-truth reference row. Update `SEED_DATA` once per quarter
  after the press release. <https://ir.tesla.com>

### Metrics — these are not interchangeable

- `registration`: vehicle entered in a national database. Lags delivery
  by days/weeks. (European national agencies, via TMC sheet.)
- `wholesale`: CPCA's total Giga Shanghai figure — domestic retail PLUS
  exports to Europe and elsewhere. Adding this to European registrations
  would double-count the exports. Use it as a Shanghai-production signal,
  not a regional addition.
- `retail`: CPCA China domestic-only. This IS additive with European
  registrations — they're disjoint geographies.
- `delivery`: Tesla's reported deliveries (quarterly press release;
  global ground truth).

### Limitations

- The TMC sheet typically lags individual X aggregators (Roland Pircher
  et al.) by a day or two because the community validates each entry
  before approving it. For a real-time read, the X feeds are faster;
  this dashboard prioritizes validated data over speed.
- CnEVPost stopped publishing weekly Tesla insurance registrations in
  October 2025; the dashboard switched to monthly CPCA data published
  in their Tesla category. If they change URL patterns again the scraper
  fails closed (no rows inserted) — fix the regexes in
  `_extract_china_wholesale` / `_extract_china_retail`.
- For the final month of any quarter, China retail data arrives AFTER
  Tesla's own quarterly announcement (Tesla announces ~3 days after
  quarter-end; CPCA retail follows ~10 days after). That means the
  bottom-up tracker is most useful through month 2 of each quarter,
  with Tesla's own number being the final word for month 3.
- SQLite at `data/tesla_sales.db` is local-only.
""")


def main() -> None:
    st.set_page_config(
        page_title="Tesla Quarterly Delivery Tracker",
        layout="wide",
        page_icon="🚗",
    )
    st.title("🚗 Tesla Quarterly Delivery Tracker")
    st.caption(
        "A bottom-up estimate of Tesla's quarterly global deliveries, "
        "aggregated from European national agencies (via the TMC community "
        "sheet), China's CPCA (via CnEVPost), Tesla's own IR figures, and "
        "manual entries for other markets."
    )

    init_db()
    seed_baseline()

    with st.sidebar:
        _sidebar_refresh()

    df = load_combined_df()
    tab_q, tab_latest, tab_monthly, tab_china, tab_all, tab_about = st.tabs(
        ["🎯 Quarter tracker", "📊 Latest", "📈 Monthly trends",
         "🇨🇳 China monthly", "🗂 All data", "ℹ️ About"]
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
