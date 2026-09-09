$serviceName = "TobaccoToolService"

$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if (-not $service) {
    Write-Host "Service '$serviceName' does not exist. Please run install_service.ps1 first."
    exit 1
}

if ($service.Status -eq 'Running') {
    Write-Host "Service '$serviceName' is already running"
    exit 0
}

Start-Service -Name $serviceName
Start-Sleep -Seconds 3

$service = Get-Service -Name $serviceName
if ($service.Status -eq 'Running') {
    Write-Host "Service '$serviceName' started successfully!"
    Write-Host "Access URL: http://localhost:8501"
} else {
    Write-Host "Service '$serviceName' failed to start. Status: $($service.Status)"
}