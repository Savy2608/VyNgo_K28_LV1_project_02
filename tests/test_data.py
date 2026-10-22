"""Checks on the input CSV and the sample files in the repository."""
import csv
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCT_FIELDS = {"id", "name", "url_key", "price", "description", "images"}


def load_json(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return json.load(f)


class InputCsvTest(unittest.TestCase):
    def test_has_200000_unique_ids(self):
        with open(os.path.join(ROOT, "products-0-200000.csv"), encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            self.assertEqual(reader.fieldnames, ["id"])  # no "\ufeffid" thanks to utf-8-sig
            ids = [row["id"].strip() for row in reader]
        self.assertEqual(len(ids), 200_000)
        self.assertEqual(len(set(ids)), 200_000)
        self.assertTrue(all(pid.isdigit() for pid in ids))


class SampleFilesTest(unittest.TestCase):
    def test_products_sample_matches_output_format(self):
        products = load_json("sample", "products_sample.json")
        self.assertTrue(products)
        for p in products:
            self.assertEqual(set(p), PRODUCT_FIELDS)
            self.assertIsInstance(p["id"], int)
            self.assertIsInstance(p["price"], int)
            self.assertIsInstance(p["description"], str)
            self.assertNotRegex(p["description"], r"<[a-zA-Z/][^>]*>")
            self.assertTrue(all(url.startswith("https://") for url in p["images"]))

    def test_errors_sample_matches_output_format(self):
        errors = load_json("sample", "errors_sample.json")
        self.assertTrue(errors)
        for e in errors:
            self.assertEqual(set(e), {"id", "reason"})
            self.assertIsInstance(e["id"], str)

    def test_raw_api_response_has_the_required_fields(self):
        raw = load_json("sample", "api_response_138083218.json")
        self.assertTrue(PRODUCT_FIELDS <= set(raw))


if __name__ == "__main__":
    unittest.main()
