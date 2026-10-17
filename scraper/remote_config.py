"""Lay gia tri Remote Config thuc te cua app TYT qua REST API (khong can dien thoai).

Firebase project: simbo-app (lay tu res/values/strings.xml cua APK).
"""

from __future__ import annotations

import base64
import json
import os
import secrets

import httpx

PROJECT_ID = "simbo-app"
APP_ID = "1:542716458455:android:5b6a876594716acfa98792"
API_KEY = "AIzaSyDKa03LlVaSy30_ehmuODdDIWenUam7KJI"
PACKAGE = "com.tytno"

URL = f"https://firebaseremoteconfig.googleapis.com/v1/projects/{PROJECT_ID}/namespaces/firebase:fetch"


def make_instance_id() -> str:
    """App instance ID dang 22 ky tu base64url."""
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")[:22]


def main() -> int:
    body = {
        "app_instance_id": make_instance_id(),
        "app_id": APP_ID,
        "package_name": PACKAGE,
        "platform_version": "34",
        "app_version": "147",
        "language_code": "vi",
        "sdk_version": "22.1.2",
        "time_zone": "Asia/Bangkok",
    }
    resp = httpx.post(
        URL,
        params={"key": API_KEY},
        json=body,
        headers={"X-Goog-Api-Key": API_KEY, "Content-Type": "application/json"},
        timeout=30.0,
    )
    print("HTTP", resp.status_code)
    if resp.status_code != 200:
        print(resp.text[:1000])
        return 1

    data = resp.json()
    entries = data.get("entries", {})
    print(f"\n== {len(entries)} entries ==")
    for key in sorted(entries):
        print(f"  {key} = {entries[key]}")

    cfg = entries.get("apiBaseUrl") or entries.get("apiTataUrl")
    if cfg:
        print(f"\n>>> apiBaseUrl = {cfg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
