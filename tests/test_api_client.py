"""Tests for src/api_client.py. A fake transport is used, so nothing is sent to Tiki."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import api_client  # noqa: E402
from src.api_client import Throttle, TikiClient, TransportError, is_block_page  # noqa: E402
from src.config import Config  # noqa: E402


def fast_config(**overrides):
    """A config with no waiting, so the tests run instantly."""
    values = dict(start_delay=0, min_delay=0, block_pause=0, max_block_pause=0)
    values.update(overrides)
    return Config(**values)


class FakeTransport:
    """Returns the given (status, body) pairs in order, or raises the given exceptions."""

    name = "fake"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(transport, **overrides):
    config = fast_config(**overrides)
    throttle = Throttle(config, log=lambda message: None)
    throttle.sleep = lambda seconds: None  # skip backoff waits
    return TikiClient(config, transport, throttle)


class FetchTest(unittest.TestCase):
    def test_success_returns_parsed_json(self):
        transport = FakeTransport((200, json.dumps({"id": 7, "name": "Pen"})))
        data, error = make_client(transport).fetch("7")
        self.assertIsNone(error)
        self.assertEqual(data, {"id": 7, "name": "Pen"})
        self.assertEqual(transport.urls, ["https://api.tiki.vn/product-detail/api/v1/products/7"])

    def test_not_found(self):
        client = make_client(FakeTransport((404, "")))
        self.assertEqual(client.fetch("8"), (None, {"id": "8", "reason": "HTTP 404 - product not found"}))

    def test_block_page_is_retried_until_it_succeeds(self):
        transport = FakeTransport((200, "<html>blocked</html>"), (403, ""), (429, ""),
                                  (200, json.dumps({"id": 9})))
        data, error = make_client(transport).fetch("9")
        self.assertEqual((data, error), ({"id": 9}, None))
        self.assertEqual(len(transport.urls), 4)

    def test_network_errors_give_up_after_max_attempts(self):
        errors = [TransportError("curl error 6: Could not resolve host")] * 3
        client = make_client(FakeTransport(*errors), max_network_retries=3)
        self.assertEqual(client.fetch("10"),
                         (None, {"id": "10", "reason": "request failed: curl error 6: Could not resolve host"}))

    def test_network_error_then_success(self):
        transport = FakeTransport(TransportError("timeout"), (200, json.dumps({"id": 12})))
        self.assertEqual(make_client(transport).fetch("12"), ({"id": 12}, None))

    def test_other_status_is_retried_then_recorded(self):
        client = make_client(FakeTransport((500, ""), (500, "")), max_network_retries=2)
        self.assertEqual(client.fetch("13"), (None, {"id": "13", "reason": "HTTP 500"}))

    def test_invalid_json(self):
        data, error = make_client(FakeTransport((200, "{not json"))).fetch("11")
        self.assertIsNone(data)
        self.assertTrue(error["reason"].startswith("invalid JSON response"))

    def test_block_detection(self):
        self.assertTrue(is_block_page(200, "  <!DOCTYPE html>"))
        self.assertTrue(is_block_page(429, ""))
        self.assertFalse(is_block_page(200, '{"id": 1}'))
        self.assertFalse(is_block_page(404, "<html>not found</html>"))


class ThrottleTest(unittest.TestCase):
    def make(self, **overrides):
        return Throttle(fast_config(**overrides), log=lambda message: None)

    def test_block_slows_down_and_caps_at_max(self):
        throttle = self.make(start_delay=1.0)
        throttle.on_blocked()
        self.assertAlmostEqual(throttle.delay, 1.5)
        throttle = self.make(start_delay=10.0, max_delay=10.0)
        throttle.on_blocked()
        self.assertEqual(throttle.delay, 10.0)

    def test_pause_doubles_on_repeated_blocks(self):
        throttle = self.make(block_pause=100, max_block_pause=250)
        with mock.patch.object(api_client.time, "time", return_value=1000.0):
            throttle.on_blocked()
            self.assertEqual(throttle.paused_until, 1100.0)
        with mock.patch.object(api_client.time, "time", return_value=2000.0):
            throttle.on_blocked()
            self.assertEqual(throttle.paused_until, 2200.0)
        with mock.patch.object(api_client.time, "time", return_value=3000.0):
            throttle.on_blocked()
            self.assertEqual(throttle.paused_until, 3250.0)  # capped by max_block_pause

    def test_speeds_up_after_streak_but_not_below_min(self):
        throttle = self.make(start_delay=1.0, min_delay=0.95, speed_up_after=3)
        for _ in range(3):
            throttle.on_success()
        self.assertEqual(throttle.delay, 0.95)

    def test_stop_event_interrupts_waiting(self):
        throttle = self.make(start_delay=60)
        throttle.stop_event.set()
        with self.assertRaises(api_client.CrawlerStopped):
            throttle.wait_turn()


class MakeTransportTest(unittest.TestCase):
    def test_auto_falls_back_to_curl_without_pycurl(self):
        with mock.patch.dict(sys.modules, {"pycurl": None}), \
                mock.patch.object(api_client.shutil, "which", return_value="/usr/bin/curl"):
            transport = api_client.make_transport(Config(transport="auto"))
        self.assertEqual(transport.name, "curl")

    def test_clear_error_when_curl_is_missing(self):
        with mock.patch.object(api_client.shutil, "which", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                api_client.make_transport(Config(transport="curl"))
        self.assertIn("--curl-path", str(ctx.exception))

    def test_clear_error_when_pycurl_is_required_but_missing(self):
        with mock.patch.dict(sys.modules, {"pycurl": None}):
            with self.assertRaises(SystemExit) as ctx:
                api_client.make_transport(Config(transport="pycurl"))
        self.assertIn("pycurl is not installed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
