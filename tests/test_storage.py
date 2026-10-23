"""Tests for src/storage.py."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage  # noqa: E402
from src.parser import clean_description  # noqa: E402


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.dir, name)

    def test_load_ids_removes_bom(self):
        with open(self.path("ids.csv"), "w", encoding="utf-8-sig") as f:
            f.write("id\n101\n 102 \n\n103\n")
        self.assertEqual(storage.load_ids(self.path("ids.csv")), ["101", "102", "103"])

    def test_save_json_is_atomic_and_keeps_unicode(self):
        storage.save_json(self.path("products_0001.json"), [{"name": "Café crème"}])
        self.assertFalse(os.path.exists(self.path("products_0001.json.tmp")))
        with open(self.path("products_0001.json"), encoding="utf-8") as f:
            self.assertIn("Café crème", f.read())

    def test_partial_file_round_trip_skips_cut_off_line(self):
        files = storage.BatchFiles(self.dir, 1)
        with files.open_partial() as handle:
            files.append_partial(handle, "1", {"id": 1}, None)
            files.append_partial(handle, "2", None, {"id": "2", "reason": "HTTP 404 - product not found"})
            handle.write('{"pid": "3", "prod')  # the crawler was killed while writing this line
        done = files.load_partial()
        self.assertEqual(set(done), {"1", "2"})
        self.assertEqual(done["1"], ({"id": 1}, None))

    def test_save_writes_files_in_input_order_and_removes_partial(self):
        files = storage.BatchFiles(self.dir, 3)
        open(files.partial, "w").close()
        done = {"b": (None, {"id": "b", "reason": "HTTP 404 - product not found"}),
                "a": ({"id": 1}, None), "c": ({"id": 3}, None)}
        products, errors = files.save(["a", "b", "c"], done)
        self.assertEqual([p["id"] for p in products], [1, 3])
        self.assertEqual(storage.load_json(files.errors), [errors[0]])
        self.assertTrue(files.is_finished())
        self.assertFalse(os.path.exists(files.partial))
        self.assertTrue(files.products.endswith("products_0003.json"))

    def test_verify_counts_every_id(self):
        storage.save_json(self.path("products_0001.json"), [{"id": 1}, {"id": 2}])
        storage.save_json(self.path("errors_0001.json"),
                          [{"id": "3", "reason": "HTTP 404 - product not found"}])
        summary = storage.verify(self.dir, ["1", "2", "3", "4"])
        self.assertEqual(summary, {
            "input_ids": 4, "saved_products": 2, "failed_ids": 1, "duplicate_ids": 0,
            "missing_ids": 1, "errors_by_reason": {"HTTP 404 - product not found": 1},
        })
        self.assertEqual(storage.load_json(self.path("summary.json")), summary)

    def test_reclean_fixes_escaped_html_in_saved_files(self):
        storage.save_json(self.path("products_0001.json"), [
            {"id": 1, "description": "<span;>Nice toy"},
            {"id": 2, "description": "Already clean"},
        ])
        self.assertEqual(storage.reclean_descriptions(self.dir, clean_description), (1, 1))
        saved = storage.load_json(self.path("products_0001.json"))
        self.assertEqual([p["description"] for p in saved], ["Nice toy", "Already clean"])


if __name__ == "__main__":
    unittest.main()
