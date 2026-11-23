<#
  Bird Photo Editor - one-time setup for Windows 11 (no administrator rights).

  What it does:
    1. Finds Python 3.11, 3.12 or 3.13 (offers to install 3.12 for you with
       winget, per-user, if none is found).
    2. Creates a private Python environment in
       %LOCALAPPDATA%\BirdPhotoEditor\runtime\venv
    3. Installs the pinned, prebuilt packages from backend\requirements.txt
       (no compiler is used: --only-binary=:all:).
    4. Optionally creates a desktop shortcut.

  Safe to run again (e.g. after updating the app).
#>
$ErrorActionPreference = "Stop"
$AppRoot   = Split-Path -Parent $PSScriptRoot
$Backend   = Join-Path $AppRoot "backend"
$Req       = Join-Path $Backend "requirements.txt"
$DataRoot  = Join-Path $env:LOCALAPPDATA "BirdPhotoEditor"
$VenvDir   = Join-Path $DataRoot "runtime\venv"
$VenvPy    = Join-Path $VenvDir "Scripts\python.exe"

function Write-Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) {
    Write-Host ""
    Write-Host "SETUP FAILED: $msg" -ForegroundColor Red
    Write-Host ""
    exit 1
}

function Get-PythonVersion($exe, $extraArgs) {
    $ErrorActionPreference = "Continue"     # see note at the tkinter check
    try {
        $out = & $exe @extraArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -match '^\d+\.\d+$') { return $out.Trim() }
    } catch { }
    return $null
}

function Find-Python {
    $supported = @("3.12", "3.13", "3.11")
    # 1) The Python launcher (installed by python.org installers)
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in $supported) {
            $ver = Get-PythonVersion "py" @("-$v")
            if ($ver -eq $v) { return @{ Exe = "py"; Args = @("-$v"); Version = $v } }
        }
    }
    # 2) python.exe on PATH (ignore the Microsoft Store placeholder, which prints nothing)
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            $ver = Get-PythonVersion $cmd.Source @()
            if ($ver -and ($supported -contains $ver)) { return @{ Exe = $cmd.Source; Args = @(); Version = $ver } }
        }
    }
    return $null
}

Write-Host "Bird Photo Editor setup" -ForegroundColor Green
Write-Host "App folder : $AppRoot"
Write-Host "Data folder: $DataRoot"

if (-not (Test-Path $Req)) { Fail "Cannot find $Req. Run this script from the extracted app folder." }
if (-not (Test-Path (Join-Path $Backend "birdedit\web\index.html"))) {
    Fail "The web interface files are missing (backend\birdedit\web). Download the app again."
}

Write-Step "Looking for Python 3.11 - 3.13"
$py = Find-Python
if (-not $py) {
    Write-Host "No suitable Python was found." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "Install Python 3.12 now for your user account with winget? (Y/N)"
        if ($answer -match '^[Yy]') {
            winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
            # Make the new install visible to this session.
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
            $py = Find-Python
        }
    }
    if (-not $py) {
        Fail ("Please install Python 3.12 from https://www.python.org/downloads/windows/ " +
              "(keep 'tcl/tk and IDLE' ticked), then run Setup again.")
    }
}
Write-Host "Using Python $($py.Version) ($($py.Exe) $($py.Args -join ' '))"

Write-Step "Creating the private Python environment"
New-Item -ItemType Directory -Force -Path (Split-Path $VenvDir) | Out-Null
if (Test-Path $VenvPy) {
    $existing = Get-PythonVersion $VenvPy @()
    if ($existing -ne $py.Version) {
        Write-Host "Replacing environment built for Python $existing"
        Remove-Item -Recurse -Force $VenvDir
    }
}
if (-not (Test-Path $VenvPy)) {
    & $py.Exe @($py.Args) -m venv "$VenvDir"
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the Python environment in $VenvDir" }
}

Write-Step "Installing packages (prebuilt wheels only; this can take a few minutes)"
& $VenvPy -m pip install --disable-pip-version-check --only-binary=:all: --no-binary=proxy_tools -r "$Req"
if ($LASTEXITCODE -ne 0) {
    Fail ("Package installation failed. Check your internet connection and try again. " +
          "If it mentions a missing wheel, your Python version may be unsupported (use 3.12).")
}

Write-Step "Checking the installation"
Push-Location $Backend
try {
    & $VenvPy -c "import rawpy, numpy, cv2, PIL, fastapi, birdedit; print('LibRaw', '.'.join(map(str, rawpy.libraw_version)))"
    if ($LASTEXITCODE -ne 0) { Fail "The packages were installed but could not be loaded." }
} finally { Pop-Location }
# In Windows PowerShell 5.1, redirected stderr from a native program becomes an
# error record, which would stop the script under ErrorActionPreference=Stop.
$tkOk = $false
try {
    $ErrorActionPreference = "Continue"
    & $VenvPy -c "import tkinter" 2>$null | Out-Null
    $tkOk = ($LASTEXITCODE -eq 0)
} catch { $tkOk = $false } finally { $ErrorActionPreference = "Stop" }
if (-not $tkOk) {
    Write-Host ("Note: Python's 'tcl/tk' component is missing, so the Windows file picker cannot be shown. " +
                "You can still import by dragging photos into the window. To fix, re-run the Python installer, " +
                "choose Modify, and tick 'tcl/tk and IDLE'.") -ForegroundColor Yellow
}

$answer = Read-Host "Create a desktop shortcut? (Y/N)"
if ($answer -match '^[Yy]') {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $desktop "Bird Photo Editor.lnk"))
    $lnk.TargetPath = Join-Path $AppRoot "Start Bird Photo Editor.bat"
    $lnk.WorkingDirectory = $AppRoot
    $lnk.Description = "Bird Photo Editor (runs locally)"
    $lnk.Save()
    Write-Host "Shortcut created on your desktop."
}

Write-Host ""
Write-Host "Setup complete. Double-click 'Start Bird Photo Editor.bat' to begin." -ForegroundColor Green
