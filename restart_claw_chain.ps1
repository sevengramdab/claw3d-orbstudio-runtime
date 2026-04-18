$ports = @(3000, 18789, 18890)

foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        $processId = $connection.OwningProcess
        if ($processId -gt 0) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-Host "Killed PID $processId on port $port"
        }
    }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

Start-Process -FilePath $pythonExe -ArgumentList "LAUNCH_CLAW3D.py" -WorkingDirectory $repoRoot
Write-Host "Restarted CLAW3D launcher from $repoRoot"