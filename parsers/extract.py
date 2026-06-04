"""
Parsers for Tesla regional sales posts, primarily the consistent format used by
@piloly, with support for summary rollups from @Tslachan / @tslaming.

The format is highly structured, which makes reliable extraction possible with
regex + light post-processing. For follow-up image charts, see vision notes below.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List
import dateutil.parser as dateparser


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


def _parse_percent(text: str) -> Optional[float]:
    """Extract first percentage like +322% or 28.8% or 149 basis points."""
    if not text:
        return None
    # Handle "149 basis points" -> 1.49
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
    """
    Handles:
    - "Germany reported 5,111 Tesla sales ... in May."
    - "In May, Tesla's Giga Shanghai wholesale sales ... were 85,982 ..."
    - "Hong Kong reported 1,392 ... in May."
    - Summary lines like "🇩🇪 Germany : +323% (Sales in May: 5,111)"
    """
    # Priority: "Country reported NNN ... in May." (most detailed @piloly posts)
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

    # China Giga Shanghai - "In May, ... Giga Shanghai ... were 85982"
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

    # Summary / rollup style: "🇬🇧 UK : +18% (Sales in May: 2,812)"
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
    """Look for '95% Model Y and 4% Model 3' or similar."""
    my = re.search(r"(\d+(?:\.\d+)?)\s*%\s*Model\s*Y", text, re.I)
    m3 = re.search(r"(\d+(?:\.\d+)?)\s*%\s*Model\s*3", text, re.I)
    return (float(my.group(1)) if my else None,
            float(m3.group(1)) if m3 else None)


def _extract_bullets(text: str) -> Dict[str, Any]:
    """Pull key derived stats from the bullet list."""
    out = {}
    # Market share line is often in the first paragraph
    ms = re.search(r"(\d+(?:\.\d+)?)\s*%\s*market share", text, re.I)
    if ms:
        out["market_share_pct"] = float(ms.group(1))

    bev = re.search(r"BEV penetration is\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if bev:
        out["bev_penetration_pct"] = float(bev.group(1))

    tesla_bev = re.search(r"Tesla has\s*(\d+(?:\.\d+)?)\s*%\s*of this segment", text, re.I)
    if tesla_bev:
        out["tesla_of_bev_pct"] = float(tesla_bev.group(1))

    # Growth bullets
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

    # Model mix
    my, m3 = _extract_model_mix(text)
    out["model_y_pct"] = my
    out["model_3_pct"] = m3

    # Collect "records" phrases
    records = re.findall(r"(best .*? ever|second best .*? ever|highest .*? since .*?Q\d|record)", text, re.I)
    out["records"] = list(dict.fromkeys(records))  # dedup preserve order

    return out


def parse_piloly_post(text: str, post_url: str = None, author: str = "piloly") -> Optional[TeslaSalesRecord]:
    """
    Main entry point for detailed per-country posts.
    Returns a TeslaSalesRecord or None if it doesn't look like a sales report.
    """
    if "reported" not in text.lower() and "Giga Shanghai" not in text and "Sales in " not in text:
        return None

    country, year, month, period = _extract_country_and_period(text)
    sales = _parse_sales_from_text(text)
    if not sales:
        # fallback sales extraction
        sales_match = re.search(r"(\d[\d,]+)\s*(?:Tesla sales|vehicles|units|Model 3 and Model Y)", text, re.I)
        sales = _parse_int(sales_match.group(1)) if sales_match else None

    if not country or sales is None:
        return None

    if not year or not month:
        # default to current context if missing
        year, month = 2026, 5  # placeholder, caller should fix

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
    # Try several patterns
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


def parse_rollup_text(text: str, post_url: str = None) -> List[TeslaSalesRecord]:
    """
    For posts that are summary tables, e.g. @Tslachan style:
    "🇬🇧 UK : +18% (Sales in May: 2,812)"
    Returns list of records (one per country mentioned).
    """
    records = []
    # More robust per-line match. Look for flag + Country : +XX% (Sales in Month: NNN)
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
            source_post_author="Tslachan/tslaming",
            ingested_at=datetime.utcnow().isoformat(),
            raw_text=text,
        )
        records.append(rec)
    return records


# Example usage / tests
if __name__ == "__main__":
    sample = """Germany reported 5,111 Tesla sales and 2.1% market share in May. BEV penetration is 25% and Tesla has 8.5% of this segment. 🇩🇪

• Market share is 31 basis points or 17% above the 3-month trailing average of 1.8%
• +322% vs. May last year and +125% compared to February the second month of the previous quarter
• Second best May ever
• Highest quarter after two months since 24Q1 (9 quarters)
• Last three months +212.2% vs. December - February
• Year-to-date +200% over same period last year
• Year-to-date is 109% or 13.1/12 of last year's total"""

    rec = parse_piloly_post(sample, post_url="https://x.com/piloly/status/2062117892619952546")
    print(rec.to_dict() if rec else "No parse")

    rollup = """🇬🇧 UK : +18% (Sales in May: 2,812) 
🇳🇴 Norway : +27% (Sales in May: 3,295)
🇩🇪 Germany : +323% (Sales in May: 5,111)"""
    print([r.to_dict() for r in parse_rollup_text(rollup)])
