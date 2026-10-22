import csv
from curl_cffi import requests

with open("products-0-200000.csv", encoding="utf-8-sig") as f:
    ids = [row["id"] for row in csv.DictReader(f)]
print("Total IDs:", len(ids))

for pid in ["138083218"] + ids[:5]:
    url = f"https://api.tiki.vn/product-detail/api/v1/products/{pid}"
    r = requests.get(url, impersonate="chrome", timeout=10)
    if r.ok:
        print(pid, r.status_code, r.json().get("name"))
    else:
        print(pid, r.status_code, "ERROR:", r.text[:150])