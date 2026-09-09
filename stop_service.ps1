$serviceName = "TobaccoToolService"

$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if (-not $service) {
    Write-Host "Service '$serviceName' does not exist"
    exit 1
}

if ($service.Status -eq 'Stopped') {
    Write-Host "Service '$serviceName' is already stopped"
    exit 0
}

Stop-Service -Name $serviceName -Force
Start-Sleep -Seconds 2

$service = Get-Service -Name $serviceName
if ($service.Status -eq 'Stopped') {
    Write-Host "Service '$serviceName' stopped successfully!"
} else {
    Write-Host "Service '$serviceName' failed to stop. Status: $($service.Status)"
}