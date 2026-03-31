$ErrorActionPreference = "Stop"

Write-Host "AITree - one-line installer for Windows" -ForegroundColor Cyan

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "Python is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

Write-Host "Installing AITree via pip..."
python -m pip install --upgrade paracci-aitree --quiet

$pythonDir = Split-Path $pythonCmd.Source
$sysScripts = Join-Path $pythonDir "Scripts"
$userBase = (python -m site --user-base).Trim()
$userScripts = Join-Path $userBase "Scripts"

$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if (-not $userPath) { $userPath = "" }
$modified = $false

foreach ($dir in @($userScripts, $sysScripts)) {
    if (Test-Path $dir) {
        if ($userPath -notlike "*$dir*") {
            $userPath = "$userPath;$dir"
            $env:PATH = "$env:PATH;$dir"
            $modified = $true
            Write-Host "Added $dir to your Windows PATH so the aitree command works directly!" -ForegroundColor Yellow
        }
    }
}

if ($modified) {
    [Environment]::SetEnvironmentVariable("PATH", $userPath, "User")
}

Write-Host "`nAITree installed successfully!" -ForegroundColor Green
Write-Host "Quick start: aitree ."
