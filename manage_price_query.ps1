# 烟草价格查询应用 - 综合管理脚本
param(
    [ValidateSet("start", "stop", "restart", "status", "install", "uninstall", "help")]
    [string]$Command = "help"
)

# 配置
$appName = "TobaccoPriceQuery"
$port = 8502
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $scriptPath "logs"
$logFile = Join-Path $logDir "price_query_app.log"

# 创建日志目录
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# 函数：写日志
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    Add-Content -Path $logFile -Value $logMessage
    Write-Host $logMessage
}

# 函数：检查进程是否在运行
function Get-AppProcess {
    return Get-Process -Name "streamlit" -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowTitle -like "*price_query_app*" -or
        (Get-WmiObject -Class Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like "*price_query_app*" })
    }
}

# 函数：检查端口是否在使用
function Test-PortInUse {
    param([int]$Port)
    try {
        $listener = [System.Net.Sockets.TcpListener]::new("127.0.0.1", $Port)
        $listener.Start()
        $listener.Stop()
        return $false
    } catch {
        return $true
    }
}

# 主菜单
function Show-Menu {
    Write-Host ""
    Write-Host "==============================================" -ForegroundColor Cyan
    Write-Host "   烟草价格查询应用 - 管理工具" -ForegroundColor Cyan
    Write-Host "==============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "当前状态:" -ForegroundColor Yellow
    $process = Get-AppProcess
    $portInUse = Test-PortInUse -Port $port
    
    if ($process) {
        Write-Host "  ✓ 应用正在运行 (PID: $($process.Id))" -ForegroundColor Green
    } else {
        Write-Host "  ✗ 应用未运行" -ForegroundColor Red
    }
    
    if ($portInUse) {
        Write-Host "  ✓ 端口 $port 被占用" -ForegroundColor Yellow
    } else {
        Write-Host "  - 端口 $port 可用" -ForegroundColor Gray
    }
    
    Write-Host ""
    Write-Host "可用命令:" -ForegroundColor Cyan
    Write-Host "  start     - 启动价格查询应用" -ForegroundColor White
    Write-Host "  stop      - 停止价格查询应用" -ForegroundColor White
    Write-Host "  restart   - 重启价格查询应用" -ForegroundColor White
    Write-Host "  status    - 查看运行状态" -ForegroundColor White
    Write-Host "  install   - 安装开机自启动" -ForegroundColor White
    Write-Host "  uninstall - 卸载开机自启动" -ForegroundColor White
    Write-Host "  help      - 显示帮助信息" -ForegroundColor White
    Write-Host ""
    Write-Host "使用方法:" -ForegroundColor Gray
    Write-Host "  .\manage_price_query.ps1 start" -ForegroundColor Gray
    Write-Host "  .\manage_price_query.ps1 stop" -ForegroundColor Gray
    Write-Host ""
}

