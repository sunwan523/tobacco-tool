$serviceName = "TobaccoToolService"
$displayName = "Tobacco Tool Service"
$description = "Tobacco Tool Streamlit Application Service"
$pythonPath = "C:\Users\sunwa\AppData\Local\Programs\Python\Python310\python.exe"
$scriptPath = "d:\codex\tobacco-tool\streamlit_app.py"
$workingDir = "d:\codex\tobacco-tool"
$port = "8501"

$exePath = "C:\Windows\System32\cmd.exe"
$arguments = "/c cd /d `"$workingDir`" && `"$pythonPath`" -m streamlit run `"$scriptPath`" --server.port $port"

$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($service) {
    Write-Host "Service already exists, stopping and deleting..."
    Stop-Service -Name $serviceName -Force
    Start-Sleep -Seconds 2
    sc.exe delete $serviceName
    Start-Sleep -Seconds 2
}

New-Service -Name $serviceName -DisplayName $displayName -Description $description `
    -BinaryPathName "`"$exePath`" $arguments" -StartupType Automatic

Write-Host "Service '$displayName' installed successfully!"
Write-Host "Service Name: $serviceName"
Write-Host "Startup Type: Automatic"
Write-Host "Working Directory: $workingDir"
Write-Host "Access URL: http://localhost:$port"

Write-Host ""
Write-Host "Start Command: Start-Service $serviceName"
Write-Host "Stop Command: Stop-Service $serviceName"
Write-Host "Status Command: Get-Service $serviceName"