@echo off
rem ============================================================
rem  Build TYT-Crawl.exe  ->  2 ban:
rem    [1] Onefile : dist\TYT-Crawl.exe          (1 file duy nhat)
rem    [2] Onedir  : dist\TYT-Crawl-folder\      (chay nhanh hon)
rem  Kem 2 goi .zip de gui/chep sang may khac.
rem ============================================================
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 ( echo [LOI] Khong tim thay python trong PATH & exit /b 1 )

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
  echo Dang cai PyInstaller...
  python -m pip install --upgrade pyinstaller || exit /b 1
)

set "UI=%~dp0scraper\ui.html"
set "COMMON=--noconfirm --clean --add-data "%UI%;scraper" --collect-all certifi --hidden-import httpx --hidden-import httpcore --hidden-import h11 --hidden-import anyio --hidden-import idna --hidden-import sniffio --exclude-module tkinter --exclude-module unittest --exclude-module pydoc --exclude-module test --console"

echo.
echo === [1/2] Build ban ONE-FILE ===
python -m PyInstaller %COMMON% --onefile --name TYT-Crawl --distpath dist --workpath build --specpath build scraper\server.py
if errorlevel 1 ( echo [LOI] Build onefile that bai & exit /b 1 )

echo.
echo === [2/2] Build ban ONE-DIR ===
python -m PyInstaller %COMMON% --onedir --name TYT-Crawl --distpath dist-2 --workpath build2 --specpath build2 scraper\server.py
if errorlevel 1 ( echo [LOI] Build onedir that bai & exit /b 1 )

rmdir /s /q "dist\TYT-Crawl-folder" 2>nul
move "dist-2\TYT-Crawl" "dist\TYT-Crawl-folder" >nul

echo.
echo === Dong goi ===
copy /y "HUONG-DAN.txt" "dist\HUONG-DAN.txt" >nul
copy /y "HUONG-DAN.txt" "dist\TYT-Crawl-folder\HUONG-DAN.txt" >nul
del /q "dist\TYT-Crawl-portable.zip" "dist\TYT-Crawl-folder.zip" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\TYT-Crawl.exe','dist\HUONG-DAN.txt' -DestinationPath 'dist\TYT-Crawl-portable.zip' -Force; Compress-Archive -Path 'dist\TYT-Crawl-folder' -DestinationPath 'dist\TYT-Crawl-folder.zip' -Force"

rmdir /s /q build build2 dist-2 2>nul

echo.
echo === XONG. Ket qua trong thu muc dist\ ===
dir /b dist
endlocal
