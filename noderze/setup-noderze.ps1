# One-time setup, and the same script for every future update.
# Installs packages, loads new research (your own data is kept), builds the fast production
# version of the UI, and creates Desktop, Start menu and sign-in shortcuts.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$here = $PSScriptRoot
Write-Host ""
Write-Host "Setting up Noderze in $root" -ForegroundColor Magenta

$python = Join-Path $root "backend\.venv\Scripts\python.exe"
Write-Host "1/5 Stopping anything already running..."
& $python (Join-Path $here "noderze_launcher.py") --stop quiet 2>$null

Write-Host "2/5 Updating backend packages..."
if (-not (Test-Path $python)) { throw "Could not find $python. The backend environment from the first setup is missing." }
& $python -m pip install --quiet --disable-pip-version-check -r (Join-Path $root "backend\requirements.txt")

Write-Host "3/5 Loading new companies and research (your applications, notes and resume are kept)..."
Push-Location (Join-Path $root "backend")
& $python "scripts\seed_db.py"
Pop-Location

Write-Host "4/5 Installing and building the app (two to four minutes)..."
Push-Location (Join-Path $root "frontend")
& npm.cmd install --no-audit --no-fund --loglevel=error
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed" }
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "The app build failed. Send a screenshot of the red text above." }
Pop-Location

Write-Host "5/5 Creating shortcuts and opening Noderze..."
& $python (Join-Path $here "noderze_launcher.py") --install
