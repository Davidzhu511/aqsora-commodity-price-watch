"""Validate published reference prices and calculate within-series changes."""

import json
import math
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def iso_date(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError(f"Use YYYY-MM-DD dates: {value}")
    return parsed


def validate(data):
    if data["schema_version"] != 1:
        raise ValueError("Unsupported schema version")
    checked = iso_date(data["verified_on"])
    if checked > date.today():
        raise ValueError("Verification date is in the future")
    series = data["series"]
    sources = data["sources"]
    if not series or not sources or not data["records"]:
        raise ValueError("Dataset must contain series, sources and records")
    for source in sources.values():
        url = urlparse(source["url"])
        if url.scheme != "https" or url.hostname not in {"mrpam.gov.mn", "esdm.go.id"}:
            raise ValueError("Review the official source host before adding it")
        published = iso_date(source["published_on"])
        start = iso_date(source["period_start"])
        end = iso_date(source["period_end"])
        if published > checked or start > end or start > checked:
            raise ValueError("Invalid publication or applicability dates")
        observed_start = iso_date(source["observation_start"])
        observed_end = iso_date(source["observation_end"])
        if observed_start > observed_end or observed_end > published:
            raise ValueError("Invalid underlying observation dates")
    seen = set()
    for record in data["records"]:
        item = series[record["series_id"]]
        source = sources[record["source_id"]]
        value = record["value"]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Published prices must be positive finite numbers")
        if item["kind"] != "official_reference" or item["unit"] != "USD/t":
            raise ValueError("This dataset accepts official USD/t references only")
        if item["family"] != source["family"]:
            raise ValueError("Source does not match the price series")
        if item["basis"] not in {"NAR", "GAR"}:
            raise ValueError("Calorific basis must be explicit")
        key = (record["series_id"], source["period_start"])
        if key in seen:
            raise ValueError(f"Duplicate series and period: {key}")
        seen.add(key)
    for series_id in series:
        rows = history(data, series_id)
        if not rows:
            raise ValueError(f"Series has no observations: {series_id}")
        for previous, current in zip(rows, rows[1:]):
            if previous["period_end"] >= current["period_start"]:
                raise ValueError(f"Overlapping periods: {series_id}")
    return data


def load_data(path=ROOT / "data/prices.json"):
    return validate(json.loads(Path(path).read_text(encoding="utf-8")))


def history(data, series_id):
    rows = [dict(data["sources"][record["source_id"]], **record)
            for record in data["records"] if record["series_id"] == series_id]
    rows.sort(key=lambda row: row["period_start"])
    previous = None
    for row in rows:
        row["change_pct"] = None
        row["previous_period"] = None
        if previous is not None:
            row["change_pct"] = (row["value"] / previous["value"] - 1) * 100
            row["previous_period"] = previous["period_start"]
        previous = row
    return rows


if __name__ == "__main__":
    data = load_data()
    print(f"Validated {len(data['records'])} records across {len(data['series'])} series")
