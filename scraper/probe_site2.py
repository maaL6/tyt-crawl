"""Kham pha cau truc website tytnovel.info (crawl HTML)."""

from __future__ import annotations

import re
import sys
from collections import Counter

from curl_cffi import requests as cr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://tytnovel.info"


def links(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


def main() -> None:
    r = cr.get(BASE + "/", impersonate="chrome", timeout=30)
    hrefs = links(r.text)
    print(f"== {len(hrefs)} href tren trang chu ==")
    groups: Counter[str] = Counter()
    for h in hrefs:
        if h.startswith("http") or h.startswith("#") or h.startswith("/assets") or h.startswith("/images"):
            continue
        seg = "/" + h.strip("/").split("/")[0]
        groups[seg] += 1
    for seg, n in groups.most_common():
        print(f"  {seg:20} x{n}")
    print("\n== vi du link ==")
    seen = set()
    for h in hrefs:
        if h.startswith("/") and not h.startswith(("/assets", "/images", "/cdn-cgi")):
            if h not in seen:
                seen.add(h)
                print("  ", h)
        if len(seen) >= 25:
            break


if __name__ == "__main__":
    main()
