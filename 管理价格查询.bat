@echo off
chcp 65001 >nul
title 烟草价格查询应用 - 管理工具

echo ==============================================
echo    烟草价格查询应用 - 管理工具
echo ==============================================
echo.
echo 请选择操作:
echo.
echo   [1] 启动应用
echo   [2] 停止应用
echo   [3] 重启应用
echo   [4] 查看状态
echo   [5] 安装开机自启动
echo   [6] 卸载开机自启动
echo   [0] 退出
echo.
echo ==============================================
echo.

set /p choice=请输入选项 (0-6): 

if "%choice%"=="1" goto start
if "%choice%"=="2" goto stop
if "%choice%"=="3" goto restart
if "%choice%"=="4" goto status
if "%choice%"=="5" goto install
if "%choice%"=="6" goto uninstall
if "%choice%"=="0" goto end

echo 无效选项，请重新选择
pause
goto start

:start
cls
echo 正在启动价格查询应用...
powershell -ExecutionPolicy Bypass -File "%~dp0manage_price_query.ps1" start
echo.
echo 按任意键返回菜单...
pause >nul
goto start

:stop
cls
echo 正在停止价格查询应用...
powershell -ExecutionPolicy Bypass -File "%~dp0manage_price_query.ps1" stop
echo.
echo 按任意键返回菜单...
pause >nul
goto start

:restart
cls
echo 正在重启价格查询应用...
powershell -ExecutionPolicy Bypass -File "%~dp0manage_price_query.ps1" restart
echo.
echo 按任意键返回菜单...
pause >nul
goto start

:status
cls
powershell -ExecutionPolicy Bypass -File "%~dp0manage_price_query.ps1" status
echo.
echo 按任意键返回菜单...
pause >nul
goto start

:install
cls
echo 正在安装开机自启动...
echo 请在弹出的PowerShell窗口中完成操作
echo.
powershell -NoExit -ExecutionPolicy Bypass -Command "& {Start-Process powershell -ArgumentList '-NoExit -ExecutionPolicy Bypass -File \"%~dp0install_price_query_autostart.ps1\"' -Verb RunAs}"
echo.
echo 按任意键返回菜单...
pause >nul
goto start

:uninstall
cls
echo 正在卸载开机自启动...
echo 请在弹出的PowerShell窗口中完成操作
echo.
powershell -NoExit -ExecutionPolicy Bypass -Command "& {Start-Process powershell -ArgumentList '-NoExit -ExecutionPolicy Bypass -File \"%~dp0install_price_query_autostart.ps1\" -Uninstall' -Verb RunAs}"
echo.
echo 按任意键返回菜单...
pause >nul
goto start

:end
cls
echo 谢谢使用！
timeout /t 1 >nul
