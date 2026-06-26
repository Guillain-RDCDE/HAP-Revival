# Build HapSync.exe — a standalone, double-click Windows GUI for the HAP-Z1ES / HAP-S1.
#
# Produces dist\HapSync.exe with no Python or dependency install needed on the target machine.
# Run from the repo root or from tools\ :  powershell -ExecutionPolicy Bypass -File tools\build_gui.ps1
#
# --onefile   : single self-contained .exe
# --windowed  : GUI app, no console window pops up behind it
# --collect-submodules smb : bundle all of pysmb (it imports submodules dynamically, so
#                            PyInstaller's static analysis misses them without this)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Installing build dependencies (pyinstaller, pysmb)..." -ForegroundColor Cyan
python -m pip install --quiet --upgrade pyinstaller pysmb
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "Building HapSync.exe..." -ForegroundColor Cyan
$icon = Join-Path $here "HapSync.ico"
python -m PyInstaller --noconfirm --onefile --windowed --name HapSync `
    --collect-submodules smb `
    --icon $icon `
    --add-data "$icon;." `
    (Join-Path $here "hap_gui.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$exe = Join-Path (Get-Location) "dist\HapSync.exe"
if (Test-Path $exe) {
    Write-Host "`nDone -> $exe" -ForegroundColor Green
    Write-Host "Double-click it, or keep it next to a hap_sync.json for shared settings."
} else {
    throw "Build reported success but dist\HapSync.exe is missing"
}
