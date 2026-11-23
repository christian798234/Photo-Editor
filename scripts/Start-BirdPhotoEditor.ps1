<#
  Starts Bird Photo Editor: runs the local server (127.0.0.1 only) and opens
  the default browser. Close this window to quit the app.
  Port selection, "already running" detection and startup error messages are
  handled by the Python program itself (python -m birdedit).
#>
$ErrorActionPreference = "Stop"
$AppRoot  = Split-Path -Parent $PSScriptRoot
$Backend  = Join-Path $AppRoot "backend"
$VenvPy   = Join-Path $env:LOCALAPPDATA "BirdPhotoEditor\runtime\venv\Scripts\python.exe"

function Show-Error($text) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($text, "Bird Photo Editor", "OK", "Error") | Out-Null
}

$Host.UI.RawUI.WindowTitle = "Bird Photo Editor - keep this window open while you work"

if (-not (Test-Path $VenvPy)) {
    Show-Error "Bird Photo Editor is not set up yet.`n`nDouble-click 'Setup Bird Photo Editor.bat' first."
    exit 1
}
if (-not (Test-Path (Join-Path $Backend "birdedit\__main__.py"))) {
    Show-Error "The application files are incomplete. Please download the app again."
    exit 1
}

Set-Location $Backend
$env:PYTHONUTF8 = "1"
& $VenvPy -m birdedit @args
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host ""
    Write-Host "Bird Photo Editor stopped (code $code). Log files are in:" -ForegroundColor Yellow
    Write-Host "  $env:LOCALAPPDATA\BirdPhotoEditor\logs"
    Read-Host "Press Enter to close this window"
}
exit $code