# 启动应用
function Start-App {
    Write-Host ""
    Write-Host "正在启动价格查询应用..." -ForegroundColor Yellow
    Write-Log "正在启动应用..."
    
    $process = Get-AppProcess
    if ($process) {
        Write-Host "应用已在运行 (PID: $($process.Id))" -ForegroundColor Yellow
        return
    }
    
    $portInUse = Test-PortInUse -Port $port
    if ($portInUse) {
        Write-Host "警告: 端口 $port 已被占用，尝试继续..." -ForegroundColor Yellow
        Write-Log "警告: 端口 $port 已被占用" "WARN"
    }
    
    try {
        $batPath = Join-Path $scriptPath "start_price_query.bat"
        $workingDir = $scriptPath
        
        # 使用隐藏窗口启动
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "cmd.exe"
        $psi.Arguments = "/c `"$batPath`""
        $psi.WorkingDirectory = $workingDir
        $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Minimized
        
        $newProcess = [System.Diagnostics.Process]::Start($psi)
        
        Start-Sleep -Seconds 3
        
        Write-Host ""
        Write-Host "==============================================" -ForegroundColor Cyan
        Write-Host "✓ 应用启动成功！" -ForegroundColor Green
        Write-Host "==============================================" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "访问地址:" -ForegroundColor Cyan
        Write-Host "  本地: http://localhost:$port" -ForegroundColor White
        Write-Host "  局域网: http://$([System.Net.Dns]::GetHostName()):$port" -ForegroundColor White
        Write-Host ""
        Write-Host "日志文件: $logFile" -ForegroundColor Gray
        Write-Host ""
        
        Write-Log "应用启动成功"
    } catch {
        Write-Host "✗ 启动失败: $_" -ForegroundColor Red
        Write-Log "启动失败: $_" "ERROR"
    }
}

# 停止应用
function Stop-App {
    Write-Host ""
    Write-Host "正在停止价格查询应用..." -ForegroundColor Yellow
    Write-Log "正在停止应用..."
    
    $process = Get-AppProcess
    if (-not $process) {
        Write-Host "应用未运行" -ForegroundColor Gray
        return
    }
    
    try {
        # 停止相关的 streamlit 进程
        $allStreamlit = Get-Process -Name "streamlit" -ErrorAction SilentlyContinue
        foreach ($p in $allStreamlit) {
            try {
                $wmi = Get-WmiObject -Class Win32_Process -Filter "ProcessId=$($p.Id)" -ErrorAction SilentlyContinue
                if ($wmi -and $wmi.CommandLine -like "*price_query_app*") {
                    Write-Host "停止进程: $($p.Id)" -ForegroundColor Gray
                    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }
        
        # 等待进程结束
        Start-Sleep -Seconds 2
        
        Write-Host "✓ 应用已停止" -ForegroundColor Green
        Write-Log "应用已停止"
    } catch {
        Write-Host "✗ 停止失败: $_" -ForegroundColor Red
        Write-Log "停止失败: $_" "ERROR"
    }
}

# 查看状态
function Show-Status {
    Write-Host ""
    Write-Host "==============================================" -ForegroundColor Cyan
    Write-Host "运行状态" -ForegroundColor Cyan
    Write-Host "==============================================" -ForegroundColor Cyan
    Write-Host ""
    
    $process = Get-AppProcess
    $portInUse = Test-PortInUse -Port $port
    
    if ($process) {
        Write-Host "应用状态:" -ForegroundColor Green
        Write-Host "  运行中" -ForegroundColor Green
        Write-Host "  PID: $($process.Id)" -ForegroundColor White
        Write-Host "  启动时间: $($process.StartTime)" -ForegroundColor White
    } else {
        Write-Host "应用状态:" -ForegroundColor Red
        Write-Host "  未运行" -ForegroundColor Red
    }
    
    Write-Host ""
    Write-Host "端口状态:" -ForegroundColor Cyan
    if ($portInUse) {
        Write-Host "  端口 $port: 被占用" -ForegroundColor Yellow
    } else {
        Write-Host "  端口 $port: 可用" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "访问地址:" -ForegroundColor Cyan
    Write-Host "  本地: http://localhost:$port" -ForegroundColor White
    Write-Host "  局域网: http://$([System.Net.Dns]::GetHostName()):$port" -ForegroundColor White
    
    # 检查计划任务
    $taskName = "烟草价格查询应用_开机自启动"
    $taskExists = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "开机自启动:" -ForegroundColor Cyan
    if ($taskExists) {
        Write-Host "  已安装" -ForegroundColor Green
    } else {
        Write-Host "  未安装" -ForegroundColor Gray
    }
    
    Write-Host ""
}

# 主逻辑
switch ($Command) {
    "start" { Start-App }
    "stop" { Stop-App }
    "restart" {
        Stop-App
        Start-Sleep -Seconds 2
        Start-App
    }
    "status" { Show-Status }
    "install" {
        $installScript = Join-Path $scriptPath "install_price_query_autostart.ps1"
        & $installScript
    }
    "uninstall" {
        $installScript = Join-Path $scriptPath "install_price_query_autostart.ps1"
        & $installScript -Uninstall
    }
    "help" { Show-Menu }
    default { Show-Menu }
}

# 如果没有参数，显示菜单
if (-not $PSBoundParameters.ContainsKey("Command")) {
    Show-Menu
}
