"""
Utilities to fetch the text content of a public X post from its URL.

Uses the public syndication endpoint (no API key required).
This is reliable for the main tweet text, which is what we need for these sales reports.
"""
import re
from typing import Optional, Dict

import httpx


def extract_post_id(url: str) -> Optional[str]:
    """Extract the numeric status ID from common X/Twitter URL formats."""
    if not url:
        return None
    # Handles https://x.com/user/status/1234567890 , https://twitter.com/... , with or without ?s=46 etc.
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


def fetch_post_from_url(url: str, timeout: float = 10.0) -> Dict[str, str]:
    """
    Best-effort fetch of the main tweet text from a public X post URL.

    Uses Twitter's public syndication CDN (no key needed). It works for most
    public posts but can occasionally 404 or return limited data.

    Returns dict with 'text', 'author', 'post_id' on success, or 'error'.
    """
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
