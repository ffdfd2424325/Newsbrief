$ErrorActionPreference = "Stop"

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Venv python not found: $py. Run scripts/setup.ps1 first." }

# Check token presence in .env or environment
$hasToken = $false
if (Test-Path ".env") {
  $content = Get-Content .env -Raw
  if ($content -match '(?m)^TELEGRAM_BOT_TOKEN=.+$') { $hasToken = $true }
}
if (-not $hasToken -and -not [string]::IsNullOrWhiteSpace($Env:TELEGRAM_BOT_TOKEN)) {
  $hasToken = $true
}
if (-not $hasToken) {
  Write-Error "TELEGRAM_BOT_TOKEN is missing. Add it to .env or set as environment variable."
  exit 1
}

& $py -m app.bot
