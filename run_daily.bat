@echo off
cd /d C:\Dev\ai-news-bot
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
python -m src.main --mode daily 1>>logs\daily_%date:~0,4%%date:~5,2%%date:~8,2%.log 2>&1
