$serviceName = "TobaccoToolService"

$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if (-not $service) {
    Write-Host "Service '$serviceName' does not exist"
    exit 1
}

Write-Host "Stopping service..."
Stop-Service -Name $serviceName -Force
Start-Sleep -Seconds 2

Write-Host "Deleting service..."
sc.exe delete $serviceName

Write-Host "Service '$serviceName' uninstalled successfully!"