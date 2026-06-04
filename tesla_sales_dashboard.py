"""
Tesla Regional Sales Dashboard (Single-File Consolidated Version)
================================================================

Mimics the Signal Lab workflow:
- This file (tesla_sales_dashboard.py) on the Desktop is the one uploaded to GitHub.
- tesla_sales_dashboard.py_bak is the previous version (for easy rollback).
- All extras, old versions, split modules, experiments live in Desktop/tesla-sales-extras/

This is a self-contained single-file Streamlit app (like equity_trends.py for Signal Lab).
All parser, storage, fetch, and UI logic is inlined here for simple GitHub uploads and Streamlit Cloud deploys.

Run with:
    source .venv/bin/activate
    streamlit run tesla_sales_dashboard.py

Or on Mac, double-click a TeslaSalesDashboard.command (copy one from tesla-sales-extras/ if needed).

See the tesla-sales-extras/ folder for the split-module versions, full project snapshot, docs, requirements, old UIs, etc.

Current UI: Simple main-page "Paste X Post URL" + one "🚀 Fetch & Ingest" button.
No sidebar for ingest, no manual text/author fields (clutter removed per user request).
Auto-seeds demo data on first load if empty.

Live public version: https://tesla-sales-dashboard.streamlit.app
"""

from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import dateutil.parser as dateparser
import httpx


# ----------------------------- TeslaSalesRecord -----------------------------
@dataclass
class TeslaSalesRecord:
    country: str
    year: int
    month: int
    period_label: str
    sales: int
    market_share_pct: Optional[float] = None
    bev_penetration_pct: Optional[float] = None
    tesla_of_bev_pct: Optional[float] = None
    yoy_pct: Optional[float] = None
    vs_prior_q2m_pct: Optional[float] = None   # vs second month of previous quarter
    model_y_pct: Optional[float] = None
    model_3_pct: Optional[float] = None
    ytd_vs_last_ytd_pct: Optional[float] = None
    ytd_fraction_of_prior_year: Optional[float] = None
    notes: str = ""
    records: List[str] = None
    source_post_url: Optional[str] = None
    source_post_author: Optional[str] = None
    source_post_id: Optional[str] = None
    ingested_at: str = None
    raw_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("records") is None:
            d["records"] = []
        return d


# ----------------------------- Extract / Parse logic (from parsers/extract.py) -----------------------------
def _parse_percent(text: str) -> Optional[float]:
    """Extract first percentage like +322% or 28.8% or 149 basis points."""
    if not text:
        return None
    bp = re.search(r"(\d+(?:\.\d+)?)\s*basis points", text, re.I)
    if bp:
        return round(float(bp.group(1)) / 100, 2)
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", text)
    if m:
        return float(m.group(1))
    return None


