"""Liệt kê các API đã bắt được trong captured.jsonl.

Dùng: python tools\\show_apis.py [chuoi_loc]
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_FILE = os.path.join(HERE, "captured.jsonl")


def main() -> int:
    needle = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    if not os.path.exists(IN_FILE):
        print(f"Chưa có {IN_FILE}. Hãy chạy mitmdump trước.")
        return 1

    counter: Counter[str] = Counter()
    json_hosts: Counter[str] = Counter()

    with open(IN_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            url = rec.get("url", "")
            if needle and needle not in url.lower():
                continue

            key = f"{rec.get('status')}  {rec.get('method')}  {url}"
            counter[key] += 1

            ctype = (rec.get("resp_headers") or {}).get("content-type", "")
            if "json" in ctype.lower():
                json_hosts[rec.get("host", "")] += 1

    print(f"== {sum(counter.values())} request" + (f" (lọc '{needle}')" if needle else "") + " ==\n")
    for key, count in counter.most_common():
        suffix = f"  x{count}" if count > 1 else ""
        print(f"{key}{suffix}")

    if json_hosts:
        print("\n== Host trả JSON nhiều nhất ==")
        for host, count in json_hosts.most_common(10):
            print(f"{count:>4}  {host}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
