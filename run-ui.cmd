@echo off
rem Chay web UI crawl TYT
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
start "" http://127.0.0.1:8787
python scraper\server.py
