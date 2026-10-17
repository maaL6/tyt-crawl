@echo off
REM Chay mitmproxy + addon bat traffic. Chay duoc tu BAT KY thu muc nao.
set "SCRIPT_DIR=%~dp0"
echo [tyt-crawl] addon: %SCRIPT_DIR%mitm\addon.py
echo [tyt-crawl] PC IP  : 192.168.1.3   port 8080
echo [tyt-crawl] Cau hinh proxy tren dien thoai -> Host: 192.168.1.3  Port: 8080
echo.
mitmdump -s "%SCRIPT_DIR%mitm\addon.py" --listen-host 0.0.0.0 --listen-port 8080
