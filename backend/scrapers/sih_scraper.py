"""
SIH (Smart India Hackathon) adapter.
sih.gov.in blocks plain `requests` calls (bot detection), so this uses
Playwright to render the page like a real browser.

CONFIRMED LIVE (2026-09): the correct URL is /sih2026PS -- NOT /sih2025PS
(2025 cycle shows 0 problem statements; SIH URLs are year-specific and
change every cycle, so this may need updating again next year).

Table is DataTables + Responsive plugin, which clones cell data into HIDDEN
<td> elements for mobile card view. This means query_selector_all("td")
returns 18 cells per row, not 8 -- must filter by is_visible(), and the
HIDDEN cell at index 5 actually contains the FULL rich problem statement
text (Background/Description/Expected Solution), which is far more useful
than the visible columns alone.

Visible/used column map (0-indexed td position in the raw 18-cell row):
  [0]  S.No
  [1]  Organization
  [2]  Title
  [5]  Full description (hidden cell, richest content)
  [13] Category (Software/Hardware)
  [14] PS Number
  [15] Submitted idea count
  [16] Theme
  [17] Deadline

NOTE: run `playwright install chromium` once before first use.
"""
import hashlib
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from text_clean import summarize, is_mostly_english

SIH_URL = "https://www.sih.gov.in/sih2026PS"

CATEGORY_KEYWORDS = {
    "software-dev": ["software"],
    "python": ["software"],
    "research": ["hardware"],
    "mba": [],
    "all": None,
}


def _make_id(source_url: str, ps_number: str) -> str:
    return hashlib.sha256(f"{source_url}{ps_number}".encode("utf-8")).hexdigest()[:16]


def _extract_row(row):
    cells = row.query_selector_all("td")
    if len(cells) < 18:
        return None

    sno = cells[0].inner_text().strip()
    organization = cells[1].inner_text().strip()
    title = cells[2].inner_text().strip()
    full_desc = cells[5].inner_text().strip()
    try:
        full_desc = full_desc.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    category_raw = cells[13].inner_text().strip()
    ps_number = cells[14].inner_text().strip()
    idea_count = cells[15].inner_text().strip()
    theme = cells[16].inner_text().strip()
    deadline = cells[17].inner_text().strip()

    return {
        "sno": sno,
        "organization": organization,
        "title": title,
        "full_desc": full_desc,
        "category_raw": category_raw,
        "ps_number": ps_number,
        "idea_count": idea_count,
        "theme": theme,
        "deadline": deadline,
    }


def fetch(category: str = "all", max_results: int = 30):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [{
            "error": "Playwright not installed. Run: pip install playwright && playwright install chromium",
            "source_name": "SIH",
        }]

    allowed_cats = CATEGORY_KEYWORDS.get(category, None)
    if category in CATEGORY_KEYWORDS and CATEGORY_KEYWORDS[category] == []:
        return []

    raw_rows = []
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
            page.wait_for_timeout(2000)

            # DEBUG: capture what the browser actually sees on this server
            try:
                page.screenshot(path="/tmp/sih_debug.png", full_page=True)
                with open("/tmp/sih_debug.html", "w") as dbgf:
                    dbgf.write(page.content())
            except Exception:
                pass

            # bump page size to 100 so we need fewer "Next" clicks
            length_select = page.query_selector("select[name='dataTablePS_length']")
            if length_select:
                length_select.select_option("100")
                page.wait_for_timeout(1500)

            seen_ps_numbers = set()
            max_pages = 10  # safety cap
            for _ in range(max_pages):
                rows = page.query_selector_all("table tbody tr")
                for row in rows:
                    parsed = _extract_row(row)
                    if not parsed:
                        continue
                    if parsed["ps_number"] in seen_ps_numbers:
                        continue
                    seen_ps_numbers.add(parsed["ps_number"])
                    raw_rows.append(parsed)
                    if len(raw_rows) >= max_results:
                        break

                if len(raw_rows) >= max_results:
                    break

                next_btn = page.query_selector("a.paginate_button.next:not(.disabled)")
                if not next_btn:
                    break
                next_btn.click()
                page.wait_for_timeout(1200)

            browser.close()
    except Exception as e:
        return [{"error": f"SIH scrape failed: {e}", "source_name": "SIH"}]

    results = []
    for r in raw_rows:
        cat_lower = r["category_raw"].lower()
        if allowed_cats is not None and cat_lower not in allowed_cats:
            continue

        desc = r["full_desc"] or f"Submitted by {r['organization']}. Theme: {r['theme']}."
        if not is_mostly_english(desc or r["title"]):
            continue

        results.append({
            "id": _make_id(SIH_URL, r["ps_number"]),
            "title": summarize(r["title"], max_len=120),
            "description": summarize(desc, max_len=220),
            "category": category,
            "technology": r["category_raw"],
            "difficulty": "Government/industry-sponsored (SIH track)",
            "source_name": "SIH",
            "source_url": SIH_URL,
            "date_fetched": datetime.now(timezone.utc).isoformat(),
        })
        if len(results) >= max_results:
            break

    return results


if __name__ == "__main__":
    out = fetch(max_results=10)
    for r in out:
        print(r)
