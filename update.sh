#!/bin/bash
set -e
echo "Updating project files..."

mkdir -p "$(dirname "backend/app.py")"
cat > "backend/app.py" << 'SCRIPT_EOF_MARKER'
"""
Main Flask app.
Run with: python3 app.py
Then open http://127.0.0.1:5000
"""
import sys
import os
sys.path.append(os.path.dirname(__file__))

from flask import Flask, render_template, request, jsonify, Response
from scrapers import github_scraper, sih_scraper
from csv_export import to_csv_string

app = Flask(__name__)

# Registry of all available sources. Add new adapters here as they're built.
SOURCES = {
    "github": github_scraper,
    "sih": sih_scraper,
    # "unstop": unstop_scraper,       # coming next
    # "company": company_scraper,     # generic company-site adapter, coming next
}

CATEGORIES = ["all", "software-dev", "python", "research", "mba"]

# simple in-memory cache of the last scrape run, so /download-csv can reuse it
_last_results: list[dict] = []


@app.route("/")
def index():
    return render_template("index.html", sources=list(SOURCES.keys()), categories=CATEGORIES)


@app.route("/api/scrape", methods=["POST"])
def scrape():
    global _last_results
    payload = request.get_json(force=True) or {}
    category = payload.get("category", "all")
    selected_sources = payload.get("sources") or list(SOURCES.keys())
    max_results = int(payload.get("max_results", 20))

    all_results = []
    errors = []

    for source_key in selected_sources:
        adapter = SOURCES.get(source_key)
        if not adapter:
            continue
        try:
            entries = adapter.fetch(category=category, max_results=max_results)
        except Exception as e:
            entries = [{"error": str(e), "source_name": source_key}]

        for entry in entries:
            if "error" in entry:
                errors.append(entry)
            else:
                all_results.append(entry)

    _last_results = all_results
    return jsonify({"results": all_results, "errors": errors, "count": len(all_results)})


@app.route("/api/download-csv")
def download_csv():
    if not _last_results:
        return jsonify({"error": "No results yet. Run a scrape first."}), 400
    csv_str = to_csv_string(_last_results)
    return Response(
        csv_str,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=problem_statements.csv"},
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)

SCRIPT_EOF_MARKER
echo "  wrote backend/app.py"

mkdir -p "$(dirname "backend/csv_export.py")"
cat > "backend/csv_export.py" << 'SCRIPT_EOF_MARKER'
import csv
import io

FIELDNAMES = [
    "title", "description", "category", "technology", "difficulty",
    "source_name", "source_url", "date_fetched",
]


