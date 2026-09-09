"""
Main Flask app.
Run with: python3 app.py
Then open http://127.0.0.1:5000
"""
import sys
import os
sys.path.append(os.path.dirname(__file__))

from flask import Flask, render_template, request, jsonify, Response
from scrapers import github_scraper, sih_scraper, upforgrabs_scraper, zindi_scraper, kaggle_scraper, devpost_scraper
from csv_export import to_csv_string

app = Flask(__name__)

# Registry of all available sources. Add new adapters here as they're built.
SOURCES = {
    "github": github_scraper,
    "sih": sih_scraper,
    "upforgrabs": upforgrabs_scraper,
    "zindi": zindi_scraper,
    "kaggle": kaggle_scraper,
    "devpost": devpost_scraper,
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

