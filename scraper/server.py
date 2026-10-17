"""Web UI de thao tac crawl TYT.

Chay:
    python scraper\\server.py
    (hoac: run-ui.cmd)

Mo trinh duyet: http://127.0.0.1:8787

Server chi listen tren 127.0.0.1 (may cuc bo), khong lo ra mang ngoai.
Doi cong:  set TYT_UI_PORT=9000  (truoc khi chay)
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import (  # noqa: E402
    Crawler,
    export_story,
    local_chapters,
    local_stories,
    read_chapter,
    strip_html,
)
from tyt_client import TytClient, TytError, app_dir, resource_dir  # noqa: E402

ROOT = app_dir()
OUT_ROOT = os.environ.get("TYT_OUT") or os.path.join(ROOT, "out")
UI_FILE = os.path.join(resource_dir(), "scraper", "ui.html")
HOST = os.environ.get("TYT_UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("TYT_UI_PORT", "8787"))

_client = TytClient()
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_active_job: str | None = None

_img = httpx.Client(
    timeout=20.0,
    follow_redirects=True,
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    },
)


# --- helpers -------------------------------------------------------------

def fetch_list(kind: str, keyword: str, count: int, offset: int) -> list[dict]:
    if kind == "search":
        payload = _client.stories_list(limit=count, offset=offset, keyword=keyword)
    else:
        payload = _client.stories_list(limit=count, offset=offset)
    items = payload.get("data") or []
    if isinstance(items, dict):
        items = items.get("stories") or items.get("list") or items.get("items") or []
    return [normalize_story(s) for s in items if isinstance(s, dict)]


def _genre(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (ValueError, SyntaxError):
            pass
    return []


def normalize_story(s: dict) -> dict:
    return {
        "id": s.get("id"),
        "title": s.get("title") or "",
        "author": s.get("author") or "",
        "cover": s.get("cover") or "",
        "chapter_count": int(s.get("chapter_count") or 0),
        "genre": _genre(s.get("genre")),
        "full": bool(s.get("full")),
        "star": s.get("star"),
        "view_count": int(s.get("view_count") or 0),
        "like_count": int(s.get("like_count") or 0),
        "updated": s.get("updated"),
    }


def clean_desc(raw: str) -> str:
    """Mo ta co HTML -> loai bo the nguy hiem, doi <br> thanh xuong dong."""
    text = re.sub(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", "", raw or "", flags=re.I | re.S)
    text = re.sub(r"\son\w+\s*=", " data-x=", text, flags=re.I)
    return text


# --- jobs ---------------------------------------------------------------

def _on_event(job: dict, event: dict) -> None:
    etype = event.get("type")
    with _jobs_lock:
        job["updated"] = time.time()
        if etype == "story":
            job["title"] = event.get("title") or job["title"]
            job["author"] = event.get("author") or ""
            job["total"] = job["max_chapters"] or int(event.get("total") or 0)
            job["log"].append(f"Truyện: {job['title']} — {event.get('total')} chương")
        elif etype == "resume":
            job["have"] = int(event["count"] or 0)
            job["log"].append(f"Đã có {event['count']} chương, bỏ qua.")
        elif etype == "retry":
            job["log"].append(
                f"⏳ {event['label']}: {event['message']} — chờ {event['wait']}s "
                f"({event['attempt']}/{event['retries']})"
            )
        elif etype == "progress":
            job["done"] = int(event.get("done") or 0)
            job["written"] = job["done"]
            job["have"] = int(event.get("have") or 0)
            job["current"] = {"number": event.get("number"), "title": event.get("title")}
            job["chars"] = job.get("chars", 0) + int(event.get("chars") or 0)
        elif etype == "error":
            job["log"].append(f"⚠ {event['message']}")
            job["errors"].append(event["message"])
        elif etype in ("done", "stopped"):
            job["status"] = etype
            job["have"] = int(event.get("have") or job["have"])
            job["written"] = int(event.get("written") or job["written"])
            job["finished"] = time.time()
        job["log"] = job["log"][-200:]


def _run_job(job_id: str) -> None:
    global _active_job
    with _jobs_lock:
        job = _jobs[job_id]
        jid = job["story_id"]
        delay = job["delay"]
        retries = job["retries"]
        max_ch = job["max_chapters"]
        resume = job["resume"]

    crawler = Crawler(
        _client, jid, OUT_ROOT, delay=delay, retries=retries,
        on_event=lambda e: _on_event(job, e),
    )
    with _jobs_lock:
        job["crawler"] = crawler

    try:
        crawler.run(max_chapters=max_ch, resume=resume)
    except TytError as exc:
        with _jobs_lock:
            job["status"] = "error"
            job["message"] = str(exc)
            job["errors"].append(str(exc))
            job["log"].append(f"✖ Lỗi: {exc}")
            job["finished"] = time.time()
    except Exception as exc:  # noqa: BLE001
        with _jobs_lock:
            job["status"] = "error"
            job["message"] = f"{type(exc).__name__}: {exc}"
            job["log"].append(f"✖ Lỗi: {job['message']}")
            job["finished"] = time.time()
    finally:
        with _jobs_lock:
            if _active_job == job_id:
                _active_job = None


# --- HTTP ---------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "TytCrawlUI/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # bo log on ao
        pass

    # -- io helpers --
    def _send(self, body: bytes, content_type: str, code: int = 200, extra=None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            code,
        )

    def _ok(self, data) -> None:
        self._json({"ok": True, "data": data})

    def _err(self, message: str, code: int = 400) -> None:
        self._json({"ok": False, "error": message}, code)

    # -- routing --
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            self._route_get(route, q)
        except TytError as exc:
            self._err(f"{exc}", 502 if exc.retryable else 400)
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._err(f"{type(exc).__name__}: {exc}", 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            self._err("JSON khong hop le")
            return
        try:
            self._route_post(route, body)
        except TytError as exc:
            self._err(f"{exc}", 502 if exc.retryable else 400)
        except Exception as exc:  # noqa: BLE001
            self._err(f"{type(exc).__name__}: {exc}", 500)

    def _route_get(self, route: str, q: dict) -> None:
        if route in ("/", "/index.html"):
            with open(UI_FILE, "rb") as f:
                self._send(f.read(), "text/html; charset=utf-8")
            return

        if route == "/api/config":
            self._ok({"out_root": OUT_ROOT, "active_job": _active_job})
            return

        if route in ("/api/list", "/api/search"):
            keyword = q.get("keyword", "").strip()
            if route == "/api/search" and not keyword:
                self._err("Thieu tu khoa")
                return
            self._ok(fetch_list("search" if route == "/api/search" else "list",
                                keyword, _int(q.get("count"), 24, 1, 60),
                                _int(q.get("offset"), 0, 0)))
            return

        if route == "/api/story":
            sid = q.get("id", "").strip()
            if not sid:
                self._err("Thieu id")
                return
            detail = _client.story_detail(sid).get("data", {})
            data = normalize_story(detail)
            data["desc"] = clean_desc(detail.get("desc") or "")
            data["desc_text"] = strip_html(detail.get("desc") or "")
            data["status_full"] = bool(detail.get("full"))
            data["source"] = detail.get("source")
            data["updated"] = detail.get("updated")
            local = next((s for s in local_stories(OUT_ROOT) if s["story_id"] == sid), None)
            data["local"] = local
            self._ok(data)
            return

        if route == "/api/chapters":
            sid = q.get("id", "").strip()
            if not sid:
                self._err("Thieu id")
                return
            start = _int(q.get("start"), 1, 1)
            end = _int(q.get("end"), start + 49, 1)
            if end < start:
                end = start + 49
            nums = _client.chapter_numbers(sid, start, end).get("data") or []
            self._ok([
                {"number": c.get("number"), "title": c.get("title"), "id": c.get("id")}
                for c in nums if isinstance(c, dict)
            ])
            return

        if route == "/api/local":
            self._ok(local_stories(OUT_ROOT))
            return

        if route == "/api/local_chapters":
            self._ok(local_chapters(OUT_ROOT, q.get("id", "").strip()))
            return

        if route == "/api/read":
            number = _int(q.get("number"), 0, 0)
            record = read_chapter(OUT_ROOT, q.get("id", "").strip(), number)
            if record is None:
                self._err("Chua tai chuong nay", 404)
                return
            self._ok(record)
            return

        if route == "/download":
            sid = q.get("id", "").strip()
            fmt = "jsonl" if q.get("format") == "jsonl" else "txt"
            name, content = export_story(OUT_ROOT, sid, fmt)
            from urllib.parse import quote as _q
            self._send(
                content.encode("utf-8"),
                "application/json; charset=utf-8" if fmt == "jsonl" else "text/plain; charset=utf-8",
                extra={"Content-Disposition": f"attachment; filename*=UTF-8''{_q(name)}"},
            )
            return

        if route == "/cover":
            self._cover(q.get("u", ""))
            return

        if route == "/api/jobs":
            with _jobs_lock:
                self._ok([_job_public(j) for j in _jobs.values()])
            return

        if route == "/api/job":
            with _jobs_lock:
                job = _jobs.get(q.get("id", ""))
                self._ok(_job_public(job) if job else None)
            return

        self._err("Khong tim thay", 404)

    def _route_post(self, route: str, body: dict) -> None:
        global _active_job  # noqa: PLW0603

        if route == "/api/crawl":
            story_id = str(body.get("story_id") or "").strip()
            if not story_id:
                self._err("Thieu story_id")
                return
            with _jobs_lock:
                if _active_job:
                    active = _jobs.get(_active_job, {})
                    self._err(f"Đang crawl: {active.get('title') or _active_job}. Dừng lại trước đã.", 409)
                    return
                job_id = uuid.uuid4().hex[:12]
                _jobs[job_id] = {
                    "id": job_id,
                    "story_id": story_id,
                    "title": body.get("title") or story_id,
                    "author": "",
                    "status": "running",
                    "started": time.time(),
                    "updated": time.time(),
                    "finished": None,
                    "total": 0,
                    "done": 0,
                    "have": 0,
                    "written": 0,
                    "chars": 0,
                    "current": None,
                    "message": "",
                    "errors": [],
                    "log": ["Bắt đầu..."],
                    "max_chapters": max(0, int(body.get("max_chapters") or 0)),
                    "delay": min(30.0, max(0.0, float(body.get("delay") or 1.0))),
                    "retries": min(20, max(0, int(body.get("retries") or 6))),
                    "resume": bool(body.get("resume", True)),
                    "crawler": None,
                }
                _active_job = job_id
            threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
            self._ok({"job_id": job_id})
            return

        if route == "/api/stop":
            job_id = str(body.get("job_id") or _active_job or "")
            with _jobs_lock:
                job = _jobs.get(job_id)
                crawler = job.get("crawler") if job else None
            if not job:
                self._err("Khong co job", 404)
                return
            if crawler:
                crawler.stop()
                with _jobs_lock:
                    job["log"].append("⏹ Đang dừng...")
            self._ok({"stopped": job_id})
            return

        self._err("Khong tim thay", 404)

    def _cover(self, url: str) -> None:
        url = unquote(url or "")
        if not re.match(r"^https?://", url, re.I):
            self._err("URL khong hop le")
            return
        try:
            resp = _img.get(url)
        except httpx.HTTPError as exc:
            self._err(f"Khong tai duoc anh: {exc}", 502)
            return
        ctype = resp.headers.get("content-type", "image/jpeg")
        if resp.status_code != 200 or not ctype.startswith("image"):
            self._err(f"Anh loi {resp.status_code}", 502)
            return
        if len(resp.content) > 12 * 1024 * 1024:
            self._err("Anh qua lon", 413)
            return
        self._send(resp.content, ctype, extra={"Cache-Control": "max-age=86400"})


def _int(value, default: int, minimum: int, maximum: int | None = None) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    n = max(minimum, n)
    return min(maximum, n) if maximum is not None else n


def _job_public(job: dict | None) -> dict | None:
    if not job:
        return None
    return {k: v for k, v in job.items() if k != "crawler"}


def free_port(preferred: int, host: str) -> int:
    import socket

    for port in [preferred, 0]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                return s.getsockname()[1]
        except OSError:
            continue
    return preferred


def main(argv: list[str] | None = None) -> int:
    import argparse
    import webbrowser

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="TYT-Crawl", description="Crawl truyen TYT + giao dien web")
    parser.add_argument("--port", type=int, default=PORT, help=f"cong web UI (mac dinh {PORT})")
    parser.add_argument("--host", default=HOST, help=f"dia chi lang nghe (mac dinh {HOST})")
    parser.add_argument("--no-browser", action="store_true", help="khong tu mo trinh duyet")
    args = parser.parse_args(argv)

    if not os.path.exists(UI_FILE):
        print("Thieu file giao dien:", UI_FILE)
        return 1

    os.makedirs(OUT_ROOT, exist_ok=True)
    port = free_port(args.port, args.host)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{port}"

    print("=" * 60)
    print("  TYT Crawl")
    print(f"  Giao dien : {url}")
    print(f"  Du lieu   : {OUT_ROOT}")
    print("  Dong cua so nay de tat.")
    print("=" * 60)

    try:
        _client.ensure_device()
        print("  Device OK:", _client.device_id)
    except TytError as exc:
        print("  ! Chua dang ky duoc device:", exc)
    except Exception as exc:  # noqa: BLE001
        print("  ! Khong ket noi duoc API (kiem tra mang):", exc)

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    server = ThreadingHTTPServer((args.host, port), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDa dung.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
