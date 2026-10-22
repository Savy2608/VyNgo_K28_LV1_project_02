"""
Project 02 - Tiki product crawler

Downloads product details for 200k product IDs from the Tiki API and saves
them into JSON files of 1,000 products each. Failed IDs are saved together
with the reason for the failure. A summary.json report is written at the end.

Tiki rate-limits the API: when requests come in too fast it returns an HTML
block page instead of JSON. The crawler runs MAX_WORKERS worker threads (1 by
default) that share one adaptive throttle: every worker slows down and pauses
together when Tiki blocks, and the pace speeds up again after a long streak of
successes.

Press Ctrl+C to stop: pending requests are cancelled, and the next run resumes
from the first unfinished ID (finished IDs of the current batch are kept in a
partial file).
"""
import csv
import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

LIMIT = None  # set to a number (e.g. 50) to test on the first N IDs only

INPUT_FILE = "products-0-200000.csv"
OUTPUT_DIR = "output_test" if LIMIT else "output"
API_URL = "https://api.tiki.vn/product-detail/api/v1/products/{}"
CURL = "/opt/anaconda3/bin/curl"  # this curl build is accepted by Tiki
BATCH_SIZE = 1000
MAX_WORKERS = 1  # parallel requests; increase slowly if no blocks happen

START_DELAY = 0.6  # seconds each worker waits before a request at the start
MIN_DELAY = 0.45  # fastest allowed pace per worker
MAX_DELAY = 10.0  # slowest pace per worker
BLOCK_PAUSE = 300  # first pause after being blocked, doubles on repeated blocks
MAX_BLOCK_PAUSE = 900  # never pause longer than 15 minutes
SPEED_UP_AFTER = 50  # successful requests in a row before speeding up
MAX_NETWORK_RETRIES = 5

_lock = threading.Lock()
stop_event = threading.Event()  # set on Ctrl+C so every worker stops quickly
delay = START_DELAY
ok_streak = 0
blocks_in_a_row = 0
paused_until = 0.0


class CrawlerStopped(Exception):
    """Raised inside a worker when the user stops the crawler."""


def sleep_or_stop(seconds):
    """Sleep, but wake up immediately and stop if Ctrl+C was pressed."""
    if stop_event.wait(seconds):
        raise CrawlerStopped()


