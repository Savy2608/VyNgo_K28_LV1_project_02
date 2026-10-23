"""Tests for src/parser.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import clean_description, extract  # noqa: E402


class CleanDescriptionTest(unittest.TestCase):
    def test_empty_values(self):
        self.assertEqual(clean_description(None), "")
        self.assertEqual(clean_description(""), "")

    def test_removes_tags(self):
        self.assertEqual(clean_description("<p>Hello <b>world</b></p>"), "Hello world")

    def test_decodes_entities(self):
        self.assertEqual(clean_description("Salt &amp; pepper&nbsp;mix"), "Salt & pepper mix")

    def test_tags_become_spaces(self):
        self.assertEqual(clean_description("  one<br>two<br/>\n\n three  "), "one two three")

    def test_escaped_html_is_removed(self):
        # Bug 9: sellers sometimes write escaped tags; they must not survive cleaning.
        self.assertEqual(clean_description("&lt;span;&gt;Nice &lt;b&gt;toy&lt;/b&gt;"), "Nice toy")

    def test_keeps_text_that_only_looks_like_a_tag(self):
        self.assertEqual(clean_description("I love it <3 so much"), "I love it <3 so much")

    def test_cleaning_twice_changes_nothing(self):
        once = clean_description("<p>Hello &amp; <b>welcome</b></p>")
        self.assertEqual(clean_description(once), once)


class ExtractTest(unittest.TestCase):
    def test_keeps_only_required_fields(self):
        data = {"id": 1, "name": "Toy", "url_key": "toy-p1", "price": 1000,
                "description": "<p>Nice</p>", "sku": "X", "rating_average": 5, "images": []}
        self.assertEqual(extract(data), {"id": 1, "name": "Toy", "url_key": "toy-p1",
                                         "price": 1000, "description": "Nice", "images": []})

    def test_image_urls(self):
        data = {"images": [{"base_url": "b1", "large_url": "l1"}, {"large_url": "l2"},
                           {"thumbnail_url": "t3"}]}
        self.assertEqual(extract(data)["images"], ["b1", "l2"])

    def test_missing_images(self):
        self.assertEqual(extract({"images": None})["images"], [])
        self.assertEqual(extract({})["images"], [])


if __name__ == "__main__":
    unittest.main()
