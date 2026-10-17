# tyt-crawl — Crawl data từ app Android TYT

Crawl truyện (metadata + nội dung chương) từ app **TYT** (`com.tytno`) qua API công khai của app.

> Không cần login, không cần root, không cần MITM. API được lấy bằng cách **dịch ngược APK**
> (`jadx`) — nhanh và sạch hơn nhiều so với bắt traffic.

---

## Bắt đầu nhanh

### Cách 0 — Dùng bản `.exe` (không cần Python)

```powershell
build-exe.cmd          # build ra dist\ (chỉ cần chạy 1 lần)
```

Sau đó bấm đúp **`dist\TYT-Crawl.exe`** → trình duyệt tự mở `http://127.0.0.1:8787`.

| Sản phẩm | Mô tả |
|----------|-------|
| `dist\TYT-Crawl.exe` | Bản **1 file** (11.7 MB) — dễ gửi/chép, khởi động chậm hơn vài giây |
| `dist\TYT-Crawl-folder\` | Bản **thư mục** (24 MB) — khởi động nhanh, chép cả thư mục để dùng |
| `dist\TYT-Crawl-portable.zip` | Gói zip của bản 1 file (kèm `HUONG-DAN.txt`) |
| `dist\TYT-Crawl-folder.zip` | Gói zip của bản thư mục |

- Dữ liệu crawl lưu ở thư mục **`out` ngay cạnh file `.exe`** (kiểu portable).
- Lần đầu chạy, Windows SmartScreen có thể cảnh báo (exe không ký số): **More info → Run anyway**.
- Tùy chọn: `TYT-Crawl.exe --port 9000`, `--no-browser`, `--help`.
- Hướng dẫn cho người dùng cuối: `HUONG-DAN.txt`.

---

### Cách 1 — Giao diện web chạy bằng Python (dễ sửa, khuyên dùng khi phát triển)

```powershell
pip install -r requirements.txt
```

```powershell
run-ui.cmd            # hoặc: python scraper\server.py
```

Mở trình duyệt: **http://127.0.0.1:8787**

- Tab **Khám phá**: danh sách truyện mới (có ảnh bìa, số chương, tác giả)
- Tab **Tìm kiếm**: tìm theo tên truyện
- Tab **Đã tải**: các truyện đã crawl, xem/tải về
- Bấm vào 1 truyện → xem chi tiết, đặt **số chương / delay / retry**, bấm **Bắt đầu crawl**
- Theo dõi **thanh tiến độ + log** trực tiếp; có nút **Dừng**; chạy lại sẽ **resume**
- **Đọc truyện ngay trên web**: bấm chương đã tải ở danh sách để đọc (có Trước/Sau)
- Tải về **.txt** hoặc **.jsonl**

> Server chỉ listen `127.0.0.1` (máy cục bộ). Đổi cổng: `set TYT_UI_PORT=9000` rồi chạy lại.

### Cách 2 — Dòng lệnh

```powershell
# Liệt kê truyện mới
python scraper\crawl_story.py list 10

# Tìm truyện
python scraper\crawl_story.py search "linh vu"

# Crawl 1 truyện (ví dụ 5 chương đầu)
python scraper\crawl_story.py story 59b410cf6fc3330b5d062f53 --max-chapters 5

# Crawl full 1 truyện
python scraper\crawl_story.py story 59b410cf6fc3330b5d062f53
```

Kết quả nằm ở `out\<story_id>\`:

```
out/59b410cf6fc3330b5d062f53/
├─ story.json      # metadata truyện (title, author, tags, chapter_count, ...)
└─ chapters.jsonl  # mỗi dòng 1 chương: number, title, content_html, content (text)
```

---

## API contract (lấy từ dịch ngược APK)

### Host & header chung

| Mục | Giá trị |
|-----|---------|
| Base URL | `https://api.noveltyt.app/api/v2/` (Firebase Remote Config key `apiBaseUrl`) |
| `client-id` | `tytno` |
| `client-token` | `tytno` |
| `client-platform` | `android` |
| `client-version` | `147` |
| `client-language` | `vi` |
| `client-uuid` | UUID bất kỳ, tự sinh và lưu lại |
| `User-Agent` | **BẮT BUỘC** dạng `Dalvik/...` (xem bên dưới) |

