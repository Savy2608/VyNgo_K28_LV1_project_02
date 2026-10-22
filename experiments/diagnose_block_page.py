import csv
import time

from curl_cffi import requests

with open("products-0-200000.csv", encoding="utf-8-sig") as f:
    ids = [row["id"] for row in csv.DictReader(f)][:20]

for pid in ids:
    r = requests.get(f"https://api.tiki.vn/product-detail/api/v1/products/{pid}",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    kind = "HTML" if r.text.lstrip().startswith("<") else "JSON"
    print(pid, r.status_code, kind, len(r.text))
    time.sleep(1)