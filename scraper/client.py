"""Template scraper: gọi lại API đã bắt được từ traffic.

Điền BASE_URL / headers / token từ captured.jsonl rồi chạy: python scraper\\client.py
"""

from __future__ import annotations

import json
import os
import time

import httpx

BASE_URL = os.environ.get("BASE_URL", "https://api.example.com")
TOKEN = os.environ.get("TOKEN", "")

HEADERS = {
    # Nên giả UA của app (thường là okhttp/...) để tránh bị chặn.
    "User-Agent": "okhttp/4.12.0",
    "Accept": "application/json",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def fetch_page(client: httpx.Client, page: int) -> list[dict]:
    resp = client.get("/v1/items", params={"page": page, "limit": 20})
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("data", [])


def crawl() -> None:
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output.jsonl")
    with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=30.0, http2=True) as client:
        for page in range(1, 51):
            try:
                items = fetch_page(client, page)
            except httpx.HTTPStatusError as exc:
                print(f"page {page}: HTTP {exc.response.status_code}, dừng")
                break

            if not items:
                print(f"page {page}: hết dữ liệu")
                break

            with open(out_path, "a", encoding="utf-8") as f:
                for item in items:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")

            print(f"page {page}: +{len(items)}")
            time.sleep(0.5)  # tránh bị rate limit


if __name__ == "__main__":
    crawl()
