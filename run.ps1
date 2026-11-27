# Start Scan Station v0: builds the viewer if needed, starts the backend,
# and opens http://127.0.0.1:8000 in your browser. Close this window to stop it.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Python environment missing. Run: py -3.12 -m venv .venv; .venv\Scripts\python.exe -m pip install -r backend\requirements.txt"
    exit 1
}
if (-not (Test-Path "viewer\dist\index.html")) {
    Write-Host "Building the viewer..."
    Push-Location viewer
    if (-not (Test-Path "node_modules")) { npm ci }
    npm run build
    Pop-Location
}

Start-Process "http://127.0.0.1:8000"
& ".venv\Scripts\python.exe" -m uvicorn scanstation.api:app --app-dir backend --host 127.0.0.1 --port 8000
