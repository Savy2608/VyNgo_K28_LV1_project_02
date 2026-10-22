# Tiki Product Crawler – Project 02

[![Tests](https://github.com/Savy2608/tiki-product-crawler/actions/workflows/tests.yml/badge.svg)](https://github.com/Savy2608/tiki-product-crawler/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)

**Course:** UniGap K28 Data Engineering · **Author:** Vy Ngo

This project downloads product details for 200,000 Tiki product IDs, keeps 6 fields per product, and saves them as JSON files of 1,000 products each. IDs that fail are saved in separate files together with the reason.

> **Status (Oct 22):** the crawl is still running – 15 of 200 batches are done. See [Results](#results).

## Contents

- [Assignment checklist](#assignment-checklist)
- [How to run](#how-to-run)
- [How it works](#how-it-works)
- [Output](#output)
- [Results](#results)
- [Known limitations](#known-limitations)
- [Project structure](#project-structure)
- [Documentation](#documentation)

## Assignment checklist

| Requirement | Status | Where |
| --- | --- | --- |
| Read 200,000 IDs from `products-0-200000.csv` (file has a BOM) | Done | `load_ids()` |
| Call `https://api.tiki.vn/product-detail/api/v1/products/{id}` | Done | `http_get()`, `fetch()` |
| Keep `id`, `name`, `url_key`, `price`, `description`, `images` | Done | `extract()` |
| Remove HTML from `description` | Done, 2 edge cases open ([Bug 9](docs/bug_report.md#bug-9--escaped-html-left-in-descriptions)) | `clean_description()` |
| One JSON file per 1,000 products | Done | `products_XXXX.json` |
| Save failed IDs with the reason | Done | `errors_XXXX.json` |
| Crawl all 200,000 IDs | In progress (15 / 200 batches) | [Results](#results) |

## How to run

Requirements: Python 3.9+ (tested on 3.14) and a `curl` that Tiki accepts. Only the standard library is used (see [`requirements.txt`](requirements.txt)).

```bash
git clone https://github.com/Savy2608/tiki-product-crawler.git
cd tiki-product-crawler
python tiki_crawler.py
```

On macOS, run `caffeinate -i python tiki_crawler.py` instead, so the Mac does not go to sleep during the long crawl.

- The script uses `/opt/anaconda3/bin/curl` (Anaconda's curl). Change `CURL` at the top of `tiki_crawler.py` if yours is elsewhere. Tiki blocked `requests`, `curl_cffi` and the macOS system curl ([Bug 4](docs/bug_report.md#bug-4--two-curl-builds-behave-differently)).
- To test on a few IDs first, set `LIMIT = 50`. Test output goes to `output_test/`.
- Press **Ctrl+C** to stop. Running the script again continues from the first unfinished ID.
- Run only one copy at a time, and restart the script after changing a setting.

Run the unit tests (they never contact Tiki):

```bash
python -m unittest discover -s tests -v
```

The 23 tests also run on GitHub Actions (Python 3.9 and 3.12) for every push.

## How it works

The crawler is one script, [`tiki_crawler.py`](tiki_crawler.py), organized as a small pipeline:

| Step | What happens | Functions |
| --- | --- | --- |
| 1. Input | Read the IDs and split them into 200 batches of 1,000 | `load_ids()`, `main()` |
| 2. Extract | Request each ID with curl, pacing requests and retrying when Tiki blocks | `fetch()`, `http_get()` |
| 3. Transform | Keep the 6 fields, strip HTML from the description, collect image URLs | `extract()`, `clean_description()` |
| 4. Load | Write `products_XXXX.json` and `errors_XXXX.json` safely | `save_json()`, `load_partial()` |
| 5. Verify | Check that every input ID appears exactly once and write `summary.json` | `verify()` |

**Handling Tiki's limits.** Tiki returns an HTML block page (HTTP 200) or HTTP 403/429 when requests come too fast. The crawler waits `delay` seconds before each request (start 0.6 s, minimum 0.45 s). After 50 successes in a row the delay gets 10% shorter; after a block it gets 50% longer and the crawler pauses 5 minutes (up to 15 minutes if blocks continue), then retries the same ID. One worker is used, because a test with 2 workers was about 3 times slower due to block pauses ([Bug 6](docs/bug_report.md#bug-6--parallel-workers-slower-than-one-worker)).

**Errors.** HTTP 404 means the product no longer exists on Tiki; it is saved as `HTTP 404 - product not found`. Network errors are tried 5 times (waiting 5, 10, 15, 20 s), then saved with the reason.

**Stopping and resuming.** Each finished ID is appended to `output/partial_XXXX.jsonl` right away. Ctrl+C stops the worker threads with a shared `threading.Event`. On the next run, finished batches are skipped and the partial file is read back. Every JSON file is written to a `.tmp` file and then renamed, so a crash never leaves a half-written file.

All settings (`MAX_WORKERS`, `START_DELAY`, `MIN_DELAY`, `BLOCK_PAUSE`, …) are constants at the top of `tiki_crawler.py`.

## Output

Files are written to `output/`, which is not in Git because of its size (about 300 MB when complete). Real examples are in [`sample/`](sample/).

| File | Content |
| --- | --- |
| `products_XXXX.json` | Products of batch `XXXX` in input order (batch `0001` = CSV rows 1–1,000) |
| `errors_XXXX.json` | Failed IDs of batch `XXXX` with the reason |
| `summary.json` | Written at the end: saved, failed, duplicate and missing IDs, errors by reason |

Example product from batch 0006 (description and image list shortened):

```json
{
  "id": 203261704,
  "name": "ELEPHANT AND PIGGIE - MO WILLEMS + audio",
  "url_key": "elephant-and-piggie-mo-willems-audio-p203261704",
  "price": 399999,
  "description": "ELEPHANT AND PIGGIE - MO WILLEMS + audio ...",
  "images": [
    "https://salt.tikicdn.com/ts/product/a8/3f/79/5188775287d7a69ef971ef2a852cec60.jpg",
    "https://salt.tikicdn.com/ts/product/1c/18/00/e3a1ead05ea4a237fb4219f202e12355.jpg"
  ]
}
```

Product names and descriptions are stored exactly as Tiki returns them, so most of them are in Vietnamese.

Example failed ID:

```json
{ "id": "139457787", "reason": "HTTP 404 - product not found" }
```

`id` is a number in product files (from the API) and a string in error files (from the CSV). `price` is in VND.

## Results

The crawl is still running. These numbers are for the finished batches (Oct 22, 12:30 PDT); the full results from `summary.json` will be added when the crawl finishes, expected around Oct 28.

| Metric | Batches 1–15 |
| --- | --- |
| IDs processed | 15,000 |
| Saved products | 9,784 (65.2%) |
| Failed – HTTP 404 | 5,214 (34.8%) |
| Failed – network error | 2 (curl could not resolve the host; will be retried after the crawl) |
| Missing / duplicate IDs | 0 / 0 |
| Time per batch | 22–144 min, about 43 min on average |

Data checks on the finished batches:

- The output IDs match the first 15,000 input IDs exactly.
- Every saved product has a `name`, `url_key`, `price` and at least one image URL.
- 2 descriptions still contain escaped HTML such as `<span;>` ([Bug 9](docs/bug_report.md#bug-9--escaped-html-left-in-descriptions)), and 2 products have `price: 0` as returned by the API.

## Known limitations

- **Speed.** About 43 minutes per 1,000 IDs, so the full crawl takes about 6 days. Each ID starts a new `curl` process with a new connection; reusing one connection (keep-alive) may be faster but has not been tested.
- **HTML cleaning.** Tags are removed before `html.unescape`, so escaped tags survive ([Bug 9](docs/bug_report.md#bug-9--escaped-html-left-in-descriptions)). This will be fixed for all files in one step after the crawl.
- **curl path.** `CURL` points to the Anaconda install on my Mac.

## Project structure

```text
├── tiki_crawler.py          # the crawler
├── products-0-200000.csv    # input: 200,000 product IDs
├── requirements.txt         # no third-party packages needed
├── tests/                   # unit tests (no network)
├── docs/
│   ├── bug_report.md        # 9 problems found and how they were handled
│   └── task_report.md       # goal, steps and progress
├── sample/                  # example API response, products and errors
├── experiments/             # my early test scripts (see experiments/README.md)
├── .github/workflows/       # runs the tests on every push
├── .gitignore               # keeps output/, .venv/ and IDE files out of Git
└── README.md
```

## Documentation

- [Bug report](docs/bug_report.md) – the 9 problems I found while building and running the crawler: symptom, cause, how I found it, fix and lesson.
- [Task report](docs/task_report.md) – goal, approach, steps, current results and remaining work.
- [Experiments](experiments/README.md) – my first test scripts and how the first crawler differs from the final one.
