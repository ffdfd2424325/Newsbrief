Param(
  [int]$Port = 8000,
  [string]$Host = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Не найден $py. Сначала запустите scripts/setup.ps1" }

& $py -m uvicorn app.main:app --host $Host --port $Port
