"""
Devpost adapter.
Uses Devpost's own internal API (devpost.com/api/hackathons) -- the same
endpoint that powers devpost.com itself. Public, no auth required, but
DOES require a real browser User-Agent + Referer header or it 403s.

CONFIRMED LIVE (2026-09): the list endpoint has NO description field.
Real challenge description text lives on each hackathon's own subdomain
page (e.g. revenuecat-shipaton-2026.devpost.com), inside
<section id="main" class="row text-content content-section">.
That subdomain page ALSO needs the same browser-like headers or it 403s.

So: fetch list -> for each hackathon, fetch its subdomain page -> pull
section#main text -> truncate. This means 1 extra HTTP call per hackathon
(same tradeoff as Zindi), so keep max_results reasonable for a POC.
"""
import hashlib
import re
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from text_clean import summarize, is_mostly_english

LIST_URL = "https://devpost.com/api/hackathons"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://devpost.com/hackathons",
}

# Devpost themes -> our app categories (approximate, based on theme names Devpost uses)
THEME_HINTS = {
    "software-dev": ["web", "mobile", "developer tools", "open ended"],
    "python": None,  # no dedicated python theme; treat like "all"
    "research": ["machine learning/ai", "health", "science", "climate"],
    "mba": ["fintech", "business", "social good"],
    "all": None,
}


def _make_id(hackathon_id) -> str:
    return hashlib.sha256(str(hackathon_id).encode("utf-8")).hexdigest()[:16]


def _fetch_challenge_text(url: str) -> str:
    import requests
    from bs4 import BeautifulSoup

    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        main_section = soup.find("section", id="main")
        if not main_section:
            return ""
        text = main_section.get_text(separator=" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        return ""


def fetch(category: str = "all", max_results: int = 20):
    import requests

    hint_words = THEME_HINTS.get(category)
    if category in THEME_HINTS and THEME_HINTS[category] == []:
        return []

    try:
        resp = requests.get(
            LIST_URL,
            params={"status[]": "open", "page": 1},
            headers=BROWSER_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [{"error": f"Devpost API call failed: {e}", "source_name": "Devpost"}]

    hackathons = data.get("hackathons", [])

    results = []
    for h in hackathons:
        title = (h.get("title") or "").strip()
        url = h.get("url") or ""
        if not title or not url:
            continue

        theme_names = " ".join(t.get("name", "") for t in h.get("themes", [])).lower()
        if hint_words and not any(w in theme_names for w in hint_words):
            continue

        challenge_text = _fetch_challenge_text(url)
        if not challenge_text:
            # fall back to tagline if the subdomain page didn't yield anything
            challenge_text = h.get("tagline", "") or title

        if not is_mostly_english(challenge_text or title):
            continue

        results.append({
            "id": _make_id(h.get("id")),
            "title": summarize(title, max_len=120),
            "description": summarize(challenge_text, max_len=220) or "(see hackathon page for full brief)",
            "category": category,
            "technology": theme_names or "General",
            "difficulty": f"Hackathon ({h.get('organization_name', 'Devpost')})",
            "source_name": "Devpost",
            "source_url": url,
            "date_fetched": datetime.now(timezone.utc).isoformat(),
        })
        if len(results) >= max_results:
            break

    return results


if __name__ == "__main__":
    out = fetch(max_results=5)
    for r in out:
        print(r)