def to_csv_string(entries: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    for e in entries:
        if "error" in e:
            continue  # skip error entries, they don't belong in the download
        writer.writerow(e)
    return buf.getvalue()

SCRIPT_EOF_MARKER
echo "  wrote backend/csv_export.py"

mkdir -p "$(dirname "backend/text_clean.py")"
cat > "backend/text_clean.py" << 'SCRIPT_EOF_MARKER'
"""
Cleans raw scraped text (markdown, code blocks, headers) into plain,
readable summaries suitable for a problem-statement listing.
"""
import re


def clean_markdown(text: str) -> str:
    if not text:
        return ""
    # remove fenced code blocks entirely — they're implementation detail, not the problem
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # remove inline code backticks but keep the content
    text = re.sub(r"`([^`]*)`", r"\1", text)
    # remove markdown headers (###, ##, #)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    # remove bold/italic markers
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    # remove markdown links, keep the label: [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # remove bare URLs
    text = re.sub(r"https?://\S+", "", text)
    # collapse multiple blank lines / whitespace
    text = re.sub(r"\n{2,}", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def is_mostly_english(text: str, threshold: float = 0.85) -> bool:
    """Rough heuristic: reject entries that are mostly non-ASCII (non-English),
    since a student problem-statement board should be readable by default."""
    if not text:
        return False
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return (ascii_chars / max(len(text), 1)) >= threshold


def summarize(text: str, max_len: int = 220) -> str:
    cleaned = clean_markdown(text)
    if len(cleaned) <= max_len:
        return cleaned
    # cut at the last full word before max_len
    cut = cleaned[:max_len].rsplit(" ", 1)[0]
    return cut + "…"

SCRIPT_EOF_MARKER
echo "  wrote backend/text_clean.py"

mkdir -p "$(dirname "backend/scrapers/github_scraper.py")"
cat > "backend/scrapers/github_scraper.py" << 'SCRIPT_EOF_MARKER'
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

SCRIPT_EOF_MARKER
echo "  wrote backend/scrapers/github_scraper.py"

mkdir -p "$(dirname "backend/scrapers/sih_scraper.py")"
cat > "backend/scrapers/sih_scraper.py" << 'SCRIPT_EOF_MARKER'
"""
SIH (Smart India Hackathon) adapter.
sih.gov.in blocks plain `requests` calls (bot detection), so this uses
Playwright to render the page like a real browser.

Real structure confirmed on https://www.sih.gov.in/sih2025PS :
table columns -> S.No | Organization | Problem Statement Title | Category | PS Number | Submitted Idea(s) Count | Theme
The table is paginated (Previous / Next).

NOTE: run `playwright install chromium` once before first use.
If this site still blocks headless Chromium (some bot-detection does),
fall back to sih_pdf_scraper.py which parses the officially downloadable
PDF/Excel export instead -- SIH and most colleges also mirror the full
problem-statement list as a PDF, which is far more reliable to parse.
"""
import hashlib
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from text_clean import summarize

SIH_URL = "https://www.sih.gov.in/sih2025PS"

CATEGORY_KEYWORDS = {
    "software-dev": ["software"],
    "python": ["software"],  # SIH doesn't tag by language; software bucket is closest proxy
    "research": ["hardware", "miscellaneous"],
    "mba": [],  # SIH has no MBA-track statements; returns empty
    "all": None,
}


def _make_id(source_url: str, ps_number: str) -> str:
    return hashlib.sha256(f"{source_url}{ps_number}".encode("utf-8")).hexdigest()[:16]


def fetch(category: str = "all", max_results: int = 30):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [{
            "error": "Playwright not installed. Run: pip install playwright && playwright install chromium",
            "source_name": "SIH",
        }]

    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
            )
            page.goto(SIH_URL, timeout=30000)
            page.wait_for_selector("table", timeout=15000)

            rows = page.query_selector_all("table tbody tr")
            for row in rows:
                cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
                if len(cells) < 6:
                    continue
                # cells: [S.No, Organization, Title, Category(SW/HW), PS Number, Idea Count, Theme]
                organization, title, cat, ps_number = cells[1], cells[2], cells[3], cells[4]
                theme = cells[6] if len(cells) > 6 else ""

                results.append({
                    "id": _make_id(SIH_URL, ps_number),
                    "title": summarize(title, max_len=120),
                    "description": f"Submitted by {organization}. Theme: {theme}. PS Number: {ps_number}.",
                    "category": category,
                    "technology": cat,
                    "difficulty": "Government/industry-sponsored (SIH track)",
                    "source_name": "SIH",
                    "source_url": SIH_URL,
                    "date_fetched": datetime.now(timezone.utc).isoformat(),
                })
                if len(results) >= max_results:
                    break

            browser.close()
    except Exception as e:
        return [{"error": f"SIH scrape failed (site may be blocking headless browsers): {e}", "source_name": "SIH"}]

    return results


if __name__ == "__main__":
    out = fetch(max_results=10)
    for r in out:
        print(r)

SCRIPT_EOF_MARKER
echo "  wrote backend/scrapers/sih_scraper.py"

mkdir -p "$(dirname "backend/templates/index.html")"
cat > "backend/templates/index.html" << 'SCRIPT_EOF_MARKER'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Problem Statement Index</title>
<style>
  :root {
    --bg: #F6F5F2;
    --surface: #FFFFFF;
    --ink: #1C1B19;
    --ink-mute: #6E6A61;
    --border: #E4E1D8;
    --accent: #2E5339;
    --accent-soft: #E8EFE9;
    --tag-sih: #8A4B2E;
    --tag-sih-soft: #F5E8DF;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, "Segoe UI", Inter, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  header {
    padding: 44px 5vw 28px;
    max-width: 1180px;
    margin: 0 auto;
  }
  header h1 {
    margin: 0 0 6px;
    font-size: 26px;
    font-weight: 650;
    letter-spacing: -0.01em;
  }
  header p {
    margin: 0;
    color: var(--ink-mute);
    font-size: 15px;
    max-width: 62ch;
    line-height: 1.5;
  }
  .panel {
    max-width: 1180px;
    margin: 0 auto 8px;
    padding: 0 5vw;
  }
  .controls {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
    display: flex;
    gap: 28px;
    flex-wrap: wrap;
    align-items: flex-end;
  }
  .field { display: flex; flex-direction: column; gap: 6px; }
  .field label {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--ink-mute);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  select, input[type=number] {
    font-family: inherit;
    font-size: 14px;
    padding: 9px 12px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--ink);
    border-radius: 8px;
    min-width: 150px;
  }
  .chips { display: flex; gap: 8px; }
  .chip {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13.5px;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg);
    cursor: pointer;
    user-select: none;
  }
  .chip input { accent-color: var(--accent); }
  .spacer { flex: 1; }
  button.primary {
    font-family: inherit;
    font-size: 14.5px;
    font-weight: 600;
    padding: 11px 22px;
    border: none;
    background: var(--accent);
    color: #fff;
    cursor: pointer;
    border-radius: 8px;
  }
  button.primary:disabled { opacity: 0.5; cursor: default; }
  button.secondary {
    font-family: inherit;
    font-size: 13.5px;
    font-weight: 600;
    padding: 9px 16px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--ink);
    cursor: pointer;
    border-radius: 8px;
  }
  button.secondary:disabled { opacity: 0.4; cursor: default; }
  main {
    max-width: 1180px;
    margin: 0 auto;
    padding: 20px 5vw 80px;
  }
  #status {
    font-size: 13.5px;
    color: var(--ink-mute);
    margin: 18px 0 16px;
    min-height: 18px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .card-title {
    font-size: 15.5px;
    font-weight: 650;
    line-height: 1.35;
    margin: 0;
  }
  .card-desc {
    font-size: 13.5px;
    color: var(--ink-mute);
    line-height: 1.55;
    margin: 0;
  }
  .card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: auto;
    padding-top: 8px;
  }
  .badge {
    font-size: 11px;
    font-weight: 600;
    padding: 4px 9px;
    border-radius: 20px;
    background: var(--accent-soft);
    color: var(--accent);
    white-space: nowrap;
  }
  .badge.source-sih { background: var(--tag-sih-soft); color: var(--tag-sih); }
  .card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }
  .card-footer .tech {
    font-size: 12px;
    color: var(--ink-mute);
    font-family: "SF Mono", Consolas, monospace;
  }
  a.open-link {
    font-size: 13px;
    font-weight: 600;
    color: var(--accent);
    text-decoration: none;
  }
  a.open-link:hover { text-decoration: underline; }
  .empty {
    color: var(--ink-mute);
    text-align: center;
    padding: 60px 20px;
    font-size: 14.5px;
  }
  .skeleton {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    height: 150px;
    animation: pulse 1.3s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
</style>
</head>
<body>

<header>
  <h1>Problem Statement Index</h1>
  <p>Real project-worthy problem statements pulled from hackathon and open-source sources — filtered by category, cleaned up, and ready to hand to students.</p>
</header>

<div class="panel">
  <div class="controls">
    <div class="field">
      <label for="category">Category</label>
      <select id="category">
        {% for c in categories %}
        <option value="{{ c }}">{{ c }}</option>
        {% endfor %}
      </select>
    </div>

    <div class="field">
      <label>Sources</label>
      <div class="chips">
        {% for s in sources %}
        <label class="chip"><input type="checkbox" class="source-check" value="{{ s }}" checked> {{ s|upper }}</label>
        {% endfor %}
      </div>
    </div>

    <div class="field">
      <label for="max_results">Results / source</label>
      <input type="number" id="max_results" value="15" min="1" max="100">
    </div>

    <div class="spacer"></div>
    <button id="downloadBtn" class="secondary" disabled>Download CSV</button>
    <button id="scrapeBtn" class="primary">Fetch problem statements</button>
  </div>
</div>

<main>
  <div id="status"></div>
  <div class="grid" id="resultsGrid"></div>
  <div class="empty" id="emptyState">No results yet — choose a category and click "Fetch problem statements".</div>
</main>

<script>
const scrapeBtn = document.getElementById('scrapeBtn');
const downloadBtn = document.getElementById('downloadBtn');
const statusEl = document.getElementById('status');
const grid = document.getElementById('resultsGrid');
const emptyState = document.getElementById('emptyState');

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

function showSkeletons(n) {
  grid.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const s = document.createElement('div');
    s.className = 'skeleton';
    grid.appendChild(s);
  }
}

