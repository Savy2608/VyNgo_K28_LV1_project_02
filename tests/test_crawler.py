"""Unit tests for tiki_crawler.py.

The tests never contact Tiki: http_get() is replaced by a fake, and sleeps are
skipped, so the whole suite runs in about a second.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tiki_crawler as tc  # noqa: E402


def reset_throttle():
    """Put the shared throttle back to a clean state with no waiting."""
    tc.delay = 0
    tc.ok_streak = 0
    tc.blocks_in_a_row = 0
    tc.paused_until = 0.0
    tc.stop_event.clear()


class CleanDescriptionTest(unittest.TestCase):
    def test_empty_values(self):
        self.assertEqual(tc.clean_description(None), "")
        self.assertEqual(tc.clean_description(""), "")

    def test_removes_tags(self):
        self.assertEqual(tc.clean_description("<p>Hello <b>world</b></p>"), "Hello world")

    def test_decodes_entities(self):
        self.assertEqual(tc.clean_description("Salt &amp; pepper&nbsp;mix"), "Salt & pepper mix")

    def test_collapses_whitespace(self):
        self.assertEqual(tc.clean_description("  one<br>two \n\n three  "), "one two three")


class ExtractTest(unittest.TestCase):
    def test_keeps_only_required_fields(self):
        data = {
            "id": 1, "name": "Toy", "url_key": "toy-p1", "price": 1000,
            "description": "<p>Nice</p>", "sku": "X", "rating_average": 5,
            "images": [],
        }
        self.assertEqual(
            tc.extract(data),
            {"id": 1, "name": "Toy", "url_key": "toy-p1", "price": 1000,
             "description": "Nice", "images": []},
        )

    def test_image_urls(self):
        data = {"images": [
            {"base_url": "b1", "large_url": "l1"},
            {"large_url": "l2"},
            {"thumbnail_url": "t3"},
        ]}
        self.assertEqual(tc.extract(data)["images"], ["b1", "l2"])

    def test_missing_images(self):
        self.assertEqual(tc.extract({"images": None})["images"], [])
        self.assertEqual(tc.extract({})["images"], [])


class FetchTest(unittest.TestCase):
    """fetch() with a fake http_get(), so no request is sent."""

    def setUp(self):
        reset_throttle()
        self.saved = (tc.http_get, tc.sleep_or_stop, tc.BLOCK_PAUSE, tc.MAX_BLOCK_PAUSE)
        tc.sleep_or_stop = lambda seconds: None
        tc.BLOCK_PAUSE = tc.MAX_BLOCK_PAUSE = 0

    def tearDown(self):
        tc.http_get, tc.sleep_or_stop, tc.BLOCK_PAUSE, tc.MAX_BLOCK_PAUSE = self.saved
        reset_throttle()

    def fake_responses(self, *responses):
        """Make http_get() return the given (status, body) pairs, or raise exceptions."""
        calls = iter(responses)

        def fake(url):
            item = next(calls)
            if isinstance(item, Exception):
                raise item
            return item

        tc.http_get = fake

    def test_success(self):
        self.fake_responses((200, json.dumps({"id": 7, "name": "Pen", "images": []})))
        product, error = tc.fetch("7")
        self.assertIsNone(error)
        self.assertEqual(product["id"], 7)
        self.assertEqual(product["name"], "Pen")

    def test_not_found(self):
        self.fake_responses((404, ""))
        self.assertEqual(tc.fetch("8"), (None, {"id": "8", "reason": "HTTP 404 - product not found"}))

    def test_block_page_is_retried(self):
        self.fake_responses(
            (200, "<html>blocked</html>"),
            (429, ""),
            (200, json.dumps({"id": 9, "images": []})),
        )
        product, error = tc.fetch("9")
        self.assertIsNone(error)
        self.assertEqual(product["id"], 9)

    def test_network_errors_give_up_after_max_attempts(self):
        self.fake_responses(*[RuntimeError("curl exited with code 28")] * tc.MAX_NETWORK_RETRIES)
        product, error = tc.fetch("10")
        self.assertIsNone(product)
        self.assertEqual(error, {"id": "10", "reason": "request failed: curl exited with code 28"})

    def test_invalid_json(self):
        self.fake_responses((200, "{not json"))
        product, error = tc.fetch("11")
        self.assertIsNone(product)
        self.assertTrue(error["reason"].startswith("invalid JSON response"))


class ThrottleTest(unittest.TestCase):
    def setUp(self):
        reset_throttle()
        self.saved_pause = tc.BLOCK_PAUSE
        tc.BLOCK_PAUSE = 0

    def tearDown(self):
        tc.BLOCK_PAUSE = self.saved_pause
        reset_throttle()

    def test_block_slows_down(self):
        tc.delay = 1.0
        tc.on_blocked()
        self.assertAlmostEqual(tc.delay, 1.5)

    def test_delay_never_above_max(self):
        tc.delay = tc.MAX_DELAY
        tc.on_blocked()
        self.assertEqual(tc.delay, tc.MAX_DELAY)

    def test_speeds_up_after_streak_but_not_below_min(self):
        tc.delay = tc.MIN_DELAY
        for _ in range(tc.SPEED_UP_AFTER):
            tc.on_success()
        self.assertEqual(tc.delay, tc.MIN_DELAY)

        tc.delay = 1.0
        for _ in range(tc.SPEED_UP_AFTER):
            tc.on_success()
        self.assertAlmostEqual(tc.delay, 0.9)


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_output_dir = tc.OUTPUT_DIR
        tc.OUTPUT_DIR = self.tmp.name

    def tearDown(self):
        tc.OUTPUT_DIR = self.saved_output_dir
        self.tmp.cleanup()

    def test_save_json_is_atomic_and_keeps_unicode(self):
        path = os.path.join(self.tmp.name, "products_0001.json")
        tc.save_json(path, [{"name": "Café crème"}])
        self.assertFalse(os.path.exists(path + ".tmp"))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Café crème", text)
        self.assertEqual(json.loads(text), [{"name": "Café crème"}])

    def test_load_partial_skips_cut_off_line(self):
        path = os.path.join(self.tmp.name, "partial_0001.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"pid": "1", "product": {"id": 1}, "error": None}) + "\n")
            f.write(json.dumps({"pid": "2", "product": None, "error": {"id": "2", "reason": "HTTP 404 - product not found"}}) + "\n")
            f.write('{"pid": "3", "prod')  # the crawler was killed while writing this line
        done = tc.load_partial(path)
        self.assertEqual(set(done), {"1", "2"})
        self.assertEqual(done["1"], ({"id": 1}, None))

    def test_load_partial_missing_file(self):
        self.assertEqual(tc.load_partial(os.path.join(self.tmp.name, "nope.jsonl")), {})

    def test_verify_counts_every_id(self):
        tc.save_json(os.path.join(self.tmp.name, "products_0001.json"), [{"id": 1}, {"id": 2}])
        tc.save_json(os.path.join(self.tmp.name, "errors_0001.json"),
                     [{"id": "3", "reason": "HTTP 404 - product not found"}])
        tc.verify(["1", "2", "3", "4"])
        with open(os.path.join(self.tmp.name, "summary.json"), encoding="utf-8") as f:
            summary = json.load(f)
        self.assertEqual(summary["input_ids"], 4)
        self.assertEqual(summary["saved_products"], 2)
        self.assertEqual(summary["failed_ids"], 1)
        self.assertEqual(summary["duplicate_ids"], 0)
        self.assertEqual(summary["missing_ids"], 1)
        self.assertEqual(summary["errors_by_reason"], {"HTTP 404 - product not found": 1})


if __name__ == "__main__":
    unittest.main()
