# 烟草价格查询应用启动脚本 (PowerShell)
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "   烟草价格查询应用启动脚本" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "正在启动价格查询应用 (端口: 8502)..." -ForegroundColor Yellow
Write-Host ""
Write-Host "应用将在以下地址访问:" -ForegroundColor Green
Write-Host "  本地访问: http://localhost:8502" -ForegroundColor Green
Write-Host ""
Write-Host "按 Ctrl+C 停止应用" -ForegroundColor Gray
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# 启动应用
streamlit run price_query_app.py --server.port 8502 --server.address 0.0.0.0