def http_get(url):
    """Download a URL with curl. Returns (status_code, body)."""
    result = subprocess.run(
        [CURL, "-s", "--max-time", "15", "-A", "Mozilla/5.0",
         "-w", "\n%{http_code}", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl exited with code {result.returncode}")
    body, _, status = result.stdout.rpartition("\n")
    return int(status), body


def wait_if_paused():
    """Sleep while the shared pause is active."""
    while True:
        remaining = paused_until - time.time()
        if remaining <= 0:
            return
        sleep_or_stop(min(remaining, 5))


def on_blocked():
    """Pause all workers and slow down; pause longer if blocks keep happening."""
    global delay, ok_streak, blocks_in_a_row, paused_until
    with _lock:
        if time.time() < paused_until:
            return  # another worker already started the pause
        delay = min(delay * 1.5, MAX_DELAY)
        ok_streak = 0
        pause = min(BLOCK_PAUSE * 2 ** blocks_in_a_row, MAX_BLOCK_PAUSE)
        blocks_in_a_row += 1
        paused_until = time.time() + pause
        print(f"  [{time.strftime('%H:%M:%S')}] Blocked by Tiki, pausing {pause // 60} min "
              f"(new delay: {delay:.2f}s)", flush=True)


def on_success():
    """Reset the block counter and speed up after a long streak of successes."""
    global delay, ok_streak, blocks_in_a_row
    with _lock:
        blocks_in_a_row = 0
        ok_streak += 1
        if ok_streak >= SPEED_UP_AFTER:
            delay = max(delay * 0.9, MIN_DELAY)
            ok_streak = 0


def clean_description(raw):
    """Remove HTML tags and entities, collapse whitespace."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract(data):
    """Keep only the fields required by the project."""
    images = data.get("images") or []
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "url_key": data.get("url_key"),
        "price": data.get("price"),
        "description": clean_description(data.get("description")),
        "images": [img.get("base_url") or img.get("large_url") for img in images
                   if img.get("base_url") or img.get("large_url")],
    }


def fetch(pid):
    """Return (product, None) on success or (None, error) on failure.
    Blocked requests are retried until they succeed; only network errors give up."""
    network_errors = 0
    while True:
        wait_if_paused()
        sleep_or_stop(delay)
        try:
            status, body = http_get(API_URL.format(pid))
        except Exception as e:
            network_errors += 1
            if network_errors >= MAX_NETWORK_RETRIES:
                return None, {"id": pid, "reason": f"request failed: {e}"}
            sleep_or_stop(5 * network_errors)
            continue

        if status == 404:
            on_success()
            return None, {"id": pid, "reason": "HTTP 404 - product not found"}
        if (status == 200 and body.lstrip().startswith("<")) or status in (403, 429):
            on_blocked()
            continue
        if status == 200:
            try:
                product = extract(json.loads(body))
            except ValueError:
                return None, {"id": pid, "reason": f"invalid JSON response: {body[:100]!r}"}
            on_success()
            return product, None

        network_errors += 1
        if network_errors >= MAX_NETWORK_RETRIES:
            return None, {"id": pid, "reason": f"HTTP {status}"}
        sleep_or_stop(5 * network_errors)


def load_ids():
    """Read the product IDs from the input CSV (utf-8-sig removes the BOM)."""
    with open(INPUT_FILE, encoding="utf-8-sig") as f:
        return [row["id"].strip() for row in csv.DictReader(f) if row["id"].strip()]


def save_json(path, data):
    """Write to a temp file first so a crash never leaves a half-written file."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def load_partial(path):
    """Read results already saved for an unfinished batch: {pid: (product, error)}."""
    done = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # last line may be cut off if the script was killed
                done[row["pid"]] = (row["product"], row["error"])
    return done


def verify(ids):
    """Check that every input ID appears exactly once in either products or errors."""
    saved, failed = [], []
    reasons = Counter()
    for name in sorted(os.listdir(OUTPUT_DIR)):
        path = os.path.join(OUTPUT_DIR, name)
        if not name.endswith(".json"):
            continue
        if name.startswith("products_"):
            with open(path, encoding="utf-8") as f:
                saved += [str(p["id"]) for p in json.load(f)]
        elif name.startswith("errors_"):
            with open(path, encoding="utf-8") as f:
                for e in json.load(f):
                    failed.append(str(e["id"]))
                    reasons[e["reason"]] += 1

    seen = saved + failed
    summary = {
        "input_ids": len(ids),
        "saved_products": len(saved),
        "failed_ids": len(failed),
        "duplicate_ids": len(seen) - len(set(seen)),
        "missing_ids": len(set(ids) - set(seen)),
        "errors_by_reason": dict(reasons.most_common()),
    }
    save_json(os.path.join(OUTPUT_DIR, "summary.json"), summary)
    print("Summary:")
    print(json.dumps(summary, indent=2))


def main():
    """Crawl every unfinished batch, then verify the output and write summary.json."""
    if LIMIT:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)  # fresh start for every test run
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ids = load_ids()
    if LIMIT:
        ids = ids[:LIMIT]
    batches = [ids[i:i + BATCH_SIZE] for i in range(0, len(ids), BATCH_SIZE)]
    print(f"Total IDs: {len(ids)} | Batches: {len(batches)} | Workers: {MAX_WORKERS} "
          f"| Output: {OUTPUT_DIR}/", flush=True)

    start = time.time()
    processed = 0
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        for n, batch in enumerate(batches, start=1):
            products_path = os.path.join(OUTPUT_DIR, f"products_{n:04d}.json")
            errors_path = os.path.join(OUTPUT_DIR, f"errors_{n:04d}.json")
            if os.path.exists(products_path):
                continue  # finished in a previous run

            # Every result is appended to a partial file right away, so stopping in
            # the middle of a batch keeps the IDs that were already downloaded.
            partial_path = os.path.join(OUTPUT_DIR, f"partial_{n:04d}.jsonl")
            done = load_partial(partial_path)
            todo = [pid for pid in batch if pid not in done]
            if done:
                print(f"  Batch {n}: resuming, {len(done)} IDs already done", flush=True)

            with open(partial_path, "a", encoding="utf-8") as partial:
                for pid, (product, error) in zip(todo, pool.map(fetch, todo)):
                    done[pid] = (product, error)
                    partial.write(json.dumps({"pid": pid, "product": product, "error": error},
                                             ensure_ascii=False) + "\n")
                    partial.flush()
                    processed += 1
                    if len(done) % 100 == 0:
                        rate = processed / (time.time() - start)
                        print(f"  [{time.strftime('%H:%M:%S')}] Batch {n}: "
                              f"{len(done)}/{len(batch)} | {rate:.2f} IDs/s "
                              f"| delay {delay:.2f}s", flush=True)

            products = [done[pid][0] for pid in batch if done[pid][0]]
            errors = [done[pid][1] for pid in batch if not done[pid][0]]
            save_json(errors_path, errors)
            save_json(products_path, products)  # written last: marks the batch finished
            os.remove(partial_path)
            elapsed = (time.time() - start) / 60
            print(f"Batch {n}/{len(batches)} saved: {len(products)} ok, {len(errors)} errors "
                  f"| {elapsed:.1f} min elapsed", flush=True)
    except KeyboardInterrupt:
        print("\nStopping: cancelling pending requests (finished IDs are kept)...",
              flush=True)
        stop_event.set()
        pool.shutdown(wait=True, cancel_futures=True)
        print("Stopped. Run the script again to resume.", flush=True)
        return
    pool.shutdown()

    print(f"Done in {(time.time() - start) / 60:.1f} min")
    verify(ids)


if __name__ == "__main__":
    main()