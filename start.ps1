# Run Cadence so a *normal* browser can open the demo URL.
# No proxy settings. No special Chrome flags.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python is not on PATH (need 3.11+)"
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install -q -e ".[proxy]"
$env:Path = "$(Resolve-Path .\.venv\Scripts);$env:Path"
& .\.venv\Scripts\cadence.exe demo @args
