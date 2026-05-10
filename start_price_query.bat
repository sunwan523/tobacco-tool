@echo off
echo ==============================================
echo    烟草价格查询应用启动脚本
echo ==============================================
echo.
echo 正在启动价格查询应用 (端口: 8502)...
echo.
echo 应用将在以下地址访问:
echo   本地访问: http://localhost:8502
echo.
echo 按 Ctrl+C 停止应用
echo ==============================================
echo.

streamlit run price_query_app.py --server.port 8502 --server.address 0.0.0.0

pause
