"""
Simple local SQLite storage for Tesla sales records.
Uses pandas for easy querying + export.
"""
import sqlite3
import pandas as pd
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "tesla_sales.db"
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
        records TEXT,                 -- JSON-ish comma list or pipe
        source_post_url TEXT,
        source_post_author TEXT,
        source_post_id TEXT,
        ingested_at TEXT,
        raw_text TEXT,
        UNIQUE(country, year, month)  -- one row per country+month. Newer ingest wins (see insert_record)
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_country_month ON monthly_sales(country, year, month)")
    conn.commit()
    conn.close()


def insert_record(rec: Dict[str, Any]) -> bool:
    """
    Insert (or replace) one parsed record.

    Dedup key is now (country, year, month) only — the most recently ingested
    data for that bucket wins. This makes the tool behave like a simple counter:
    when someone posts an update for Norway in May, it just updates the Norway-May number.
    """
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
    # Keep the most recent per country (by year-month)
    df = df.sort_values(["country", "year", "month"], ascending=[True, False, False])
    return df.groupby("country", as_index=False).first()


def seed_examples():
    """Seed a few real examples from the May/June 2026 wave so the dashboard is immediately useful."""
    from parsers.extract import parse_piloly_post, parse_rollup_text

    examples = [
        # Germany detailed
        ("""Germany reported 5,111 Tesla sales and 2.1% market share in May. BEV penetration is 25% and Tesla has 8.5% of this segment. 🇩🇪

• Market share is 31 basis points or 17% above the 3-month trailing average of 1.8%
• +322% vs. May last year and +125% compared to February the second month of the previous quarter
• Second best May ever
• Highest quarter after two months since 24Q1 (9 quarters)
• Last three months +212.2% vs. December - February
• Year-to-date +200% over same period last year
• Year-to-date is 109% or 13.1/12 of last year's total""",
         "https://x.com/piloly/status/2062117892619952546", "piloly"),

        # China Giga
        ("""In May, Tesla's Giga Shanghai wholesale sales (local in China and exports) were 85,982 Model 3 and Model Y. 🇨🇳

This represents a year-on-year increase of 39.4% and a month-on-month increase of 8.2%. Compared to last year, year-to-date sales are up by 29.4%.

Highest sales after 2 months into the quarter since 22Q4 (14 quarters).""",
         "https://x.com/piloly/status/2061793233076691388", "piloly"),

        # Australia
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

        # Rollup example (will create multiple rows)
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
        # Also try rollup on the same text (harmless if none)
        for r in parse_rollup_text(text, url):
            if insert_record(r.to_dict()):
                count += 1
    print(f"Seeded/updated {count} records (including rollups).")


if __name__ == "__main__":
    init_db()
    seed_examples()
    df = load_df()
    print("\nCurrent DB rows:", len(df))
    print(df[["country", "period_label", "sales", "yoy_pct"]].head(10).to_string())
