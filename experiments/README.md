# Experiments

Early scripts written while building the crawler, kept to show how the final version in [`../tiki_crawler.py`](../tiki_crawler.py) was reached. They are kept unchanged from when they were written.

> These scripts are **not** needed to run the project, and most of them no longer get data from Tiki (see the notes below). Use `tiki_crawler.py` instead. Run them from the repository root so they can find `products-0-200000.csv`.

| Order | File | Purpose | What it showed |
| --- | --- | --- | --- |
| 1 | [`step1_api_test.py`](step1_api_test.py) | Read the CSV and request one known product (`138083218`) plus the first 5 IDs with `curl_cffi` (`impersonate="chrome"`) | The API structure, and the BOM fix (`encoding="utf-8-sig"`). The full response of product `138083218` is saved in [`../sample/api_response_138083218.json`](../sample/api_response_138083218.json). |
| 2 | [`diagnose_block_page.py`](diagnose_block_page.py) | Request the first 20 IDs with `curl_cffi`, 1 s apart, and print the status, whether the body is HTML or JSON, and its size | Tiki returns an HTML page (HTTP 200, about 25 KB) instead of JSON to this client ([Bug 2](../docs/bug_report.md#bug-2--html-bot-check-page-instead-of-json)). |
| 3 | [`step2_first_crawler.py`](step2_first_crawler.py) | First full crawler: Anaconda `curl` through `subprocess`, 4 workers, 0.25 s delay, 60 s shared cooldown when blocked, `LIMIT = 50` test mode | Batching, error files, safe writes and `verify()` worked and were kept. The pace was far too fast for Tiki's rate limit, and Ctrl+C did not stop the workers. |

## From the first crawler to the final version

| | `step2_first_crawler.py` | `tiki_crawler.py` |
| --- | --- | --- |
| Workers | 4 | 1 ([Bug 6](../docs/bug_report.md#bug-6--parallel-workers-slower-than-one-worker)) |
| Delay | fixed 0.25 s | adaptive, 0.45–10 s ([Bug 3](../docs/bug_report.md#bug-3--rate-limiting)) |
| When blocked | pause 60 s, give up after 8 attempts | pause 5–15 min, retry the same ID until it succeeds |
| Ctrl+C | workers keep running until the batch ends | stops at once ([Bug 7](../docs/bug_report.md#bug-7--ctrlc-did-not-stop-the-worker-threads)) |
| Stopped mid-batch | batch lost | finished IDs kept ([Bug 8](../docs/bug_report.md#bug-8--ctrlc-lost-the-batch-in-progress)) |

Note: the docstring of `step2_first_crawler.py` says it uses "the system `curl` command", but the code already calls `/opt/anaconda3/bin/curl`. The difference between the two curl builds is explained in [Bug 4](../docs/bug_report.md#bug-4--two-curl-builds-behave-differently).
