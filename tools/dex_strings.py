"""Trich chuoi ASCII tu cac file .dex de tim endpoint API (khong can dich nguoc).

Dung: python tools\\dex_strings.py <file-hoac-thu-muc> <file-ra>
"""

from __future__ import annotations

import os
import re
import sys

STR_RE = re.compile(rb"[\x20-\x7e]{4,200}")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    target, out_path = sys.argv[1], sys.argv[2]
    files: list[str] = []
    if os.path.isfile(target):
        files = [target]
    else:
        for dirpath, _dirs, names in os.walk(target):
            for name in names:
                if name.endswith(".dex"):
                    files.append(os.path.join(dirpath, name))

    total = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for path in files:
            with open(path, "rb") as f:
                data = f.read()
            for match in STR_RE.findall(data):
                out.write(match.decode("ascii") + "\n")
                total += 1

    print(f"{total} chuoi tu {len(files)} file dex -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
