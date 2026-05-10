$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = "C:\Users\sunwa\AppData\Local\Programs\Python\Python310\python.exe"
$port = 18080
$logDir = Join-Path $root "logs"
$logFile = Join-Path $logDir "streamlit-startup.log"
$stdoutLog = Join-Path $logDir "streamlit-stdout.log"
$stderrLog = Join-Path $logDir "streamlit-stderr.log"
if (-not (Test-Path $python)) {
    throw "Python not found: $python"
}

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

# Avoid launching a second copy when the Streamlit port is already in use.
$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    "[{0}] Streamlit is already listening on port {1}." -f (Get-Date -Format s), $port | Out-File -FilePath $logFile -Append -Encoding utf8
    exit 0
}

"[{0}] Starting Streamlit on port {1} with {2}" -f (Get-Date -Format s), $port, $python | Out-File -FilePath $logFile -Append -Encoding utf8
$process = Start-Process `
    -FilePath $python `
    -ArgumentList @(
        "-m",
        "streamlit",
        "run",
        "$root\streamlit_app.py",
        "--server.headless",
        "true",
        "--server.port",
        "$port"
    ) `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

"[{0}] Streamlit started with PID {1}." -f (Get-Date -Format s), $process.Id | Out-File -FilePath $logFile -Append -Encoding utf8
