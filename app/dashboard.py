"""
Tesla Regional Sales Dashboard (Streamlit)
Run with: streamlit run app/dashboard.py
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
import sys

# Make sure we can import local modules
sys.path.append(str(Path(__file__).parent.parent))

from app.storage import init_db, load_df, insert_record, get_latest_by_country, seed_examples
from parsers.extract import parse_piloly_post, parse_rollup_text, TeslaSalesRecord
from parsers.fetch_x import fetch_post_from_url, extract_post_id

st.set_page_config(page_title="Tesla Regional Sales", layout="wide", page_icon="🚗")

st.title("🚗 Tesla Regional Sales Dashboard")
st.caption("Aggregate the excellent per-country data posted by @piloly, @Tslachan, @tslaming et al. into something you can actually query and trend.")

# Sidebar controls
with st.sidebar:
    st.header("Controls")
    if st.button("🔄 Seed with recent examples (May/June 2026)"):
        seed_examples()
        st.success("Seeded sample data from real posts.")
        st.rerun()

    st.markdown("---")
    st.markdown("**Ingest a new post** — just paste the X URL (recommended)")
    st.caption("This is now the primary way to add data. The tool is essentially a counter: when you ingest a post for a country+month that already exists, the newest numbers win and replace the old ones.")

    # URL-first flow (recommended)
    post_url = st.text_input(
        "X Post URL",
        placeholder="https://x.com/piloly/status/2061793233076691388",
        help="Paste the full link from X. Click 'Fetch from URL' below — it will pull the text using a public endpoint and fill in the author."
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 Fetch from URL", disabled=not post_url.strip()):
            result = fetch_post_from_url(post_url.strip())
            if "error" in result:
                st.error(result["error"])
            else:
                st.session_state["fetched_text"] = result["text"]
                st.session_state["fetched_author"] = result.get("author", "piloly")
                st.success(f"Fetched post by @{result.get('author', '?')}. Text loaded below — you can edit it if needed.")
                st.rerun()

    # Text area (populated by fetch or manual paste as fallback)
    default_text = st.session_state.get("fetched_text", "")
    post_text = st.text_area(
        "Post text (auto-filled from URL above, or paste manually)",
        value=default_text,
        height=160,
        placeholder="The post text will appear here after you click Fetch, or you can paste the full text manually."
    )

    # Author — auto-filled from fetch, still overridable
    default_author = st.session_state.get("fetched_author", "piloly")
    author = st.text_input(
        "Author / handle (auto-filled)",
        value=default_author,
        help="Recorded for provenance (shown in the Latest table). Deduplication is now purely on country+year+month — the newest paste always wins, regardless of who posted it. This makes the tool behave like a straightforward counter."
    )

    if st.button("📥 Parse & Save"):
        if not post_text.strip():
            st.error("Need some post text (either fetch from URL or paste it).")
        else:
            recs = []
            main = parse_piloly_post(post_text, post_url or None, author)
            if main:
                recs.append(main)
            rollups = parse_rollup_text(post_text, post_url or None)
            recs.extend(rollups)

            if not recs:
                st.warning("Couldn't parse any sales records. The format might be a weekly Europe summary or different. Try the detailed per-country posts first.")
            else:
                inserted = 0
                for r in recs:
                    if insert_record(r.to_dict()):
                        inserted += 1
                st.success(f"Inserted/updated {inserted} record(s). The tables below should update after rerun.")
                # Clear fetched state so next ingest starts fresh
                st.session_state.pop("fetched_text", None)
                st.session_state.pop("fetched_author", None)
                st.rerun()

    st.markdown("---")
    st.markdown("Data lives in `data/tesla_sales.db` (SQLite). Easy to query or back up.")
    st.markdown("See README.md and docs/sources.md for how to add more countries and sources.")

# Load data
init_db()
df = load_df()

if df.empty:
    st.info("No data yet. Click 'Seed with recent examples' in the sidebar, or use the URL fetch in the left sidebar to add real posts.")
    st.stop()

# Tabs
tab_latest, tab_trends, tab_all, tab_sources = st.tabs(["📊 Latest by Country", "📈 Trends & Charts", "All Data", "Sources & Help"])

with tab_latest:
    st.subheader("Most recent month per country")
    latest = get_latest_by_country()
    cols = ["country", "period_label", "sales", "yoy_pct", "market_share_pct", "bev_penetration_pct", "tesla_of_bev_pct", "source_post_author", "source_post_url"]
    display = latest[[c for c in cols if c in latest.columns]].copy()
    st.dataframe(display, width="stretch", hide_index=True)

    # Quick totals
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

        # YoY growth where available
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
    st.markdown("📖 **[docs/sources.md — Official sources + how the data is gathered](docs/sources.md)**  \n_(Open this file in your editor or terminal with `open docs/sources.md` / `code docs/sources.md`)_")
    st.markdown("""
    **Primary X accounts worth following / monitoring**:
    - @piloly — detailed per-country with excellent charts and context (the gold standard for this dashboard).
    - @Tslachan — big rollups, China, South Korea, Europe/Asia updates.
    - @tslaming — Japan, Norway daily/weekly, UK, timely "good news" posts.
    - @SawyerMerritt — high-signal major market records + links to articles (thedriven.io etc.).

    When your friend posts new links in Discord, paste the main post text (and the follow-up image description if you want) into the ingest box on the left. The parser is tuned to their very consistent writing style.
    """)

st.caption("Prototype built to stop the manual copy-paste cycle. Extend the parser, add direct scrapers for CPCA / OFV / thedriven.io, or wire up a Discord bot next.")