> ⚠️ **`User-Agent` là mấu chốt.** Cloudflare của API chặn mọi request **không có UA** (trả
> `403 Just a moment...`). UA mặc định của `HttpURLConnection` (mà app dùng qua Volley) đi qua bình thường:
>
> ```http
> User-Agent: Dalvik/2.1.0 (Linux; U; Android 14; 2312DRA50I Build/UKQ1.231003.002)
> ```
>
> UA kiểu `curl`, `okhttp`, trình duyệt… đều **bị chặn 403**.

### Envelope trả về

```json
{"status": true, "data": ...}
{"status": false, "error_code": "..."}
```

### Endpoint công khai (không cần ký)

| Method | Endpoint | Tham số | Ghi chú |
|--------|----------|---------|---------|
| GET | `app/info` | – | thông tin phiên bản/ads |
| GET | `stories/list` | `limit`, `offset`, `keyword` | danh sách / tìm truyện |
| GET | `stories/{id}/detail` | – | chi tiết 1 truyện |
| GET | `chapters/numbers` | `story_id`, `start`, `end` | danh sách chương (number/title/id) |
| GET | `stories/trending/{day\|week\|month}` | `limit`, `offset` | bảng xếp hạng |
| GET | `stories/recommend/top`, `stories/gem/top`, `stories/filter`, `stories/author` | — | các mục khác |
| GET | `tags/` | – | danh sách thể loại |
| GET | `webtts/site-configs` | – | cấu hình web/TTS |

> Lưu ý `chapters/numbers`: `end` **không được vượt** `chapter_count` của truyện, nếu không server
> trả `HTTP 400`.

### Endpoint cần CHỮ KÝ

`chapters/detail` (`story_id`, `number`) trả về **nội dung chương** và **bắt buộc phải ký**;
nếu thiếu sẽ trả `error_code: "missing_sig"`.

### Đăng ký thiết bị (không cần login, không cần App Check)

```http
POST /api/v2/devices/session
body: {}
```

Trả về:

```json
{"status": true, "data": {"device_id": "...", "device_secret": "<base64url 32 byte>"}}
```

`device_secret` giải mã base64url ra **đúng 32 byte** — dùng làm **khoá HMAC**.

### Thuật toán ký (dịch từ `xh/l.java` + `dj/q.java`)

Header gửi kèm mỗi request cần ký:

```http
x-device-id: <device_id>
x-ts:        <unix giây>
x-nonce:     <UUID ngẫu nhiên>
x-sig:       <Base64(HMAC_SHA256(key=device_secret, msg=canonical))>
```

```
canonical = METHOD | PATH | QUERY | SHA256_HEX(body) | ts | nonce
```

- `METHOD`: `GET` / `POST` / …
- `PATH`: phần path của URL, ví dụ `/api/v2/chapters/detail`
- `QUERY`: chuỗi query đã **sắp xếp key tăng dần** (với GET/DELETE); `""` với POST/PATCH
- `SHA256_HEX(body)`: hash body JSON compact với POST; không có body thì dùng
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (SHA-256 của chuỗi rỗng)
- `ts`: unix **giây**
- `nonce`: UUID v4

> App đọc header `Date` của response để tự hiệu chỉnh lệch giờ (`x-ts`). Máy bạn lệch giờ nhiều
> có thể bị `error_code: ts_drift` — đồng bộ đồng hồ hệ thống nếu gặp.

Toàn bộ logic này đã được đóng gói trong `scraper/tyt_client.py` (class `TytClient`).

---

## Cấu trúc

