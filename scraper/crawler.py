"""Loi crawl dung chung cho CLI (crawl_story.py) va web UI (server.py)."""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from typing import Callable

from tyt_client import TytClient, TytError


def strip_html(raw: str) -> str:
    """Chuyen HTML cua chuong/mo ta thanh text de doc."""
    text = re.sub(r"<br\s*/?>", "\n", raw or "")
    text = re.sub(r"</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


class Crawler:
    """Crawl 1 truyen, bao tien do qua callback on_event(dict)."""

    BATCH = 50

    def __init__(
        self,
        client: TytClient,
        story_id: str,
        out_root: str,
        delay: float = 1.0,
        retries: int = 6,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.client = client
        self.story_id = story_id
        self.out_root = out_root
        self.delay = delay
        self.retries = retries
        self.on_event = on_event or (lambda e: None)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    # -- helpers ----------------------------------------------------------
    def _emit(self, **event) -> None:
        try:
            self.on_event(event)
        except Exception:  # callback loi thi bo qua, khong lam chet crawl
            pass

    def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_event.is_set():
                return
            time.sleep(min(0.25, max(0.0, end - time.time())))

    def _fetch(self, fn, label: str):
        """Goi fn(), tu thu lai khi 429/5xx/mang (ton trong Retry-After)."""
        attempt = 0
        while True:
            try:
                return fn()
            except TytError as exc:
                if not exc.retryable or attempt >= self.retries:
                    raise
                wait = exc.retry_after or min(5 * (2 ** attempt), 120)
                attempt += 1
                self._emit(
                    type="retry", label=label, message=str(exc),
                    wait=round(wait), attempt=attempt, retries=self.retries,
                )
                self._sleep(wait)
                if self.stop_event.is_set():
                    raise TytError(0, "stopped") from None

    # -- main -------------------------------------------------------------
    def run(
        self,
        max_chapters: int = 0,
        resume: bool = True,
        start_chapter: int = 0,
        end_chapter: int = 0,
    ) -> dict:
        """Crawl chuong [start_chapter .. end_chapter] (bao gom 2 dau).

        start_chapter = 0 -> tu chuong 1; end_chapter = 0 -> den het (hoac dung
        max_chapters chuong tinh tu start_chapter neu max_chapters > 0).
        """
        story_id = self.story_id
        out_dir = os.path.join(self.out_root, story_id)
        os.makedirs(out_dir, exist_ok=True)

        try:
            detail = self._fetch(
                lambda: self.client.story_detail(story_id), "story detail"
            ).get("data", {})
        except TytError as exc:
            if exc.error_code == "stopped":
                self._emit(type="stopped", written=0, have=0)
                return {"story_id": story_id, "written": 0, "have": 0, "errors": ["stopped"]}
            raise

        with open(os.path.join(out_dir, "story.json"), "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)

        total_meta = int(detail.get("chapter_count") or 0)
        first = max(1, int(start_chapter or 1))
        if end_chapter:
            last = int(end_chapter)
        elif max_chapters:
            last = first + int(max_chapters) - 1
        else:
            last = total_meta
        if total_meta:  # chapters/numbers tra 400 neu end > chapter_count
            last = min(last, total_meta)
        range_total = max(0, last - first + 1)
        self._emit(
            type="story", story_id=story_id, title=detail.get("title"),
            author=detail.get("author"), total=total_meta,
            start=first, end=last, range_total=range_total,
        )
        if range_total == 0:
            message = f"Khoảng chương {first}–{last} không hợp lệ (truyện có {total_meta} chương)"
            self._emit(type="error", message=message)
            summary = {
                "story_id": story_id, "title": detail.get("title"), "total_meta": total_meta,
                "written": 0, "have": 0, "stopped": False, "errors": [message], "path": None,
            }
            self._emit(type="done", **summary)
            return summary

        chapters_path = os.path.join(out_dir, "chapters.jsonl")
        done: set[int] = set()
        if resume and os.path.exists(chapters_path):
            with open(chapters_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        done.add(int(json.loads(line)["number"]))
                    except (ValueError, KeyError, TypeError):
                        continue

        def in_range(n) -> bool:
            return isinstance(n, int) and first <= n <= last

        have_range = sum(1 for n in done if in_range(n))
        if have_range:
            self._emit(type="resume", count=have_range)

        written = 0
        errors: list[str] = []
        stopped = False

        with open(chapters_path, "a", encoding="utf-8") as f:
            start = first
            while start <= last:
                if self.stop_event.is_set():
                    stopped = True
                    break
                end = min(start + self.BATCH - 1, last)
                try:
                    nums = self._fetch(
                        lambda: self.client.chapter_numbers(story_id, start, end),
                        f"chapters/numbers {start}-{end}",
                    ).get("data") or []
                except TytError as exc:
                    if exc.error_code == "stopped":
                        stopped = True
                        break
                    self._emit(type="error", message=f"chapters/numbers {start}-{end}: {exc}")
                    errors.append(f"numbers {start}-{end}: {exc}")
                    break

                for ch in nums:
                    if self.stop_event.is_set():
                        stopped = True
                        break
                    number = ch.get("number")
                    if number in done:
                        continue
                    try:
                        content = self._fetch(
                            lambda n=number: self.client.chapter_detail(story_id, n),
                            f"chuong {number}",
                        ).get("data", {})
                    except TytError as exc:
                        if exc.error_code == "stopped":
                            stopped = True
                            break
                        self._emit(type="error", message=f"chuong {number}: {exc}")
                        errors.append(f"{number}: {exc}")
                        continue

                    record = {
                        "number": number,
                        "title": content.get("title") or ch.get("title"),
                        "chapter_id": ch.get("id"),
                        "content_html": content.get("content"),
                        "content": strip_html(content.get("content")),
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    f.flush()
                    done.add(number)
                    written += 1
                    if in_range(number):
                        have_range += 1
                    self._emit(
                        type="progress", done=written, have=have_range,
                        number=number, title=record["title"],
                        chars=len(record["content"] or ""),
                    )
                    self._sleep(self.delay)
                start = end + 1

        summary = {
            "story_id": story_id,
            "title": detail.get("title"),
            "total_meta": total_meta,
            "written": written,
            "have": have_range,
            "range": [first, last],
            "stopped": stopped,
            "errors": errors[:20],
            "path": chapters_path,
        }
        self._emit(type="stopped" if stopped else "done", **summary)
        return summary


# -- tien ich doc du lieu da crawl ---------------------------------------

def local_stories(out_root: str) -> list[dict]:
    """Liet ke cac truyen da crawl trong out/."""
    items: list[dict] = []
    if not os.path.isdir(out_root):
        return items
    for name in sorted(os.listdir(out_root)):
        sdir = os.path.join(out_root, name)
        if not os.path.isdir(sdir):
            continue
        story_path = os.path.join(sdir, "story.json")
        chapters_path = os.path.join(sdir, "chapters.jsonl")
        item = {"story_id": name, "title": name, "author": "", "cover": "",
                "chapter_count": 0, "have": 0, "bytes": 0}
        if os.path.exists(story_path):
            try:
                with open(story_path, encoding="utf-8") as f:
                    d = json.load(f)
                item["title"] = d.get("title") or name
                item["author"] = d.get("author") or ""
                item["cover"] = d.get("cover") or ""
                item["chapter_count"] = int(d.get("chapter_count") or 0)
            except (OSError, ValueError):
                pass
        if os.path.exists(chapters_path):
            count = 0
            with open(chapters_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        count += 1
            item["have"] = count
            item["bytes"] = os.path.getsize(chapters_path)
        items.append(item)
    return items


def local_chapters(out_root: str, story_id: str) -> list[dict]:
    """Danh sach chuong da tai (number + title), khong nap content."""
    path = os.path.join(out_root, story_id, "chapters.jsonl")
    result: list[dict] = []
    if not os.path.exists(path):
        return result
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            result.append({
                "number": r.get("number"),
                "title": r.get("title"),
                "chars": len(r.get("content") or ""),
            })
    result.sort(key=lambda r: (r["number"] is None, r["number"]))
    return result


def read_chapter(out_root: str, story_id: str, number: int) -> dict | None:
    """Noi dung 1 chuong da tai."""
    path = os.path.join(out_root, story_id, "chapters.jsonl")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if int(r.get("number") or -1) == number:
                return {
                    "number": r.get("number"),
                    "title": r.get("title"),
                    "content": r.get("content") or strip_html(r.get("content_html") or ""),
                }
    return None


def export_story(out_root: str, story_id: str, fmt: str = "txt") -> tuple[str, str]:
    """Tra ve (ten_file, noi_dung) de tai ve."""
    story_path = os.path.join(out_root, story_id, "story.json")
    chapters_path = os.path.join(out_root, story_id, "chapters.jsonl")
    title = story_id
    author = ""
    if os.path.exists(story_path):
        try:
            with open(story_path, encoding="utf-8") as f:
                d = json.load(f)
            title = d.get("title") or story_id
            author = d.get("author") or ""
        except (OSError, ValueError):
            pass

    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip() or story_id

    if fmt == "jsonl":
        if os.path.exists(chapters_path):
            with open(chapters_path, encoding="utf-8") as f:
                return f"{safe}.jsonl", f.read()
        return f"{safe}.jsonl", ""

    lines = [title, f"Tác giả: {author}" if author else "", "=" * 60, ""]
    if os.path.exists(chapters_path):
        with open(chapters_path, encoding="utf-8") as f:
            rows = []
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        rows.sort(key=lambda r: (r.get("number") is None, r.get("number")))
        for r in rows:
            lines.append(r.get("title") or f"Chương {r.get('number')}")
            lines.append("")
            lines.append(r.get("content") or strip_html(r.get("content_html") or ""))
            lines.append("")
            lines.append("-" * 60)
            lines.append("")
    return f"{safe}.txt", "\n".join(lines)
