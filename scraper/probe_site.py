"""Thu nghiem: website tytnovel.info co API de crawl khong."""

from __future__ import annotations

import re
import sys

from curl_cffi import requests as cr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    r = cr.get("https://tytnovel.info/", impersonate="chrome", timeout=30)
    print("status", r.status_code, "len", len(r.text))
    print("title:", re.findall(r"<title>(.*?)</title>", r.text))
    print("\nscript src:")
    for s in re.findall(r'<script[^>]*src="([^"]+)"', r.text)[:20]:
        print("  ", s)
    print("\nlink href:")
    for s in re.findall(r'<link[^>]*href="([^"]+)"', r.text)[:20]:
        print("  ", s)
    print("\napi/v1/v2 hints in html:")
    hints = set(re.findall(r"[\"'](/[a-zA-Z0-9_/.-]*(?:api|v1|v2|story|stories|chapter)[a-zA-Z0-9_/.-]*)[\"']", r.text))
    for h in sorted(hints)[:30]:
        print("  ", h)
    print("\nbody preview:")
    print(r.text[:600])


if __name__ == "__main__":
    main()
