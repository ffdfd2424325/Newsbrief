Param(
  [string]$Token = ""
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[setup] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[setup] $msg" -ForegroundColor Yellow }
function Write-Ok($msg) { Write-Host "[setup] $msg" -ForegroundColor Green }

# 1) Ensure venv
$venv = ".venv"
if (-not (Test-Path $venv)) {
  Write-Info "Создаю виртуальное окружение $venv"
  python -m venv $venv
}

$py = Join-Path $venv "Scripts/python.exe"
if (-not (Test-Path $py)) {
  throw "Не найден интерпретатор venv: $py"
}

# 2) Install deps
Write-Info "Обновляю pip"
& $py -m pip install --upgrade pip

Write-Info "Устанавливаю зависимости из requirements.txt"
& $py -m pip install -r requirements.txt

# 3) Resolve httpx/PTB compatibility (PTB 20.7 -> httpx ~= 0.25.2)
Write-Info "Привожу httpx к версии 0.25.2 для совместимости с python-telegram-bot"
& $py -m pip install httpx==0.25.2 --force-reinstall

# 4) Ensure python-telegram-bot is installed
Write-Info "Проверяю установку python-telegram-bot"
& $py -m pip install python-telegram-bot==20.7

# 5) Setup .env
$envPath = ".env"
if (-not (Test-Path $envPath)) {
  if (Test-Path ".env.example") {
    Write-Info "Создаю .env из .env.example"
    Copy-Item ".env.example" $envPath
  } else {
    Write-Info "Создаю пустой .env"
    New-Item -ItemType File -Path $envPath | Out-Null
  }
}

# Helper to set or update key in .env
function Set-EnvKey([string]$path, [string]$key, [string]$value) {
  $content = Get-Content $path -Raw -ErrorAction SilentlyContinue
  if ($null -eq $content) { $content = "" }
  $pattern = "(?m)^" + [Regex]::Escape($key) + "=.*$"
  if ($value -eq "") {
    return
  }
  if ($content -match $pattern) {
    $new = [Regex]::Replace($content, $pattern, "$key=$value")
  } else {
    if ($content.Length -gt 0 -and -not $content.EndsWith("`n")) { $content += "`n" }
    $new = $content + "$key=$value`n"
  }
  Set-Content -Path $path -Value $new -Encoding UTF8
}

# Set API_BASE default if missing
$apiBase = $Env:API_BASE
if ([string]::IsNullOrWhiteSpace($apiBase)) { $apiBase = "http://127.0.0.1:8000" }
Set-EnvKey $envPath "API_BASE" $apiBase

# Set token from param or current session env
if (-not [string]::IsNullOrWhiteSpace($Token)) {
  Set-EnvKey $envPath "TELEGRAM_BOT_TOKEN" $Token
} elseif (-not [string]::IsNullOrWhiteSpace($Env:TELEGRAM_BOT_TOKEN)) {
  Set-EnvKey $envPath "TELEGRAM_BOT_TOKEN" $Env:TELEGRAM_BOT_TOKEN
} else {
  Write-Warn "TELEGRAM_BOT_TOKEN не задан. Добавьте его в .env вручную или перезапустите скрипт с параметром -Token."}

Write-Ok "Готово. Запускайте сервер и бота следующими командами:"
Write-Host "`nТерминал 1 (API):" -ForegroundColor Gray
Write-Host ". .\.venv\Scripts\Activate.ps1`nuvicorn app.main:app --host 127.0.0.1 --port 8000" -ForegroundColor White
Write-Host "`nТерминал 2 (Bot):" -ForegroundColor Gray
Write-Host ". .\.venv\Scripts\Activate.ps1`npython -m app.bot" -ForegroundColor White
