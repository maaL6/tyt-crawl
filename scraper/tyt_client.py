"""Client day du cho API TYT (app doc truyen com.tytno).

Toan bo lay tu dich nguoc APK (jadx):

Base URL      : https://api.noveltyt.app/api/v2/   (Firebase Remote Config "apiBaseUrl")
Headers chung : client-id=tytno, client-token=tytno, client-platform=android,
                client-version=147, client-language, client-uuid=<uuid>
User-Agent    : PHAI la kieu "Dalvik/..." (HttpURLConnection cua Volley).
                Cloudflare chan request khong co UA => 403 "Just a moment".

Dang ky thiet bi (khong can dang nhap, khong can App Check):
    POST devices/session  ->  {"status":true,"data":{"device_id":..., "device_secret":...}}
    device_secret = base64url, giai ma ra DUNG 32 byte -> dung lam khoa HMAC.

Chu ky (header), ap dung cho endpoint can bao mat (vd chapters/detail):
    x-device-id = device_id
    x-ts        = (System.currentTimeMillis() + drift) / 1000   # GIÂY
    x-nonce     = UUID ngau nhien
    x-sig       = Base64( HMAC_SHA256( key=device_secret, msg=canonical ) )

canonical = METHOD | PATH | QUERY | SHA256_HEX(body) | ts | nonce
    - PATH  = phan path cua URL, vd "/api/v2/chapters/detail"
    - QUERY = chuoi query da sap xep tang dan (GET/DELETE), "" voi POST/PATCH
    - SHA256_HEX(body): POST/PATCH la hash cua body JSON compact;
      khong co body => e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

Dung:
    python scraper\\tyt_client.py            # thu vai endpoint
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import httpx

BASE_URL = os.environ.get("TYT_BASE_URL", "https://api.noveltyt.app/api/v2/")
CLIENT_VERSION = os.environ.get("TYT_CLIENT_VERSION", "147")
USER_AGENT = os.environ.get(
    "TYT_UA",
    "Dalvik/2.1.0 (Linux; U; Android 14; 2312DRA50I Build/UKQ1.231003.002)",
)
SESSION_FILE = os.environ.get("TYT_SESSION_FILE") or ""

# Cloudflare doi luc chan "dau van tay TLS" cua Python (403 "Just a moment...") du header dung.
# Khi do tu chuyen sang curl (co san tren Windows 10+ va macOS). TYT_TRANSPORT=curl de ep dung curl.
CURL = shutil.which("curl")
FORCE_CURL = os.environ.get("TYT_TRANSPORT", "").lower() == "curl"

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def app_dir() -> str:
    """Thu muc lam viec: canh file .exe khi da dong goi, nguoc lai la goc project."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir() -> str:
    """Thu muc chua tai nguyen dong goi (ui.html...)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


if not SESSION_FILE:
    SESSION_FILE = os.path.join(app_dir(), ".tyt_session.json")


class TytError(RuntimeError):
    def __init__(self, code: int, error_code: str = "", payload=None, retry_after: float | None = None,
                 detail: str = ""):
        super().__init__(f"HTTP {code} error_code={error_code!r}" + (f" ({detail})" if detail else ""))
        self.code = code
        self.error_code = error_code
        self.payload = payload
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        """Loi tam thoi nen thu lai (rate limit / loi server / mang)."""
        return self.code == 429 or self.code >= 500 or self.code == 0


class _CurlResponse:
    """Vo mong giong httpx.Response (chi phan _request can)."""

    def __init__(self, status: int, headers: dict, content: bytes):
        self.status_code = status
        self.headers = headers  # khoa viet thuong
        self.text = content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)


def _is_api_json(resp) -> bool:
    try:
        return isinstance(resp.json(), dict)
    except ValueError:
        return False


def _is_edge_block(resp) -> bool:
    """403 do Cloudflare/CDN (khong phai JSON cua API) -> thu lai bang curl."""
    return resp.status_code == 403 and (resp.headers.get("cf-mitigated") == "challenge" or not _is_api_json(resp))


def _describe(resp) -> str:
    h = resp.headers
    return (
        f"server={h.get('server')}, cf-mitigated={h.get('cf-mitigated')}, "
        f"transport={'curl' if isinstance(resp, _CurlResponse) else 'python'}, "
        f"curl={CURL or 'KHONG TIM THAY'}"
    )


def _encode(value: str) -> str:
    """Giong dj.q.e(): URLEncoder.encode + vai thay the."""
    return (
        quote(str(value), safe="")
        .replace("+", "%20")
        .replace("*", "%2A")
        .replace("%7E", "~")
        .replace("%21", "!")
        .replace("%27", "'")
        .replace("%28", "(")
        .replace("%29", ")")
    )


def build_query(params: dict) -> str:
    """Giong dj.q.d(): sap xep key tang dan, encode tung phan."""
    if not params:
        return ""
    return "&".join(f"{_encode(k)}={_encode(v)}" for k, v in sorted(params.items()))


def _pad_b64(s: str) -> str:
    return s + "=" * (-len(s) % 4)


class TytClient:
    def __init__(self, base_url: str = BASE_URL, client_uuid: str | None = None, language: str = "vi"):
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.client_uuid = client_uuid or os.environ.get("TYT_UUID") or str(uuid.uuid4())
        self.device_id: str | None = None
        self.device_secret: bytes | None = None
        self._device_lock = threading.Lock()
        self._use_curl = False
        self._drift = 0.0  # giay: gio server - gio may, hieu chinh x-ts giong app that
        self.http = httpx.Client(
            headers={
                "client-id": "tytno",
                "client-token": "tytno",
                "client-platform": "android",
                "client-version": CLIENT_VERSION,
                "client-language": language,
                "client-uuid": self.client_uuid,
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
            timeout=30.0,
            follow_redirects=True,
        )
        self._load_session()

    # --- session ---------------------------------------------------------
    def _load_session(self) -> None:
        try:
            with open(SESSION_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("client_uuid") == self.client_uuid:
                self.device_id = data.get("device_id")
                secret = data.get("device_secret")
                self.device_secret = self._decode_secret(secret) if secret else None
        except (OSError, ValueError):
            pass

    def _save_session(self) -> None:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "client_uuid": self.client_uuid,
                    "device_id": self.device_id,
                    "device_secret": base64.urlsafe_b64encode(self.device_secret).decode(),
                },
                f,
            )

    @staticmethod
    def _decode_secret(secret: str) -> bytes | None:
        raw = secret.replace("-", "+").replace("_", "/")
        data = base64.b64decode(_pad_b64(raw))
        return data if len(data) == 32 else None

    def ensure_device(self) -> None:
        if self.device_id and self.device_secret:
            return
        with self._device_lock:
            if self.device_id and self.device_secret:
                return
            payload = self._request("POST", "devices/session", body={}, signed=False)
            data = payload.get("data", {})
            secret = self._decode_secret(data["device_secret"])
            if secret is None:
                raise TytError(0, "bad_device_secret", data)
            self.device_id = data["device_id"]
            self.device_secret = secret
            self._save_session()

    def _reset_device(self) -> None:
        """Bo thiet bi cu (server tu choi: 401) de lan sau dang ky lai."""
        with self._device_lock:
            self.device_id = None
            self.device_secret = None
            try:
                os.remove(SESSION_FILE)
            except OSError:
                pass

    def _sync_clock(self, resp) -> None:
        date = resp.headers.get("date")
        if not date:
            return
        try:
            self._drift = parsedate_to_datetime(date).timestamp() - time.time()
        except (TypeError, ValueError):
            pass

    # --- transport -------------------------------------------------------
    def _sign(self, method: str, path: str, query: str, body: bytes, ts: int, nonce: str) -> str:
        body_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
        canonical = f"{method}|{path}|{query}|{body_hash}|{ts}|{nonce}"
        mac = hmac.new(self.device_secret, canonical.encode("utf-8"), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _request(self, method: str, path: str, params=None, body=None, signed=False):
        used_device = self.device_id
        try:
            return self._request_once(method, path, params, body, signed)
        except TytError as exc:
            # 401 = server khong nhan thiet bi / chu ky -> dang ky thiet bi moi va thu lai 1 lan
            if signed and exc.code == 401:
                if self.device_id == used_device:  # luong khac chua kip dang ky lai
                    self._reset_device()
                return self._request_once(method, path, params, body, signed)
            raise

    def _request_once(self, method: str, path: str, params=None, body=None, signed=False):
        url = self.base_url + path.lstrip("/")
        path_only = httpx.URL(url).path
        query = build_query(params) if params else ""
        body_bytes = b""

        headers = {}
        if signed:
            self.ensure_device()
            ts = int(time.time() + self._drift)
            nonce = str(uuid.uuid4())
            if method in ("GET", "DELETE"):
                body_bytes = b""
            else:
                body_bytes = json.dumps(body or {}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            headers = {
                "x-device-id": self.device_id,
                "x-ts": str(ts),
                "x-nonce": nonce,
                "x-sig": self._sign(method, path_only, query, body_bytes, ts, nonce),
            }

        retry_after = None
        try:
            if method in ("GET", "DELETE"):
                resp = self._send(method, url + (("?" + query) if query else ""), headers, None)
            else:
                resp = self._send(method, url, headers, body_bytes)
            ra = resp.headers.get("retry-after")
            self._sync_clock(resp)
        except (httpx.HTTPError, OSError, subprocess.SubprocessError) as exc:
            raise TytError(0, type(exc).__name__, str(exc)) from None

        if ra:
            try:
                retry_after = float(ra)
            except ValueError:
                retry_after = None

        try:
            payload = resp.json()
        except ValueError:
            raise TytError(resp.status_code, "invalid_json", resp.text[:500], retry_after, _describe(resp)) from None
        if isinstance(payload, dict) and payload.get("status") is False:
            raise TytError(resp.status_code, str(payload.get("error_code", "")), payload, retry_after)
        if resp.status_code >= 400:
            raise TytError(resp.status_code, "", payload, retry_after)
        return payload

    def _send(self, method: str, target: str, headers: dict, content: bytes | None):
        if not (self._use_curl or FORCE_CURL and CURL):
            if content is None:
                resp = self.http.request(method, target, headers=headers)
            else:
                resp = self.http.request(method, target, headers=headers, content=content)
            if not (CURL and _is_edge_block(resp)):
                return resp
            print("  [i] Cloudflare chan Python (403) -> tu dong chuyen sang curl. Day la binh thuong, khong phai loi.",
              flush=True)
        self._use_curl = True
        return self._curl(method, target, headers, content)

    def _curl(self, method: str, target: str, headers: dict, content: bytes | None):
        merged = {**self.http.headers, **headers}
        cmd = [CURL, "-sS", "-i", "--http1.1", "--compressed", "--max-time", "30", "-X", method]
        if sys.platform == "win32":
            cmd.append("--ssl-no-revoke")  # schannel hay loi kiem tra thu hoi cert sau proxy/mang cong ty
        for k, v in merged.items():
            if k.lower() not in ("host", "accept-encoding", "connection", "content-length"):
                cmd += ["-H", f"{k}: {v}"]
        if content is not None:
            cmd += ["--data-binary", "@-", "-H", "Content-Type:"]
        cmd.append(target)
        proc = subprocess.run(
            cmd, input=content, capture_output=True, timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0:
            raise OSError(f"curl loi {proc.returncode}: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
        data = proc.stdout
        while True:  # bo qua khoi "HTTP/1.1 100 Continue"
            head, _, rest = data.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            status = int(lines[0].split()[1])
            if status < 200:
                data = rest
                continue
            break
        hdrs = {l.split(":", 1)[0].strip().lower(): l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
        return _CurlResponse(status, hdrs, rest)

    # --- endpoints -------------------------------------------------------
    def app_info(self):
        return self._request("GET", "app/info")

    def stories_list(self, limit: int = 20, offset: int = 0, keyword: str = ""):
        return self._request("GET", "stories/list", {"limit": limit, "offset": offset, "keyword": keyword})

    def story_detail(self, story_id: str):
        return self._request("GET", f"stories/{story_id}/detail")

    def trending(self, period: str = "day", limit: int = 20, offset: int = 0):
        return self._request("GET", f"stories/trending/{period}", {"limit": limit, "offset": offset})

    def tags(self):
        return self._request("GET", "tags/")

    def chapter_numbers(self, story_id: str, start: int, end: int):
        return self._request(
            "GET", "chapters/numbers", {"story_id": story_id, "start": start, "end": end}
        )

    def chapter_detail(self, story_id: str, number: int):
        return self._request(
            "GET", "chapters/detail", {"story_id": story_id, "number": number}, signed=True
        )

    def close(self):
        self.http.close()


def diagnose(write_to: str | None = None) -> None:
    """In (va luu) thong tin de tim nguyen nhan 403. Dung: TYT-Crawl.exe --diagnose"""
    import platform
    import ssl

    lines: list[str] = []

    def out(msg: str = "") -> None:
        print(msg, flush=True)
        lines.append(msg)

    out(f"He dieu hanh : {platform.platform()}")
    out(f"Python       : {platform.python_version()} ({ssl.OPENSSL_VERSION}), dong goi={getattr(sys, 'frozen', False)}")
    out(f"curl         : {CURL or 'KHONG TIM THAY trong PATH'}")
    if CURL:
        try:
            ver = subprocess.run([CURL, "--version"], capture_output=True, timeout=15,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out("curl version : " + ver.stdout.decode("utf-8", "replace").splitlines()[0])
        except (OSError, subprocess.SubprocessError, IndexError) as exc:
            out(f"curl version : LOI {exc}")
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy"):
        if os.environ.get(var):
            out(f"proxy        : {var}={os.environ[var]}")

    client = TytClient()
    url = client.base_url + "app/info"

    def probe(label: str, fn) -> None:
        try:
            r = fn()
            body = r.text[:150].replace("\n", " ")
            out(f"[{label}] HTTP {r.status_code}  server={r.headers.get('server')}  "
                f"cf-mitigated={r.headers.get('cf-mitigated')}  body={body!r}")
        except Exception as exc:  # noqa: BLE001
            out(f"[{label}] LOI {type(exc).__name__}: {exc}")

    out("\n-- Goi app/info --")
    probe("python/httpx", lambda: client.http.get(url))
    if CURL:
        probe("curl", lambda: client._curl("GET", url, {}, None))

    out("\n-- Chay that qua TytClient (tu dong chuyen sang curl neu can) --")
    for label, call in (
        ("dang ky thiet bi", client.ensure_device),
        ("danh sach truyen", lambda: client.stories_list(limit=1)),
        ("tai chuong 1 (co chu ky)", lambda: client.chapter_detail(
            client.stories_list(limit=1)["data"][0]["id"], 1)),
    ):
        try:
            call()
            out(f"[{label}] OK  (transport hien tai: {'curl' if client._use_curl else 'python'})")
        except Exception as exc:  # noqa: BLE001
            out(f"[{label}] LOI {exc}")
    out(f"lech gio so voi server: {client._drift:+.1f}s  (qua 300s se bi ts_drift)")
    client.close()

    if write_to:
        try:
            with open(write_to, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print(f"\nDa luu ket qua vao: {write_to}  (gui file nay cho nguoi ho tro)")
        except OSError as exc:
            print(f"\nKhong luu duoc file: {exc}")


def _show(label: str, data) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:1200])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = TytClient()
    print(f"uuid: {client.client_uuid}")

    try:
        client.ensure_device()
        print(f"device_id: {client.device_id}")
        print(f"device_secret: {len(client.device_secret)} bytes")
    except TytError as exc:
        print("devices/session loi:", exc, exc.payload)
        return 1

    story_id = None
    try:
        data = client.stories_list(limit=2, offset=0)
        lst = data.get("data") or []
        if isinstance(lst, dict):
            lst = lst.get("stories") or lst.get("list") or []
        print(f"\nstories/list -> {len(lst)} truyen")
        if lst:
            story_id = lst[0].get("id")
            print("story_id:", story_id, "|", lst[0].get("title"))
    except TytError as exc:
        print("stories/list loi:", exc)

    if story_id:
        for label, call in (
            ("chapters/numbers 1..20", lambda: client.chapter_numbers(story_id, 1, 20)),
            ("chapters/detail #1", lambda: client.chapter_detail(story_id, 1)),
        ):
            try:
                _show(label, call())
            except TytError as exc:
                print(f"\n{label} loi:", exc, "| payload:", str(exc.payload)[:300])

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