```
tyt-crawl/
├─ README.md
├─ requirements.txt
├─ HUONG-DAN.txt          # hướng dẫn cho người dùng bản .exe
├─ build-exe.cmd          # build .exe (PyInstaller)
├─ run-ui.cmd             # chay web UI
├─ run-mitm.cmd           # (du phong) chay mitmproxy
├─ scraper/
│  ├─ tyt_client.py       # client API TYT: header, device session, ký HMAC
│  ├─ crawler.py          # loi crawl dung chung (retry/resume/progress)
│  ├─ crawl_story.py      # CLI: list / search / story
│  ├─ server.py           # web server cho UI
│  ├─ ui.html             # giao diện web
│  ├─ remote_config.py    # đọc trực tiếp Firebase Remote Config (lấy apiBaseUrl...)
│  ├─ probe_site.py       # (phụ) khảo sát website tytnovel.info
│  └─ probe_site2.py      # (phụ)
├─ tools/
│  ├─ find-app.ps1        # tìm app qua adb + pull APK
│  ├─ show_apis.py        # liệt kê API đã bắt (MITM, nếu dùng)
│  └─ jadx/               # jadx CLI
├─ mitm/addon.py          # addon mitmproxy (phương án dự phòng)
├─ apk/                   # (tự sinh) APK + code dịch ngược
├─ out/                   # (tự sinh) dữ liệu crawl
└─ dist/                  # (tự sinh) .exe + zip sau khi build
```

## Build lại .exe

```powershell
build-exe.cmd
```

Script tự cài PyInstaller nếu thiếu, rồi build **2 bản** (one-file + one-dir), copy
`HUONG-DAN.txt` và nén `.zip`. Bản one-file đóng gói `scraper/ui.html` qua `--add-data`;
khi chạy, code dùng `sys._MEIPASS` để tìm giao diện và `sys.executable` để chọn thư mục dữ liệu
(`out/` nằm cạnh `.exe`) — xem `app_dir()` / `resource_dir()` trong `scraper/tyt_client.py`.

---

## Ghi chú kỹ thuật (đã gặp)

- **Cloudflare 403**: nguyên nhân là **thiếu User-Agent**, không phải IP hay TLS fingerprint.
  `Dalvik/...` là UA hợp lệ.
- **Chương cần ký**: `stories/*` và `chapters/numbers` công khai; riêng `chapters/detail`
  (nội dung) cần `x-sig`. Đăng ký device công khai nên vẫn crawl được toàn bộ.
- **App Check của Firebase** chỉ áp cho endpoint auth (`devices/token`, `auth/*`), app vẫn
  chạy tiếp nếu App Check lỗi → các endpoint công khai ở trên không cần.
- **MITM không bắt được API**: app đọc dữ liệu từ cache (app offline) + Volley/`HttpURLConnection`.
  Việc bắt traffic không cần thiết vì đã có API từ APK.

---

## Phương án dự phòng — bắt traffic bằng mitmproxy

Chỉ dùng khi cần tìm hiểu thêm (endpoint mới, luồng auth…).

1. Chạy proxy: `run-mitm.cmd` (hoặc
   `mitmdump -s mitm\addon.py --listen-host 0.0.0.0 --listen-port 8080`).
2. Trên điện thoại: Wi-Fi → Proxy thủ công → `192.168.1.3:8080`.
3. Vào `http://mitm.it` trên điện thoại để cài cert.
4. `blocked.txt` = host app từ chối cert; `captured.jsonl` = request/response đọc được.

> Android 7+ không tin CA người dùng ở tầng app → cần patch APK (`user` cert) hoặc Frida.
> Xem git history/ghi chú cũ trong repo.

---

## Lưu ý pháp lý

Chỉ crawl dữ liệu công khai, tôn trọng ToS của app và quy định bản quyền. Cân nhắc rate limit
(`DELAY` trong `crawl_story.py`) để không gây tải cho server.
