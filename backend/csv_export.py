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

