# 烟草价格查询应用 - 安装开机自启动脚本
param([switch]$Uninstall)

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "   烟草价格查询应用 - 开机自启动管理" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

$appName = "TobaccoPriceQuery"
$taskName = "烟草价格查询应用_开机自启动"
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath = Join-Path $scriptPath "start_price_query.bat"
$workingDir = $scriptPath

if ($Uninstall) {
    Write-Host "正在卸载开机自启动..." -ForegroundColor Yellow
    
    try {
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Host "✓ 成功删除计划任务: $taskName" -ForegroundColor Green
        } else {
            Write-Host "计划任务不存在，无需卸载" -ForegroundColor Gray
        }
        Write-Host ""
        Write-Host "卸载完成！" -ForegroundColor Green
    } catch {
        Write-Host "✗ 卸载失败: $_" -ForegroundColor Red
    }
    exit
}

Write-Host "正在安装开机自启动..." -ForegroundColor Yellow
Write-Host ""

# 检查启动脚本是否存在
if (-not (Test-Path $batPath)) {
    Write-Host "✗ 错误: 找不到启动脚本: $batPath" -ForegroundColor Red
    exit 1
}

try {
    # 创建任务动作
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`"" -WorkingDirectory $workingDir
    
    # 创建触发器 - 登录后启动
    $trigger = New-ScheduledTaskTrigger -AtLogon
    
    # 创建设置
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    
    # 设置运行权限
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
    
    # 检查任务是否已存在
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    
    if ($existingTask) {
        Write-Host "计划任务已存在，正在更新..." -ForegroundColor Yellow
        Set-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
        Write-Host "✓ 成功更新计划任务" -ForegroundColor Green
    } else {
        Write-Host "正在创建新的计划任务..." -ForegroundColor Yellow
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -TaskPath "\" -Description "烟草价格查询应用开机自启动" | Out-Null
        Write-Host "✓ 成功创建计划任务: $taskName" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "==============================================" -ForegroundColor Cyan
    Write-Host "安装完成！" -ForegroundColor Green
    Write-Host "==============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "下次登录时应用将自动启动。" -ForegroundColor Gray
    Write-Host ""
    Write-Host "要立即启动，请运行: .\start_price_query.bat" -ForegroundColor Gray
    Write-Host "要卸载自启动，请运行: .\install_price_query_autostart.ps1 -Uninstall" -ForegroundColor Gray
    Write-Host ""
    
} catch {
    Write-Host "✗ 安装失败: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "请尝试右键使用'以管理员身份运行'" -ForegroundColor Yellow
    exit 1
}
