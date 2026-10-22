# Task Report – Tiki Product Crawler

- **Student:** Vy Ngo · **Course:** UniGap K28 Data Engineering
- **Repository:** https://github.com/Savy2608/tiki-product-crawler
- **Status:** In progress – crawl running (15 / 200 batches done on Oct 22, expected to finish around Oct 28)

---

## 1. Goal

Download product details for 200,000 Tiki product IDs and store them as clean JSON.

- **Input:** `products-0-200000.csv` – 200,000 product IDs (UTF-8 with BOM).
- **API:** `https://api.tiki.vn/product-detail/api/v1/products/{id}`
- **Fields kept:** `id`, `name`, `url_key`, `price`, `description` (HTML removed), `images` (list of image URLs).
- **Output:** one JSON file per 1,000 products, plus a separate file of failed IDs with the reason for each failure.

## 2. Approach

| Decision | Why |
| --- | --- |
| Call Anaconda's `curl` through `subprocess` | Tiki returned an HTML bot-check page to `requests`, `curl_cffi` and the macOS system curl. Only the Anaconda curl build received JSON. |
| One worker (`MAX_WORKERS = 1`) with an adaptive delay | Tiki blocks the IP for several minutes when requests come too fast. A 2-worker test was about 3 times slower because of block pauses. |
| Adaptive throttle | Starts at 0.6 s per request, speeds up (×0.9, minimum 0.45 s) after 50 successes in a row, slows down (×1.5) and pauses 5–15 min when blocked. |
| Batches of 1,000 IDs, one file each | Matches the required output format and lets the crawl resume after a stop. |
| Write to `.tmp`, then `os.replace` | A crash never leaves a half-written JSON file. |
| Skip finished batches, keep finished IDs in a partial file | A restart resumes from the first unfinished ID. |
| `verify()` writes `summary.json` | Checks that every input ID appears exactly once in products or errors. |

## 3. Steps

1. **Explore the API** with a few requests ([`experiments/step1_api_test.py`](../experiments/step1_api_test.py)); saved a full response ([`sample/api_response_138083218.json`](../sample/api_response_138083218.json)) to learn the field structure.
2. **Read the input CSV.** Found the BOM problem (column name `\ufeffid`) and fixed it with `encoding="utf-8-sig"`.
3. **Fetch and clean one product:** keep 6 fields, strip HTML tags and entities from `description`, collect `base_url` for each image (`large_url` if `base_url` is missing).
4. **Hit bot detection** (HTML page instead of JSON, checked with [`experiments/diagnose_block_page.py`](../experiments/diagnose_block_page.py)). Tested `requests`, `curl_cffi`, `/usr/bin/curl` and `/opt/anaconda3/bin/curl`; only the last one worked.
5. **Hit rate limiting.** Measured delays: 0.30 s was blocked often, 0.45 s was more stable. Built the adaptive throttle with shared pauses.
6. **Add batching, error files, resume and safe writes** (first version: [`experiments/step2_first_crawler.py`](../experiments/step2_first_crawler.py)).
7. **Fix Ctrl+C** so it stops all worker threads within seconds (`threading.Event` + `pool.shutdown(cancel_futures=True)`).
8. **Test parallel workers** (2 workers) and go back to 1 worker after the test.
9. **Clean up the project** (test scripts moved out of the project root, later added to `experiments/`), write `.gitignore` and `README.md`, push to GitHub.
10. **Run the full crawl** with `caffeinate -i python tiki_crawler.py` to keep the Mac awake.
11. **Keep finished IDs on stop:** each result is appended to `output/partial_XXXX.jsonl`, so stopping mid-batch no longer loses work. Added sample data (`sample/`), the early test scripts (`experiments/`) and this documentation to the repository.
12. **Add automated tests:** 23 unit tests in `tests/` (no network: the HTTP call is faked) run by GitHub Actions on Python 3.9 and 3.12 for every push.

## 4. Current results (Oct 22, 12:30 PDT)

| Batches | Saved products | Failed IDs | Notes |
| --- | --- | --- | --- |
| 1–10 | 6,699 | 3,301 | All failures are HTTP 404, no missing IDs |
| 11 | 721 | 279 | All failures are HTTP 404 |
| 12 | 657 | 343 | All failures are HTTP 404 |
| 13 | 695 | 305 | All failures are HTTP 404 |
| 14 | 555 | 445 | 444 HTTP 404, 1 network error (curl could not resolve the host) |
| 15 | 457 | 543 | 542 HTTP 404, 1 network error (curl could not resolve the host) |
| **Total (15 / 200)** | **9,784** | **5,216** | 404 rate ≈ 34.8% |

Data quality checks on the saved batches:

- Input has 200,000 rows and 200,000 unique IDs (no duplicates).
- The output IDs are exactly the first 15,000 input IDs: none missing, none extra, none duplicated.
- Every saved product has a `name`, `url_key` and `price`, and at least one image URL (4.9 on average).
- 2 descriptions still contain tag-like text such as `<span;>`, which came from escaped HTML (`&lt;span;&gt;`); see [Bug 9](bug_report.md#bug-9--escaped-html-left-in-descriptions).
- 2 products have `price: 0`, kept as returned by the API.

Speed: 22–144 minutes per batch, about 43 minutes on average.

## 5. Remaining work

- [ ] Let the crawl finish (around Oct 28).
- [ ] Check `summary.json`: `missing_ids = 0`, `duplicate_ids = 0`, saved + failed = 200,000, and whether any errors other than HTTP 404 appear.
- [ ] Run the IDs that failed with a network error again (2 so far).
- [ ] Fill in the Results section of `README.md` (counts, total run time).
- [ ] Fix escaped HTML in all saved descriptions in one post-processing step ([Bug 9](bug_report.md#bug-9--escaped-html-left-in-descriptions)).
- [ ] Next: load the data into PostgreSQL (Python + PostgreSQL module, Lab 01).

## 6. Possible improvements

- Use `html.parser` instead of a regex to strip HTML, so text like "<3 … >" can never be removed by mistake.
- Reuse one connection for many requests (HTTP keep-alive) instead of starting a new `curl` process per ID, then measure whether batches get faster.