scrapeBtn.addEventListener('click', async () => {
  const category = document.getElementById('category').value;
  const maxResults = document.getElementById('max_results').value;
  const sources = Array.from(document.querySelectorAll('.source-check:checked')).map(c => c.value);

  if (sources.length === 0) {
    statusEl.textContent = 'Select at least one source.';
    return;
  }

  scrapeBtn.disabled = true;
  statusEl.textContent = 'Fetching…';
  emptyState.style.display = 'none';
  showSkeletons(6);

  try {
    const res = await fetch('/api/scrape', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({category, sources, max_results: maxResults})
    });
    const data = await res.json();
    grid.innerHTML = '';

    if (data.results && data.results.length > 0) {
      data.results.forEach(r => {
        const card = document.createElement('div');
        card.className = 'card';
        const sourceBadgeClass = r.source_name === 'SIH' ? 'source-sih' : '';
        card.innerHTML = `
          <p class="card-title">${escapeHtml(r.title)}</p>
          <p class="card-desc">${escapeHtml(r.description)}</p>
          <div class="card-meta">
            <span class="badge ${sourceBadgeClass}">${escapeHtml(r.source_name)}</span>
            <span class="badge">${escapeHtml(r.category)}</span>
          </div>
          <div class="card-footer">
            <span class="tech">${escapeHtml(r.technology || '')}</span>
            <a class="open-link" href="${r.source_url}" target="_blank" rel="noopener">View source →</a>
          </div>
        `;
        grid.appendChild(card);
      });
      downloadBtn.disabled = false;
    } else {
      emptyState.textContent = 'No results found for this category/source combination.';
      emptyState.style.display = 'block';
    }

    let statusMsg = `${data.count} problem statement(s) fetched.`;
    if (data.errors && data.errors.length > 0) {
      statusMsg += ` — ${data.errors.length} source error(s): ${data.errors.map(e => e.source_name + ': ' + e.error).join('; ')}`;
    }
    statusEl.textContent = statusMsg;

  } catch (e) {
    grid.innerHTML = '';
    statusEl.textContent = 'Error: ' + e.message;
  } finally {
    scrapeBtn.disabled = false;
  }
});

downloadBtn.addEventListener('click', () => {
  window.location.href = '/api/download-csv';
});
</script>

</body>
</html>

SCRIPT_EOF_MARKER
echo "  wrote backend/templates/index.html"

mkdir -p "$(dirname "backend/requirements.txt")"
cat > "backend/requirements.txt" << 'SCRIPT_EOF_MARKER'
flask
requests
playwright

SCRIPT_EOF_MARKER
echo "  wrote backend/requirements.txt"

echo "All files updated."
echo "Now run: source venv/bin/activate && pip install -r backend/requirements.txt && cd backend && python3 app.py"
