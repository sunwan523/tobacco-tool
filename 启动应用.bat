@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "LANG=zh_CN.UTF-8"
set "LC_ALL=zh_CN.UTF-8"
set "PYTHONUNBUFFERED=1"
cd /d "d:\codex\tobacco-tool"
echo ====================
echo   Starting App...
echo ====================
echo Local: http://localhost:8501
echo Network: http://192.168.100.200:8501
echo ====================
echo Press Ctrl+C to stop
echo ====================
echo.
"C:\Users\sunwa\AppData\Local\Programs\Python\Python310\python.exe" -m streamlit run streamlit_app.py --server.port 8501