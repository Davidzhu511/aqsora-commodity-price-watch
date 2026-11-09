"""Synthetic network responses exercise monitoring failure and discovery paths."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from monitor import INDEXES, Page, article_links, check_family, extract_prices, run, safe_url
from prices import load_data
from build import render


def mongolia_page(prices=(49.37, 42.79, 39.50), published="2026-10-09"):
    rows = ''.join(f'<tr><td>{name}</td><td>test specification</td><td>{price:.2f}</td><td></td></tr>'
                   for name, price in zip(["Low moisture lignite", "Wet lignite", "High moisture lignite"], prices))
    return f'<p>{published} 17:49:05</p><table>{rows}</table>'


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.data = load_data()
        self.latest = self.data["sources"]["mn_2026-10"]["url"]
        self.index = INDEXES["mongolia_lignite"][0]
        self.pages = {self.latest: mongolia_page(), self.index: f'<a href="{self.latest}">Announcement</a>'}

    def test_official_rows_are_extracted_without_confusing_specifications(self):
        self.assertEqual(extract_prices(Page(mongolia_page()), "mongolia_lignite"),
                         {"mn_lignite_low": 49.37, "mn_lignite_wet": 42.79, "mn_lignite_high": 39.50})

    def test_duplicate_or_missing_price_rows_fail_closed(self):
        for html in [mongolia_page() + mongolia_page(), "<html>Temporary outage</html>"]:
            with self.assertRaises(ValueError):
                extract_prices(Page(html), "mongolia_lignite")

    def test_hba_decimal_comma_and_four_distinct_categories(self):
        html = '''Harga Batubara Acuan (HBA) periode pertama November 2026 sebesar USD125,60 per ton.
        HBA I 5.300 kcal/kg GAR ditetapkan USD97,85 per ton.
        HBA II 4.100 kcal/kg GAR mencapai USD69,28 per ton.
        HBA III 3.400 kcal/kg GAR ditetapkan USD46,64 per ton.'''
        self.assertEqual(extract_prices(Page(html), "indonesia_hba"),
                         {"hba": 125.60, "hba_i": 97.85, "hba_ii": 69.28, "hba_iii": 46.64})

    def test_success_does_not_modify_reviewed_prices(self):
        before = copy.deepcopy(self.data)
        result = check_family(self.data, "mongolia_lignite", {}, self.pages.__getitem__)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["pending"], [])
        self.assertEqual(self.data, before)

    def test_changed_official_value_requires_review(self):
        self.pages[self.latest] = mongolia_page((50.00, 42.79, 39.50))
        result = check_family(self.data, "mongolia_lignite", {}, self.pages.__getitem__)
        self.assertEqual(result["status"], "error")
        self.assertIn("differ", result["message"])

    def test_new_announcements_enter_review_queue_once(self):
        url = "https://mrpam.gov.mn/en/news/international-market-price-information-for-exported-mineral-products-test"
        self.pages[self.index] += f'<a href="{url}">New</a><a href="{url}">Duplicate</a>'
        self.pages[url] = mongolia_page(published="2026-11-05")
        first = check_family(self.data, "mongolia_lignite", {}, self.pages.__getitem__)
        second = check_family(self.data, "mongolia_lignite", first, self.pages.__getitem__)
        self.assertEqual(len(second["pending"]), 1)
        self.assertEqual(second["pending"][0]["status"], "pending_review")
        self.pages[self.index] = f'<a href="{self.latest}">Old</a>'
        third = check_family(self.data, "mongolia_lignite", second, self.pages.__getitem__)
        self.assertEqual(third["pending"], second["pending"])

    def test_outage_preserves_last_success_and_pending_queue(self):
        previous = {"sources": {"mongolia_lignite": {"last_success_utc": "2026-11-08T07:17:00+00:00", "pending": []}}}
        def offline(url):
            raise OSError("Network unavailable")
        result = run(self.data, previous, offline, now="2026-11-09T07:17:00+00:00")
        source = result["sources"]["mongolia_lignite"]
        self.assertEqual(source["status"], "error")
        self.assertEqual(source["last_success_utc"], "2026-11-08T07:17:00+00:00")
        self.assertIn("检查异常", render(self.data, result))

    def test_unsafe_source_urls_are_rejected(self):
        for url in ["https://example.com/", "http://mrpam.gov.mn/", "https://user:pass@mrpam.gov.mn/"]:
            with self.assertRaises(ValueError):
                safe_url(url)

    def test_empty_mongolian_index_is_reported_as_error(self):
        self.pages[self.index] = '<html>Maintenance</html>'
        result = check_family(self.data, "mongolia_lignite", {}, self.pages.__getitem__)
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
