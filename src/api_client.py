"""Talking to the Tiki API: HTTP transport, adaptive throttle, retries and backoff.

Tiki serves an HTML block page to most HTTP clients; the libcurl build that
ships with Anaconda is accepted. Two transports use it:

* PycurlTransport (default): libcurl inside Python through pycurl. Each worker
  thread keeps one curl handle, so the TLS connection is reused between
  requests (keep-alive) and no new process is started per request.
* CurlTransport (fallback): runs the curl binary with subprocess, one process
  per request. Slower, but needs no Python package.
"""
import io
import json
import shutil
import subprocess
import threading
import time

USER_AGENT = "Mozilla/5.0"


class CrawlerStopped(Exception):
    """Raised inside a worker when the user stops the crawler."""


class TransportError(Exception):
    """A request failed before an HTTP status was received (DNS, timeout, ...)."""


class PycurlTransport:
    """libcurl through pycurl, one reusable handle per thread (keep-alive)."""

    name = "pycurl"

    def __init__(self, timeout):
        import pycurl  # imported here so the rest of the crawler works without it
        self._pycurl = pycurl
        self._timeout = timeout
        self._local = threading.local()

    def _handle(self):
        if not hasattr(self._local, "curl"):
            curl = self._pycurl.Curl()
            curl.setopt(self._pycurl.USERAGENT, USER_AGENT)
            curl.setopt(self._pycurl.TIMEOUT, self._timeout)
            curl.setopt(self._pycurl.NOSIGNAL, 1)  # required for libcurl in threads
            self._local.curl = curl
        return self._local.curl

    def get(self, url):
        """Return (status_code, body)."""
        curl = self._handle()
        buffer = io.BytesIO()
        curl.setopt(self._pycurl.URL, url)
        curl.setopt(self._pycurl.WRITEDATA, buffer)
        try:
            curl.perform()
        except self._pycurl.error as e:
            code, message = e.args[0], e.args[1] if len(e.args) > 1 else ""
            raise TransportError(f"curl error {code}: {message}") from None
        status = curl.getinfo(self._pycurl.RESPONSE_CODE)
        return status, buffer.getvalue().decode("utf-8", errors="replace")


class CurlTransport:
    """The curl binary through subprocess, one process per request."""

    name = "curl"

    def __init__(self, curl_path, timeout):
        self._curl = curl_path
        self._timeout = timeout

    def get(self, url):
        """Return (status_code, body)."""
        result = subprocess.run(
            [self._curl, "-s", "--max-time", str(self._timeout), "-A", USER_AGENT,
             "-w", "\n%{http_code}", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            raise TransportError(f"curl exited with code {result.returncode}")
        body, _, status = result.stdout.rpartition("\n")
        return int(status), body


def make_transport(config):
    """Pick the transport from config.transport; explain clearly if it cannot be used."""
    if config.transport in ("auto", "pycurl"):
        try:
            return PycurlTransport(config.timeout)
        except ImportError:
            if config.transport == "pycurl":
                raise SystemExit("pycurl is not installed. Install it (pip install pycurl) "
                                 "or run with --transport curl.")
    elif config.transport != "curl":
        raise SystemExit(f"Unknown transport {config.transport!r}: use auto, pycurl or curl.")

    curl_path = config.curl_path or shutil.which("curl")
    if not curl_path or not shutil.which(curl_path):
        raise SystemExit("curl was not found. Install curl or pass its path with --curl-path "
                         "(or TIKI_CURL_PATH in .env).")
    return CurlTransport(curl_path, config.timeout)


class Throttle:
    """One pace shared by all workers: slow down and pause together when Tiki blocks,
    speed up again after a long streak of successes."""

    def __init__(self, config, stop_event=None, log=print):
        self.config = config
        self.stop_event = stop_event or threading.Event()
        self.log = log
        self.delay = config.start_delay
        self.ok_streak = 0
        self.blocks_in_a_row = 0
        self.paused_until = 0.0
        self._lock = threading.Lock()

    def sleep(self, seconds):
        """Sleep, but wake up immediately and stop if Ctrl+C was pressed."""
        if self.stop_event.wait(seconds):
            raise CrawlerStopped()

    def wait_turn(self):
        """Wait while a shared pause is active, then wait the current delay."""
        while True:
            remaining = self.paused_until - time.time()
            if remaining <= 0:
                break
            self.sleep(min(remaining, 5))
        self.sleep(self.delay)

    def on_blocked(self):
        """Pause all workers and slow down; pause longer if blocks keep happening."""
        with self._lock:
            if time.time() < self.paused_until:
                return  # another worker already started the pause
            self.delay = min(self.delay * 1.5, self.config.max_delay)
            self.ok_streak = 0
            pause = min(self.config.block_pause * 2 ** self.blocks_in_a_row,
                        self.config.max_block_pause)
            self.blocks_in_a_row += 1
            self.paused_until = time.time() + pause
            self.log(f"  [{time.strftime('%H:%M:%S')}] Blocked by Tiki, pausing {pause // 60} min "
                     f"(new delay: {self.delay:.2f}s)")

    def on_success(self):
        """Reset the block counter and speed up after a long streak of successes."""
        with self._lock:
            self.blocks_in_a_row = 0
            self.ok_streak += 1
            if self.ok_streak >= self.config.speed_up_after:
                self.delay = max(self.delay * 0.9, self.config.min_delay)
                self.ok_streak = 0


def is_block_page(status, body):
    """Tiki's bot check answers with an HTML page (HTTP 200) or HTTP 403/429."""
    return (status == 200 and body.lstrip().startswith("<")) or status in (403, 429)


class TikiClient:
    """Fetch one product: retry blocked requests until they succeed, retry network
    errors with a growing backoff, and report every other outcome as an error."""

    def __init__(self, config, transport, throttle):
        self.config = config
        self.transport = transport
        self.throttle = throttle

    def fetch(self, pid):
        """Return (product_json, None) on success or (None, error) on failure."""
        network_errors = 0
        while True:
            self.throttle.wait_turn()
            try:
                status, body = self.transport.get(self.config.api_url.format(pid))
            except TransportError as e:
                reason = f"request failed: {e}"
            else:
                if status == 404:
                    self.throttle.on_success()  # Tiki answered normally
                    return None, {"id": pid, "reason": "HTTP 404 - product not found"}
                if is_block_page(status, body):
                    self.throttle.on_blocked()
                    continue  # a block is never recorded as a failure
                if status == 200:
                    try:
                        data = json.loads(body)
                    except ValueError:
                        return None, {"id": pid, "reason": f"invalid JSON response: {body[:100]!r}"}
                    self.throttle.on_success()
                    return data, None
                reason = f"HTTP {status}"

            network_errors += 1
            if network_errors >= self.config.max_network_retries:
                return None, {"id": pid, "reason": reason}
            self.throttle.sleep(5 * network_errors)  # backoff: 5, 10, 15, 20 s
