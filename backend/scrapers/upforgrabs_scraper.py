"""
Up For Grabs adapter.
Source: github.com/up-for-grabs/up-for-grabs.net (gh-pages branch, _data/projects/*.yml)
Each project file has: name, desc, site, tags[], upforgrabs: {name, link}
We read the file listing via GitHub's Contents API, then fetch+parse each
YAML file from raw.githubusercontent.com. No scraping, no bot-detection risk.
"""
import requests
import hashlib
import yaml
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from text_clean import summarize, is_mostly_english

LISTING_URL = "https://api.github.com/repos/up-for-grabs/up-for-grabs.net/contents/_data/projects?ref=gh-pages"
RAW_BASE = "https://raw.githubusercontent.com/up-for-grabs/up-for-grabs.net/gh-pages/_data/projects/"

CATEGORY_KEYWORDS = {
    "software-dev": None,
    "python": ["python", "django", "flask"],
    "research": ["machine-learning", "data-science", "ai", "research"],
    "mba": [],
    "all": None,
}


def _make_id(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]


def fetch(category: str = "all", max_results: int = 20, github_token: str | None = None):
    if category not in CATEGORY_KEYWORDS:
        category = "all"
    keywords = CATEGORY_KEYWORDS.get(category)
    if keywords == []:
        return []

    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    try:
        listing_resp = requests.get(LISTING_URL, headers=headers, timeout=15)
        listing_resp.raise_for_status()
        files = listing_resp.json()
    except Exception as e:
        return [{"error": f"Could not list Up For Grabs projects: {e}", "source_name": "Up For Grabs"}]

    if not isinstance(files, list):
        return [{"error": f"Unexpected response (likely GitHub API rate limit): {files}", "source_name": "Up For Grabs"}]

    results = []
    for f in files:
        if len(results) >= max_results:
            break
        if not f["name"].endswith((".yml", ".yaml")):
            continue

        try:
            raw = requests.get(RAW_BASE + f["name"], timeout=10)
            if raw.status_code != 200:
                continue
            project = yaml.safe_load(raw.text)
        except Exception:
            continue

        if not project:
            continue

        name = project.get("name", "").strip()
        desc = (project.get("desc") or "").strip()
        tags = [t.lower() for t in (project.get("tags") or [])]
        upforgrabs = project.get("upforgrabs") or {}
        task_link = upforgrabs.get("link") or project.get("site", "")

        if not is_mostly_english(desc):
            continue
        if keywords and not any(k in tags or k in desc.lower() for k in keywords):
            continue

        results.append({
            "id": _make_id(task_link),
            "title": name,
            "description": summarize(desc, max_len=220),
            "category": category,
            "technology": ", ".join(tags[:4]) if tags else "unspecified",
            "difficulty": "Beginner-friendly (curated first-timer tasks)",
            "source_name": "Up For Grabs",
            "source_url": task_link,
            "date_fetched": datetime.now(timezone.utc).isoformat(),
        })

    return results


if __name__ == "__main__":
    out = fetch(category="python", max_results=5)
    for r in out:
        print(r.get("title"), "->", r.get("source_url"))
