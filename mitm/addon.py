"""Addon mitmproxy: ghi request/response ra captured.jsonl + host bi chan ra blocked.txt.

Dùng:
    mitmdump -s mitm\\addon.py --listen-host 0.0.0.0 --listen-port 8080

Lọc theo host (tuỳ chọn):
    $env:FILTER_HOST="api.tenapp.com"; mitmdump -s mitm\\addon.py
"""

from __future__ import annotations

import datetime
import json
import os

from mitmproxy import http

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "captured.jsonl")
BLOCKED = os.path.join(ROOT, "blocked.txt")
FILTER_HOST = os.environ.get("FILTER_HOST", "").strip()

MAX_BODY = 200_000

# Host chi de telemetry/analytics -> bo qua cho do nhieu (đặt IGNORE_HOSTS="none" để tắt).
DEFAULT_IGNORE = (
    # Firebase / analytics
    "firebaselogging.googleapis.com",
    "app-measurement.com",
    "google-analytics.com",
    "googletagmanager.com",
    "crashlytics.com",
    "doubleclick.net",
    "connect.facebook.net",
    "graph.facebook.com",
    # Ads
    "googlesyndication.com",
    "googleadservices.com",
    "googleads.g.doubleclick.net",
    "unity3d.com",
    "unityads.unity3d.com",
    # Noise cua he thong
    "csi.gstatic.com",
    "connectivitycheck.gstatic.com",
    "pubsub.googleapis.com",
    "play-fe.googleapis.com",
)
_ignore_env = os.environ.get("IGNORE_HOSTS", "").strip()
if _ignore_env.lower() == "none":
    IGNORE: tuple[str, ...] = ()
elif _ignore_env:
    IGNORE = tuple(h.strip() for h in _ignore_env.split(",") if h.strip())
else:
    IGNORE = DEFAULT_IGNORE

_blocked_seen: set[str] = set()


def _is_noise(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in IGNORE)


def _text(message) -> str:
    if not message or not message.content:
        return ""
    try:
        return message.get_text(strict=False)[:MAX_BODY]
    except Exception:
        return f"<binary {len(message.content)} bytes>"


def _tls_host(data) -> str:
    """Lay host tu doi tuong mitmproxy.tls.TlsData."""
    sni = getattr(getattr(data, "conn", None), "sni", None)
    if sni:
        return str(sni)
    try:
        return str(data.context.client.sni or "?")
    except Exception:
        return "?"


def tls_failed_client(data) -> None:
    """Goi khi client KHONG tin cert cua proxy (Android 7+ / pinning).

    data la mitmproxy.tls.TlsData -> host nam o data.conn.sni.
    """
    host = _tls_host(data)
    if host in _blocked_seen or _is_noise(host):
        return
    _blocked_seen.add(host)

    line = f"{datetime.datetime.now().isoformat(timespec='seconds')}\t{host}"
    with open(BLOCKED, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"[TLS-BLOCKED] {host}   (app khong tin cert proxy)")


def response(flow: http.HTTPFlow) -> None:
    req = flow.request
    if FILTER_HOST and FILTER_HOST not in req.host:
        return
    if _is_noise(req.host):
        return

    resp = flow.response
    record = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "method": req.method,
        "url": req.pretty_url,
        "host": req.host,
        "req_headers": dict(req.headers),
        "req_body": _text(req),
        "status": resp.status_code if resp else None,
        "resp_headers": dict(resp.headers) if resp else {},
        "resp_body": _text(resp),
    }

    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[{record['status']}] {req.method} {req.pretty_url}")
