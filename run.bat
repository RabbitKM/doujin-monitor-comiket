@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
py monitor.py >> logs\monitor.log 2>&1
