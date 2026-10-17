"""Quet URL trong APK/da giai nen (dex, resources, assets...) ma khong can dich nguoc.

Dung:
    python tools\\scan_urls.py <thu-muc-hoac-file> [tu-khoa-loc]
"""

from __future__ import annotations

import collections
import os
import re
import sys

URL_RE = re.compile(rb"(?:https?)://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]{3,200}")


def iter_files(path: str):
    if os.path.isfile(path):
        yield path
        return
    for dirpath, _dirs, files in os.walk(path):
        for fn in files:
            yield os.path.join(dirpath, fn)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    target = sys.argv[1]
    needle = sys.argv[2].lower() if len(sys.argv) > 2 else ""

    urls: dict[str, set[str]] = collections.defaultdict(set)
    for path in iter_files(target):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        for raw in URL_RE.findall(data):
            try:
                url = raw.decode("ascii")
            except UnicodeDecodeError:
                continue
            url = url.rstrip('/",\\;)')
            if needle and needle not in url.lower():
                continue
            urls[url].add(os.path.basename(path))

    print(f"== {len(urls)} URL" + (f" (loc '{needle}')" if needle else "") + " ==\n")

    # Gom theo host de de doc
    by_host: dict[str, list[str]] = collections.defaultdict(list)
    for url in urls:
        host = url.split("//", 1)[-1].split("/", 1)[0]
        by_host[host].append(url)

    for host in sorted(by_host):
        print(f"# {host}")
        for url in sorted(set(by_host[host])):
            print(f"  {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
