"""
Kaggle adapter.
Uses the official `kaggle` Python package (kagglesdk under the hood, v2.2.4+).
Requires an access token at ~/.kaggle/access_token (set up once via
`kaggle.com/settings` -> API Tokens -> Generate New Token).

CONFIRMED LIVE (2026-09): api.competitions_list() returns a response object
(NOT a plain list) -- the actual list is at response.competitions.
Each competition object already has a populated `description` field at the
list level (short one-liner, no per-competition detail call needed --
unlike Zindi/SIH which required that).

Kaggle's own `category` filter uses FIXED values, different from this app's
categories: 'gettingStarted', 'featured', 'research', 'playground',
'community', 'analytics' (roughly -- passed straight to the API).
We map our app categories to the closest Kaggle category / tag signal below.
"""
import hashlib
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from text_clean import summarize, is_mostly_english

# maps our app's category filter -> Kaggle's native category param (or None = no filter)
CATEGORY_MAP = {
    "software-dev": None,   # Kaggle doesn't really have a software-dev bucket; use tag filtering instead
    "python": None,         # nearly all Kaggle comps are Python/ML; treat as "all" with tag hint
    "research": "research",
    "mba": None,             # Kaggle has no MBA/business-strategy bucket; will return empty
    "all": None,
}

# for categories with no direct Kaggle category, filter by keyword presence in tags/title instead
TAG_HINTS = {
    "software-dev": ["software", "engineering", "web", "app"],
    "python": None,  # no extra filtering, Kaggle is Python-centric by default
    "mba": ["business", "finance", "marketing", "economics"],
}


def _make_id(ref: str) -> str:
    return hashlib.sha256(ref.encode("utf-8")).hexdigest()[:16]


def fetch(category: str = "all", max_results: int = 20):
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        return [{
            "error": "kaggle package not installed. Run: pip install kaggle --break-system-packages",
            "source_name": "Kaggle",
        }]

    if category == "mba":
        # Kaggle has essentially no MBA/business-strategy competitions
        pass  # fall through, will likely return [] after tag filtering below

    try:
        api = KaggleApi()
        api.authenticate()
    except Exception as e:
        return [{
            "error": f"Kaggle auth failed. Check ~/.kaggle/access_token exists and is valid: {e}",
            "source_name": "Kaggle",
        }]

    kaggle_category = CATEGORY_MAP.get(category)

    try:
        resp = api.competitions_list(
            category=kaggle_category,
            sort_by="latestDeadline",
            page_size=max_results * 2,  # fetch extra since some get filtered out below
        )
        comps = resp.competitions if resp and resp.competitions else []
    except Exception as e:
        return [{"error": f"Kaggle API call failed: {e}", "source_name": "Kaggle"}]

    hint_words = TAG_HINTS.get(category)

    results = []
    for comp in comps:
        d = comp.to_dict()
        title = (d.get("title") or "").strip()
        desc = (d.get("description") or "").strip()
        tags = d.get("tags") or []
        tag_names = " ".join(t.get("name", "") for t in tags).lower()
        searchable = f"{title} {desc} {tag_names}".lower()

        if not title:
            continue
        if hint_words and not any(w in searchable for w in hint_words):
            continue
        if not is_mostly_english(desc or title):
            continue

        ref = d.get("ref") or d.get("url") or title
        results.append({
            "id": _make_id(str(ref)),
            "title": summarize(title, max_len=120),
            "description": summarize(desc, max_len=220) or "(see competition page for full brief)",
            "category": category,
            "technology": "Python / ML",
            "difficulty": d.get("category", "Data science competition"),
            "source_name": "Kaggle",
            "source_url": d.get("url") or ref,
            "date_fetched": datetime.now(timezone.utc).isoformat(),
        })
        if len(results) >= max_results:
            break

    return results


if __name__ == "__main__":
    out = fetch(max_results=10)
    for r in out:
        print(r)
