import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prices import ROOT, history, load_data, validate
from build import render


class PriceTests(unittest.TestCase):
    def setUp(self):
        self.data = load_data()

    def test_initial_values_match_reviewed_official_rows(self):
        expected = {
            "mn_lignite_low": [35.73, 35.00, 37.96, 49.37],
            "mn_lignite_wet": [30.97, 30.33, 32.90, 42.79],
            "mn_lignite_high": [28.59, 28.00, 30.37, 39.50],
            "hba": [125.60], "hba_i": [97.85],
            "hba_ii": [69.28], "hba_iii": [46.64],
        }
        for series_id, values in expected.items():
            initial = [row["value"] for row in history(self.data, series_id)
                       if row["period_start"] <= "2026-11-01"]
            self.assertEqual(initial, values)

    def test_changes_are_sorted_and_calculated_within_one_series(self):
        self.data["records"].reverse()
        rows = history(self.data, "mn_lignite_low")
        self.assertIsNone(rows[0]["change_pct"])
        self.assertAlmostEqual(rows[-1]["change_pct"], 30.05795574288725)
        self.assertEqual(rows[-1]["previous_period"], "2026-09-01")
        self.assertIsNone(history(self.data, "hba_iii")[0]["change_pct"])

    def test_missing_month_is_not_filled(self):
        self.data["records"] = [row for row in self.data["records"] if row["source_id"] != "mn_2026-08"]
        rows = history(validate(self.data), "mn_lignite_wet")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["previous_period"], "2026-07-01")

    def test_duplicate_period_is_rejected(self):
        self.data["records"].append(copy.deepcopy(self.data["records"][0]))
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_invalid_prices_are_rejected(self):
        for value in [None, True, 0, -1, float("nan"), float("inf"), "49.37"]:
            with self.subTest(value=value):
                self.data["records"][0]["value"] = value
                with self.assertRaises(ValueError):
                    validate(self.data)

    def test_unknown_sources_are_rejected(self):
        self.data["records"][0]["source_id"] = "invented"
        with self.assertRaises(KeyError):
            validate(self.data)

    def test_cross_market_source_is_rejected(self):
        self.data["records"][0]["source_id"] = "id_hba_2026_11_1"
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_future_publication_is_rejected(self):
        self.data["sources"]["mn_2026-07"]["published_on"] = "2099-01-01"
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_reversed_and_overlapping_periods_are_rejected(self):
        self.data["sources"]["mn_2026-07"]["period_end"] = "2026-06-30"
        with self.assertRaises(ValueError):
            validate(self.data)
        self.data["sources"]["mn_2026-07"]["period_end"] = "2026-08-01"
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_unreviewed_source_host_is_rejected(self):
        self.data["sources"]["mn_2026-07"]["url"] = "https://example.com/price"
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_august_publication_and_issue_dates_are_preserved(self):
        source = self.data["sources"]["mn_2026-08"]
        self.assertEqual(source["published_on"], "2026-08-11")
        self.assertEqual(source["issue_date"], "2026-08-10")
        self.assertEqual(source["observation_start"], "2026-07-01")

    def test_templates_do_not_contain_prices(self):
        template = json.loads((ROOT / "templates/licensed-indices.json").read_text())
        self.assertTrue(all(row["value"] is None for row in template["entries"]))
        quote = json.loads((ROOT / "templates/supplier-quote.json").read_text())
        self.assertIsNone(quote["price"])

    def test_dashboard_contains_all_rows_and_escapes_text(self):
        self.data["series"]["hba"]["name"] = "<script>alert(1)</script>"
        page = render(self.data)
        self.assertEqual(page.count("<tr><td>"), len(self.data["records"]))
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("实时行情尚未接入", page)
        self.assertIn("2026-11-01 至 2026-11-14", page)


if __name__ == "__main__":
    unittest.main()
