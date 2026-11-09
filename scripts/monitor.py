"""Check official sources and discover announcements without inventing prices."""

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from prices import ROOT, load_data

INDEXES = {
    "mongolia_lignite": ["https://mrpam.gov.mn/en/news/type/price"],
    "indonesia_hba": ["https://esdm.go.id/id/media-center/arsip-berita" + suffix
                      for suffix in ["", "?page=2", "?page=3"]],
}
MONTHS = dict(zip(
    ["januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus", "september", "oktober", "november", "desember"],
    range(1, 13)))


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.rows = []
        self.row = None
        self.cell = None
        self.skip = 0
        self.feed(html)
        self.text = re.sub(r"\s+", " ", " ".join(self.parts)).strip()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.skip += 1
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"}:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"td", "th"} and self.cell is not None:
            if self.row is not None:
                self.row.append(re.sub(r"\s+", " ", " ".join(self.cell)).strip())
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)
            if self.cell is not None:
                self.cell.append(value)


def safe_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"mrpam.gov.mn", "esdm.go.id", "www.esdm.go.id"}:
        raise ValueError("Unexpected source URL")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Unexpected source URL authority")
    return url


def fetch(url):
    safe_url(url)
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "AQSora-Price-Watch/1.0 (public reference research)"})
            with urlopen(request, timeout=25) as response:
                safe_url(response.url)
                body = response.read(4_000_001)
                if len(body) > 4_000_000:
                    raise ValueError("Source exceeds expected page size")
                return body.decode("utf-8")
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def published_on(page, family):
    if family == "mongolia_lignite":
        match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}", page.text)
        if match:
            return date.fromisoformat(match[1]).isoformat()
    else:
        match = re.search(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(20\d{2})\s*-\s*Dibaca", page.text, re.I)
        if match:
            return date(int(match[3]), MONTHS[match[2].lower()], int(match[1])).isoformat()
    raise ValueError("Publication date format requires review")


def extract_prices(page, family):
    values = {}
    if family == "mongolia_lignite":
        for name, series_id in [("Low moisture lignite", "mn_lignite_low"),
                                ("Wet lignite", "mn_lignite_wet"),
                                ("High moisture lignite", "mn_lignite_high")]:
            rows = [row for row in page.rows if name in row]
            if len(rows) != 1:
                raise ValueError(f"Missing or ambiguous official row: {name}")
            numbers = [cell for cell in rows[0] if re.fullmatch(r"\d+\.\d{2}", cell)]
            if len(numbers) != 1:
                raise ValueError(f"Ambiguous price cell: {name}")
            values[series_id] = float(numbers[0])
    else:
        patterns = {
            "hba": r"Harga Batubara Acuan\s*\(HBA\)\s*periode\s+(?:pertama|kedua)\s+\w+\s+20\d{2}\s+sebesar\s+USD([\d.,]+)\s+per ton",
            "hba_i": r"\bHBA I\b.{0,100}?GAR\s+ditetapkan\s+USD([\d.,]+)\s+per ton",
            "hba_ii": r"\bHBA II\b.{0,100}?GAR\s+mencapai\s+USD([\d.,]+)\s+per ton",
            "hba_iii": r"\bHBA III\b.{0,100}?GAR\s+ditetapkan\s+USD([\d.,]+)\s+per ton",
        }
        # Indonesian thousands separators are dots and decimal separators commas.
        for series_id, pattern in patterns.items():
            matches = re.findall(pattern, page.text, re.I)
            if len(matches) != 1:
                raise ValueError(f"Missing or ambiguous price statement: {series_id}")
            values[series_id] = float(matches[0].replace(".", "").replace(",", "."))
    return values


def article_links(page, base, family):
    links = []
    for href in page.links:
        url = urljoin(base, href).split("#")[0]
        path = urlparse(url).path
        relevant = "international-market-price-information-for-exported-mineral-products" in path
        if family == "indonesia_hba":
            relevant = "/arsip-berita/" in path and any(word in path for word in ["hba", "harga-batu", "harga-acuan"])
        if relevant and url not in links:
            safe_url(url)
            links.append(url)
    return links


def check_family(data, family, previous, fetcher=fetch):
    """A family succeeds only if its index and latest stored announcement verify."""
    try:
        sources = [(key, value) for key, value in data["sources"].items() if value["family"] == family]
        source_id, latest = max(sources, key=lambda entry: entry[1]["period_start"])
        raw = fetcher(latest["url"])
        page = Page(raw)
        expected = {row["series_id"]: row["value"] for row in data["records"] if row["source_id"] == source_id}
        if extract_prices(page, family) != expected:
            raise ValueError("Official source values differ from the stored data; manual review required")
        if published_on(page, family) != latest["published_on"]:
            raise ValueError("Official publication date changed; manual review required")
        known = {value["url"] for _, value in sources}
        candidates = {item["url"]: item for item in previous.get("pending", []) if item["url"] not in known}
        discovered = []
        for index in INDEXES[family]:
            index_page = Page(fetcher(index))
            links = article_links(index_page, index, family)
            if family == "mongolia_lignite" and not links:
                raise ValueError("Official index contains no recognizable announcements")
            if family == "indonesia_hba" and not any("/arsip-berita/" in link for link in index_page.links):
                raise ValueError("ESDM news index is unavailable or its format changed")
            discovered.extend(links[:6])
        # Scan a bounded set of recent index entries. Backlog remains until a
        # reviewed source is added to prices.json, even after an index rolls over.
        for url in dict.fromkeys(discovered):
            if url in known or url in candidates:
                continue
            candidate_page = Page(fetcher(url))
            published = published_on(candidate_page, family)
            if latest["published_on"] < published <= date.today().isoformat():
                candidates[url] = {"url": url, "published_on": published, "status": "pending_review"}
        return {
            "status": "ok", "latest_source_url": latest["url"],
            "latest_period_end": latest["period_end"],
            "source_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "pending": sorted(candidates.values(), key=lambda item: item["published_on"], reverse=True),
            "message": "已检查官方目录并复核库内最近一期价格。新公告经审核后入库。",
        }
    except (OSError, ValueError) as error:
        return {**previous, "status": "error", "message": str(error)}


def run(data, previous, fetcher=fetch, now=None):
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    def check(family):
        old = previous.get("sources", {}).get(family, {})
        result = check_family(data, family, old, fetcher)
        result["last_attempt_utc"] = now
        if result["status"] == "ok":
            result["last_success_utc"] = now
        return family, result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(check, INDEXES))
    return {"schema_version": 1, "checked_at_utc": now, "schedule_utc": "07:17, 19:17 daily", "sources": results}


if __name__ == "__main__":
    path = ROOT / "data/monitoring.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    result = run(load_data(), previous)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    for family, status in result["sources"].items():
        print(f"{family}: {status['status']} — {status['message']}")
    # Publish failure status alongside the last reviewed prices. The workflow's
    # final health step fails after deployment so GitHub can report the incident.