def _parse_int(text: str) -> Optional[int]:
    m = re.search(r"([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _extract_country_and_period(text: str) -> tuple[Optional[str], Optional[int], Optional[int], Optional[str]]:
    m = re.search(
        r"([A-Z][A-Za-z\s]+?)\s+reported\s+([\d,]+)\s+Tesla\s+sales.*?in\s+(January|February|March|April|May|June|July|August|September|October|November|December)",
        text, re.I
    )
    if m:
        country = m.group(1).strip()
        sales = _parse_int(m.group(2))
        month_name = m.group(3).capitalize()
        try:
            dt = dateparser.parse(f"1 {month_name} 2026")
            return country, dt.year, dt.month, f"{month_name} {dt.year}"
        except Exception:
            pass

    m = re.search(
        r"(?:In|For)\s+(January|February|March|April|May|June|July|August|September|October|November|December).*?Giga Shanghai.*?(\d[\d,]+)",
        text, re.I
    )
    if m:
        month_name = m.group(1).capitalize()
        sales = _parse_int(m.group(2))
        try:
            dt = dateparser.parse(f"1 {month_name} 2026")
            return "China (Giga Shanghai wholesale)", dt.year, dt.month, f"{month_name} {dt.year}"
        except Exception:
            pass

    m = re.search(
        r"[🇨🇳🇹🇷🇳🇴🇳🇱🇸🇪🇧🇪🇪🇸🇩🇰🇵🇹🇫🇷🇮🇹🇬🇧🇦🇺🇩🇪🇹🇼🇭🇰🇮🇸🇨🇿🇷🇴🇮🇪🇨🇴🇰🇷🇯🇵]\s*([A-Za-z][A-Za-z\s]+?)\s*:\s*[+-]?\d+%\s*\(Sales in (January|February|March|April|May|June|July|August|September|October|November|December):\s*([\d,]+)\)",
        text
    )
    if m and m.group(1):
        country = m.group(1).strip()
        month_name = m.group(2)
        sales = _parse_int(m.group(3))
        try:
            dt = dateparser.parse(f"1 {month_name} 2026")
            return country, dt.year, dt.month, f"{month_name} 2026"
        except Exception:
            pass

    return None, None, None, None


def _extract_model_mix(text: str) -> tuple[Optional[float], Optional[float]]:
    my = re.search(r"(\d+(?:\.\d+)?)\s*%\s*Model\s*Y", text, re.I)
    m3 = re.search(r"(\d+(?:\.\d+)?)\s*%\s*Model\s*3", text, re.I)
    return (float(my.group(1)) if my else None,
            float(m3.group(1)) if m3 else None)


def _extract_bullets(text: str) -> Dict[str, Any]:
    out = {}
    ms = re.search(r"(\d+(?:\.\d+)?)\s*%\s*market share", text, re.I)
    if ms:
        out["market_share_pct"] = float(ms.group(1))

    bev = re.search(r"BEV penetration is\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if bev:
        out["bev_penetration_pct"] = float(bev.group(1))

    tesla_bev = re.search(r"Tesla has\s*(\d+(?:\.\d+)?)\s*%\s*of this segment", text, re.I)
    if tesla_bev:
        out["tesla_of_bev_pct"] = float(tesla_bev.group(1))

    yoy = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%\s*vs\.\s*(?:May|same month|last year)", text, re.I)
    if yoy:
        out["yoy_pct"] = float(yoy.group(1))

    q2 = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%\s*(?:compared to|vs\.)\s*(?:February|the second month)", text, re.I)
    if q2:
        out["vs_prior_q2m_pct"] = float(q2.group(1))

    ytd = re.search(r"Year-to-date\s*([+-]?\d+(?:\.\d+)?)\s*%\s*over same period last year", text, re.I)
    if ytd:
        out["ytd_vs_last_ytd_pct"] = float(ytd.group(1))

    frac = re.search(r"Year-to-date is\s*(\d+(?:\.\d+)?)\s*%\s*or\s*([\d.]+)/12", text, re.I)
    if frac:
        out["ytd_fraction_of_prior_year"] = float(frac.group(1))

    my, m3 = _extract_model_mix(text)
    out["model_y_pct"] = my
    out["model_3_pct"] = m3

    records = re.findall(r"(best .*? ever|second best .*? ever|highest .*? since .*?Q\d|record)", text, re.I)
    out["records"] = list(dict.fromkeys(records))
    return out


def parse_piloly_post(text: str, post_url: str = None, author: str = "piloly") -> Optional[TeslaSalesRecord]:
    if "reported" not in text.lower() and "Giga Shanghai" not in text and "Sales in " not in text:
        return None

    country, year, month, period = _extract_country_and_period(text)
    sales = _parse_sales_from_text(text)
    if not sales:
        sales_match = re.search(r"(\d[\d,]+)\s*(?:Tesla sales|vehicles|units|Model 3 and Model Y)", text, re.I)
        sales = _parse_int(sales_match.group(1)) if sales_match else None

    if not country or sales is None:
        return None

    if not year or not month:
        year, month = 2026, 5

    bullets = _extract_bullets(text)

    rec = TeslaSalesRecord(
        country=country,
        year=year,
        month=month,
        period_label=period or f"{month:02d}/{year}",
        sales=sales,
        market_share_pct=bullets.get("market_share_pct"),
        bev_penetration_pct=bullets.get("bev_penetration_pct"),
        tesla_of_bev_pct=bullets.get("tesla_of_bev_pct"),
        yoy_pct=bullets.get("yoy_pct"),
        vs_prior_q2m_pct=bullets.get("vs_prior_q2m_pct"),
        model_y_pct=bullets.get("model_y_pct"),
        model_3_pct=bullets.get("model_3_pct"),
        ytd_vs_last_ytd_pct=bullets.get("ytd_vs_last_ytd_pct"),
        ytd_fraction_of_prior_year=bullets.get("ytd_fraction_of_prior_year"),
        notes=text[:500] + "..." if len(text) > 500 else text,
        records=bullets.get("records", []),
        source_post_url=post_url,
        source_post_author=author,
        source_post_id=post_url.split("/")[-1] if post_url else None,
        ingested_at=datetime.utcnow().isoformat(),
        raw_text=text,
    )
    return rec


def _parse_sales_from_text(text: str) -> Optional[int]:
    patterns = [
        r"reported\s+([\d,]+)\s+Tesla",
        r"(\d[\d,]+)\s*(?:Tesla sales|vehicles|units|Model 3 and Model Y)",
        r"Sales in [A-Z][a-z]+:\s*([\d,]+)",
        r"(\d[\d,]+)\s*deliveries",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return _parse_int(m.group(1))
    return None


def parse_rollup_text(text: str, post_url: str = None, author: str = "Tslachan/tslaming") -> List[TeslaSalesRecord]:
    records = []
    pattern = r"[🇨🇳🇹🇷🇳🇴🇳🇱🇸🇪🇧🇪🇪🇸🇩🇰🇵🇹🇫🇷🇮🇹🇬🇧🇦🇺🇩🇪🇹🇼🇭🇰🇮🇸🇨🇿🇷🇴🇮🇪🇨🇴🇰🇷🇯🇵]\s*([A-Za-z][A-Za-z\s]+?)\s*:\s*[+-]?(\d+(?:\.\d+)?)%\s*\(Sales in (January|February|March|April|May|June|July|August|September|October|November|December):\s*([\d,]+)\)"
    for m in re.finditer(pattern, text):
        country = m.group(1).strip()
        try:
            yoy = float(m.group(2))
        except Exception:
            yoy = None
        month_name = m.group(3)
        sales = _parse_int(m.group(4))
        try:
            dt = dateparser.parse(f"1 {month_name} 2026")
            year, month = dt.year, dt.month
        except Exception:
            year, month = 2026, 5

        if sales is None:
            continue
        rec = TeslaSalesRecord(
            country=country,
            year=year,
            month=month,
            period_label=f"{month_name} {year}",
            sales=sales,
            yoy_pct=yoy,
            source_post_url=post_url,
            source_post_author=author,
            ingested_at=datetime.utcnow().isoformat(),
            raw_text=text,
        )
        records.append(rec)
    return records


# ----------------------------- Fetch X logic (from parsers/fetch_x.py) -----------------------------
def extract_post_id(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


def fetch_post_from_url(url: str, timeout: float = 10.0) -> Dict[str, str]:
    post_id = extract_post_id(url)
    if not post_id:
        return {"error": "Could not extract post ID from URL. Use a link like https://x.com/piloly/status/1234567890"}

    syndication_url = f"https://cdn.syndication.twimg.com/tweet?id={post_id}&lang=en"

    try:
        resp = httpx.get(syndication_url, timeout=timeout, follow_redirects=True)
        if resp.status_code == 404:
            return {"error": "Post not found via public endpoint (it may be very new, deleted, protected, or the syndication cache hasn't updated yet). Paste the text manually instead — it's the most reliable method."}
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": f"Network error fetching post: {e}. You can still paste the full text from the post manually."}

    text = (data.get("text") or "").strip()
    user = data.get("user", {}) or {}
    author = (user.get("screen_name") or user.get("name") or "").strip()

    if not text:
        return {"error": "Could not extract text from the post. Paste the text contents manually."}

    return {
        "text": text,
        "author": author,
        "post_id": post_id,
    }


# ----------------------------- Storage (from app/storage.py, adjusted for single-file) -----------------------------
DB_PATH = Path(__file__).parent / "data" / "tesla_sales.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS monthly_sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT NOT NULL,
        year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        period_label TEXT,
        sales INTEGER NOT NULL,
        market_share_pct REAL,
        bev_penetration_pct REAL,
        tesla_of_bev_pct REAL,
        yoy_pct REAL,
        vs_prior_q2m_pct REAL,
        model_y_pct REAL,
        model_3_pct REAL,
        ytd_vs_last_ytd_pct REAL,
        ytd_fraction_of_prior_year REAL,
        notes TEXT,
        records TEXT,
        source_post_url TEXT,
        source_post_author TEXT,
        source_post_id TEXT,
        ingested_at TEXT,
        raw_text TEXT,
        UNIQUE(country, year, month)
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_country_month ON monthly_sales(country, year, month)")
    conn.commit()
    conn.close()


def insert_record(rec: Dict[str, Any]) -> bool:
    init_db()
    conn = get_conn()
    c = conn.cursor()
    records_str = "|".join(rec.get("records", [])) if rec.get("records") else ""
    try:
        c.execute("""
            INSERT OR REPLACE INTO monthly_sales
            (country, year, month, period_label, sales, market_share_pct, bev_penetration_pct,
             tesla_of_bev_pct, yoy_pct, vs_prior_q2m_pct, model_y_pct, model_3_pct,
             ytd_vs_last_ytd_pct, ytd_fraction_of_prior_year, notes, records,
             source_post_url, source_post_author, source_post_id, ingested_at, raw_text)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rec["country"], rec["year"], rec["month"], rec.get("period_label"),
            rec["sales"], rec.get("market_share_pct"), rec.get("bev_penetration_pct"),
            rec.get("tesla_of_bev_pct"), rec.get("yoy_pct"), rec.get("vs_prior_q2m_pct"),
            rec.get("model_y_pct"), rec.get("model_3_pct"),
            rec.get("ytd_vs_last_ytd_pct"), rec.get("ytd_fraction_of_prior_year"),
            rec.get("notes", ""), records_str,
            rec.get("source_post_url"), rec.get("source_post_author"),
            rec.get("source_post_id"), rec.get("ingested_at") or datetime.utcnow().isoformat(),
            rec.get("raw_text", "")
        ))
        conn.commit()
        return True
    except Exception as e:
        print("Insert error:", e)
        return False
    finally:
        conn.close()


def load_df() -> pd.DataFrame:
    init_db()
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM monthly_sales ORDER BY year DESC, month DESC, country", conn)
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["year"].astype(str) + "-" + df["month"].astype(str) + "-01")
    return df


def get_latest_by_country() -> pd.DataFrame:
    df = load_df()
    if df.empty:
        return df
    df = df.sort_values(["country", "year", "month"], ascending=[True, False, False])
    return df.groupby("country", as_index=False).first()


def seed_examples():
    """Seed a few real examples from the May/June 2026 wave so the dashboard is immediately useful."""
    examples = [
        ("""Germany reported 5,111 Tesla sales and 2.1% market share in May. BEV penetration is 25% and Tesla has 8.5% of this segment. 🇩🇪

• Market share is 31 basis points or 17% above the 3-month trailing average of 1.8%
• +322% vs. May last year and +125% compared to February the second month of the previous quarter
• Second best May ever
• Highest quarter after two months since 24Q1 (9 quarters)
• Last three months +212.2% vs. December - February
• Year-to-date +200% over same period last year
• Year-to-date is 109% or 13.1/12 of last year's total""",
         "https://x.com/piloly/status/2062117892619952546", "piloly"),

        ("""In May, Tesla's Giga Shanghai wholesale sales (local in China and exports) were 85,982 Model 3 and Model Y. 🇨🇳

This represents a year-on-year increase of 39.4% and a month-on-month increase of 8.2%. Compared to last year, year-to-date sales are up by 29.4%.

Highest sales after 2 months into the quarter since 22Q4 (14 quarters).""",
         "https://x.com/piloly/status/2061793233076691388", "piloly"),

        ("""Australia reported 6,433 Tesla sales and 6% market share in May. BEV penetration reaches new record of 19.9% and Tesla has 30.2% of this segment. 🇦🇺

• Market share is 336 basis points or 126% above the 3-month trailing average of 2.7%
• Highest market share ever
• Tesla 6th best-selling brand
• Model Y best-selling car
• 87% Model Y and 13% Model 3
• +65% vs. May last year
• Best May ever
• Year-to-date +56% over same period last year""",
         "https://x.com/piloly/status/2062105828568555573", "piloly"),

        ("""$TSLA (Update #3)
More Tesla vehicle sales in European and Asian countries were reported in May. Data from UK, Australia, Germany, Taiwan and Turkey were added.

🇬🇧 UK : +18% (Sales in May: 2,812) 
🇳🇴 Norway : +27% (Sales in May: 3,295)
🇳🇱 Netherlands : +31% (Sales in May: 1,387)
🇦🇺 Australia : +65% (Sales in May: 6,433)
🇩🇪 Germany : +323% (Sales in May: 5,111)
🇫🇷 France: +655% (Sales in May: 5,446)
🇹🇼 Taiwan : +804% (Sales in May: 1,781)

🇮🇹 Italy : -24% (Sales in May: 654)
🇹🇷 Turkey : -76% (Sales in May: 370)""",
         "https://x.com/Tslachan/status/2062152188458393809", "Tslachan"),
    ]

    count = 0
    for text, url, author in examples:
        rec = parse_piloly_post(text, url, author)
        if rec:
            if insert_record(rec.to_dict()):
                count += 1
        for r in parse_rollup_text(text, url, author):
            if insert_record(r.to_dict()):
                count += 1
    print(f"Seeded/updated {count} records (including rollups).")


# ----------------------------- Main UI (simplified, from app/dashboard.py) -----------------------------
def main():
    st.set_page_config(page_title="Tesla Regional Sales", layout="wide", page_icon="🚗")
    st.title("🚗 Tesla Regional Sales Dashboard")
    st.caption("Aggregate the excellent per-country data posted by @piloly, @Tslachan, @tslaming et al. into something you can actually query and trend.")

    # === Simple main-page ingest (URL only) ===
    st.markdown("### Ingest latest from X")
    st.markdown("Paste a public X post URL below. The tool fetches the text, parses the sales numbers, and updates (or adds) the relevant country/region. Newest data for a country+month always wins.")

    post_url = st.text_input(
        "Paste X Post URL",
        placeholder="https://x.com/piloly/status/2061793233076691388",
        key="ingest_url"
    )

    if st.button("🚀 Fetch & Ingest", type="primary", disabled=not post_url.strip(), key="ingest_btn"):
        url = post_url.strip()
        with st.spinner("Fetching post from X and parsing..."):
            result = fetch_post_from_url(url)
            if "error" in result:
                st.error(result["error"])
            else:
                text = result["text"]
                author = result.get("author", "piloly")

                recs = []
                main_rec = parse_piloly_post(text, url, author)
                if main_rec:
                    recs.append(main_rec)
                rollups = parse_rollup_text(text, url, author)
                recs.extend(rollups)

                if not recs:
                    st.warning("Fetched the post but couldn't extract any sales records. The format might be new or different. Please notify the dashboard admin (share the X post URL in Discord) so support can be added.")
                else:
                    inserted = 0
                    countries_updated = []
                    for r in recs:
                        if insert_record(r.to_dict()):
                            inserted += 1
                            countries_updated.append(r.country)

                    unique_countries = list(dict.fromkeys(countries_updated))
                    st.success(
                        f"✅ Ingested/updated {inserted} record(s) for: **{', '.join(unique_countries)}** "
                        f"(source: @{author})."
                    )
                    st.session_state["ingest_url"] = ""
                    st.rerun()

    # Load data
    init_db()
    df = load_df()

    if df.empty:
        seed_examples()
        df = load_df()
        st.info("Seeded with demo data. Paste a real X post URL above to add fresh numbers.")

    tab_latest, tab_trends, tab_all, tab_sources = st.tabs(["📊 Latest by Country", "📈 Trends & Charts", "All Data", "Sources & Help"])

    with tab_latest:
        st.subheader("Most recent month per country")
        latest = get_latest_by_country()
        cols = ["country", "period_label", "sales", "yoy_pct", "market_share_pct", "bev_penetration_pct", "tesla_of_bev_pct", "source_post_author", "source_post_url"]
        display = latest[[c for c in cols if c in latest.columns]].copy()
        st.dataframe(display, width="stretch", hide_index=True)

        total_latest = latest["sales"].sum()
        st.metric("Sum of displayed latest months (partial coverage)", f"{total_latest:,}")

    with tab_trends:
        st.subheader("Sales over time (select countries)")
        countries = sorted(df["country"].unique().tolist())
        selected = st.multiselect("Countries", countries, default=countries[:6] if len(countries) > 6 else countries)

        if selected:
            sub = df[df["country"].isin(selected)].sort_values("date")
            fig = px.line(sub, x="date", y="sales", color="country", markers=True,
                          title="Tesla Sales by Country (monthly)")
            fig.update_layout(height=450)
            st.plotly_chart(fig, width="stretch")

            if "yoy_pct" in df.columns:
                sub2 = sub.dropna(subset=["yoy_pct"])
                if not sub2.empty:
                    fig2 = px.bar(sub2, x="date", y="yoy_pct", color="country", barmode="group",
                                  title="YoY % change (where reported)")
                    st.plotly_chart(fig2, width="stretch")

        st.markdown("**Notes**: China numbers are Giga Shanghai wholesale (includes exports). Europe coverage is often partial (fast-reporting countries). Always check the source links for full context and charts.")

    with tab_all:
        st.subheader("Full table (all ingested months)")
        st.dataframe(df[["country", "period_label", "sales", "yoy_pct", "market_share_pct", "source_post_url"]],
                     width="stretch", hide_index=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv, "tesla_regional_sales.csv", "text/csv")

    with tab_sources:
        st.markdown("See the full list of underlying sources and the X accounts that do the hard work:")
        st.markdown("📖 **[Supporting docs in tesla-sales-extras/docs_sources.md]**")
        st.markdown("""
        **Primary X accounts worth following / monitoring**:
        - @piloly — detailed per-country with excellent charts and context (the gold standard for this dashboard).
        - @Tslachan — big rollups, China, South Korea, Europe/Asia updates.
        - @tslaming — Japan, Norway daily/weekly, UK, timely "good news" posts.
        - @SawyerMerritt — high-signal major market records + links to articles (thedriven.io etc.).

        Paste X post URLs into the box at the top. This single-file version is optimized for easy GitHub uploads and live deploys.
        """)

    st.caption("Prototype built to stop the manual copy-paste cycle. Single-file version for Signal Lab-style Desktop + GitHub workflow. Extend the parser, add direct scrapers, or wire up a Discord bot next.")


if __name__ == "__main__":
    main()
