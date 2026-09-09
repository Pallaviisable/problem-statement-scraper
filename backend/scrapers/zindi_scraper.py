"""
Zindi adapter.
Zindi's list endpoint (api.zindi.africa/v1/competitions) has NO description
field -- confirmed via live testing. The actual problem statement lives in
the per-competition detail endpoint, under pages[] where url_title=="description",
in a field called content_html (raw HTML, not Draft.js blocks).
So: fetch list -> for each item, fetch detail -> find description page -> strip HTML.
"""
import requests
import hashlib
import re
import html as html_lib
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from text_clean import summarize, is_mostly_english

LIST_URL = "https://api.zindi.africa/v1/competitions"
DETAIL_URL = "https://api.zindi.africa/v1/competitions/{slug}"

CATEGORY_MAP = {
    "software-dev": [],
    "python": ["all"],
    "research": ["all"],
    "mba": [],
    "all": ["all"],
}

_TAG_RE = re.compile(r"<[^>]+>")


def _make_id(slug: str) -> str:
    return hashlib.sha256(slug.encode("utf-8")).hexdigest()[:16]


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_description(slug: str) -> str:
    try:
        resp = requests.get(DETAIL_URL.format(slug=slug), timeout=15)
        resp.raise_for_status()
        detail = resp.json().get("data", {})
    except Exception:
        return ""

    pages = detail.get("pages", [])
    if not isinstance(pages, list):
        return ""

    for page in pages:
        if isinstance(page, dict) and page.get("url_title") == "description":
            return _strip_html(page.get("content_html", ""))

    return ""


def fetch(category: str = "all", max_results: int = 20):
    if category not in CATEGORY_MAP:
        category = "all"
    if not CATEGORY_MAP[category]:
        return []

    try:
        resp = requests.get(LIST_URL, params={"per_page": max_results}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [{"error": f"Zindi API call failed: {e}", "source_name": "Zindi"}]

    items = data if isinstance(data, list) else data.get("data", data.get("competitions", []))
    if not isinstance(items, list):
        return [{"error": f"Unexpected Zindi response shape: {str(data)[:200]}", "source_name": "Zindi"}]

    results = []
    for item in items[:max_results]:
        title = (item.get("name") or item.get("title") or "").strip()
        slug = item.get("id") or item.get("slug") or title
        if not title or not slug:
            continue

        desc = _fetch_description(str(slug))
        if not desc:
            desc = (item.get("subtitle") or "").strip()

        if not is_mostly_english(desc or title):
            continue

        results.append({
            "id": _make_id(str(slug)),
            "title": title,
            "description": summarize(desc, max_len=220) or "(see competition page for full brief)",
            "category": category,
            "technology": "Python / ML",
            "difficulty": "Data science competition (social-impact focus)",
            "source_name": "Zindi",
            "source_url": f"https://zindi.africa/competitions/{slug}",
            "date_fetched": datetime.now(timezone.utc).isoformat(),
        })

    return results


if __name__ == "__main__":
    out = fetch(max_results=5)
    for r in out:
        print(r)
