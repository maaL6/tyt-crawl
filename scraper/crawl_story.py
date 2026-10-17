"""Crawl truyen tu API TYT (com.tytno) bang dong lenh.

Vi du:
    python scraper\\crawl_story.py list 10
    python scraper\\crawl_story.py search "linh vu"
    python scraper\\crawl_story.py story 59b410cf6fc3330b5d062f53 --max-chapters 5
    python scraper\\crawl_story.py story 59b410cf6fc3330b5d062f53          # full
    python scraper\\crawl_story.py story <id> --from 100 --to 250        # chi chuong 100-250
    python scraper\\crawl_story.py story <id> --delay 1.5 --retries 6

Chay lai voi cung story_id se TU DONG RESUME: bo qua cac chuong da co trong
chapters.jsonl (ghi them, khong ghi de).

Ket qua luu vao  out\\<story_id>\\  :  story.json, chapters.jsonl

Muon giao dien bam chuot:  python scraper\\server.py
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import Crawler  # noqa: E402
from tyt_client import TytClient  # noqa: E402

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")


def parse_list(payload) -> list:
    items = payload.get("data") or []
    if isinstance(items, dict):
        items = items.get("stories") or items.get("list") or items.get("items") or []
    return items


def cmd_list(client: TytClient, args) -> int:
    for s in parse_list(client.stories_list(limit=args.count, offset=0)):
        print(f"{s.get('id')}  {s.get('title')!r:55}  {s.get('chapter_count')} chuong  {s.get('author')!r}")
    return 0


def cmd_search(client: TytClient, args) -> int:
    items = parse_list(client.stories_list(limit=args.count, offset=0, keyword=args.keyword))
    print(f"{len(items)} ket qua cho {args.keyword!r}")
    for s in items:
        print(f"{s.get('id')}  {s.get('title')!r:55}  {s.get('chapter_count')} chuong")
    return 0


def console_events(event: dict) -> None:
    t = event.get("type")
    if t == "story":
        print(
            f"[{event['story_id']}] {event.get('title')!r} - {event.get('total')} chuong "
            f"(tai {event.get('start')}-{event.get('end')})"
        )
    elif t == "resume":
        print(f"  resume: da co {event['count']} chuong, bo qua cac chuong nay")
    elif t == "retry":
        print(f"  ! {event['label']}: {event['message']} -> cho {event['wait']}s ({event['attempt']}/{event['retries']})")
    elif t == "progress":
        if event["done"] % 20 == 0:
            print(f"  ... {event['done']} chuong moi")
    elif t == "error":
        print(f"  ⚠ {event['message']}")
    elif t in ("done", "stopped"):
        tag = "dung som" if t == "stopped" else "xong"
        print(f"{tag}: {event.get('written')} chuong moi -> {event.get('path')} (tong {event.get('have')})")


def cmd_story(client: TytClient, args) -> int:
    crawler = Crawler(
        client, args.story_id, OUT_ROOT,
        delay=args.delay, retries=args.retries, on_event=console_events,
    )
    crawler.run(
        max_chapters=args.max_chapters, resume=args.resume,
        start_chapter=args.start, end_chapter=args.end,
    )
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Crawl truyen TYT")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="liet ke truyen moi")
    p_list.add_argument("count", nargs="?", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="tim truyen theo tu khoa")
    p_search.add_argument("keyword")
    p_search.add_argument("count", nargs="?", type=int, default=20)
    p_search.set_defaults(func=cmd_search)

    p_story = sub.add_parser("story", help="crawl 1 truyen")
    p_story.add_argument("story_id")
    p_story.add_argument("--max-chapters", type=int, default=0, help="0 = tat ca")
    p_story.add_argument("--from", dest="start", type=int, default=0, help="chuong dau (mac dinh 1)")
    p_story.add_argument("--to", dest="end", type=int, default=0, help="chuong cuoi (mac dinh: het)")
    p_story.add_argument("--delay", type=float, default=1.0, help="giay giua cac request (tranh 429)")
    p_story.add_argument("--retries", type=int, default=6, help="so lan thu lai khi bi rate limit")
    p_story.add_argument("--no-resume", dest="resume", action="store_false", help="crawl lai tu dau")
    p_story.set_defaults(func=cmd_story, resume=True)

    args = parser.parse_args()
    client = TytClient()
    try:
        return args.func(client, args)
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
