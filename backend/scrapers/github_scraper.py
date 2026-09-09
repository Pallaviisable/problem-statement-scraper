"""
GitHub adapter.
Uses GitHub's official free Search API — no HTML scraping needed.
Docs: https://docs.github.com/en/rest/search
"""
import requests
import hashlib
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from text_clean import summarize, is_mostly_english

GITHUB_API_URL = "https://api.github.com/search/issues"

# Maps our internal filter categories -> GitHub search labels/keywords.
# Extend this dict as you find more relevant labels.
CATEGORY_QUERY_MAP = {
    "software-dev": 'label:"good first issue" state:open',
    "python": 'label:"good first issue" language:python state:open',
    "research": 'label:"good first issue" topic:research state:open',
    "mba": None,  # GitHub has no MBA-relevant content; adapter returns empty for this category
    "all": 'label:"good first issue" state:open',
}


def _make_id(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]


def fetch(category: str = "all", max_results: int = 30, github_token: str | None = None):
    """
    Returns a list of normalized problem-statement dicts:
    {id, title, description, category, technology, source_name, source_url, date_fetched}
    """
    query = CATEGORY_QUERY_MAP.get(category)
    if not query:
        return []

    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    # over-fetch since we filter out noisy/non-English/too-short entries afterward
    params = {"q": query, "per_page": min(max_results * 3, 100)}

    try:
        resp = requests.get(GITHUB_API_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        return [{"error": str(e), "source_name": "GitHub"}]

    data = resp.json()
    items = data.get("items", [])
    results = []

    for item in items:
        title = item.get("title", "").strip()
        body = (item.get("body") or "").strip()

        # skip entries that aren't readable/substantial enough to be a real problem statement
        if not is_mostly_english(title) or not is_mostly_english(body):
            continue
        if len(body) < 60:
            continue

        description = summarize(body, max_len=240)
        source_url = item.get("html_url", "")
        repo_url = item.get("repository_url", "")
        repo_name = repo_url.split("/repos/")[-1] if repo_url else ""

        results.append({
            "id": _make_id(source_url),
            "title": title,
            "description": description or "(no description provided)",
            "category": category,
            "technology": repo_name,
            "difficulty": "Beginner-friendly (open-source contribution)",
            "source_name": "GitHub",
            "source_url": source_url,
            "date_fetched": datetime.now(timezone.utc).isoformat(),
        })
        if len(results) >= max_results:
            break

    return results


if __name__ == "__main__":
    # quick manual test
    out = fetch(category="python", max_results=5)
    for r in out:
        print(r.get("title"), "->", r.get("source_url"))

