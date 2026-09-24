# start-crm.ps1 - launch the Ambifo CRM stack (engine, API, frontend) locally
# Usage:  powershell -ExecutionPolicy Bypass -File start-crm.ps1

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Logs = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

$EnginePort = 8081
$ApiPort = 8000
$FrontendPort = 5173
$Py = Join-Path $Root 'backend\.venv\Scripts\python.exe'

function Test-Port($Port) {
  return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Port($Port, $Seconds = 30) {
  for ($i = 0; $i -lt $Seconds; $i++) {
    if (Test-Port $Port) { return $true }
    Start-Sleep 1
  }
  return Test-Port $Port
}

Write-Host '== Ambifo CRM local launcher ==' -ForegroundColor Cyan

# ------------------------------------------------------------ 1. PostgreSQL
Write-Host '1) PostgreSQL...' -ForegroundColor Yellow
$pg = Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($pg) {
  if ($pg.Status -ne 'Running') { Start-Service -Name $pg.Name }
  Write-Host "   $($pg.Name): $($pg.Status)" -ForegroundColor Green
} else {
  Write-Host '   WARNING: no PostgreSQL service found - start it manually.' -ForegroundColor Red
}

# ------------------------------------------------------------ 2. Engine
Write-Host '2) Engine (Rust) ...' -ForegroundColor Yellow
$EngineExe = Join-Path $Root 'backend\engine\target\debug\ambifo_engine.exe'
if (Test-Port $EnginePort) {
  Write-Host '   already running on :8081' -ForegroundColor Green
} elseif (-not (Test-Path $EngineExe)) {
  Write-Host '   engine binary not found - building...' -ForegroundColor Red
  Push-Location (Join-Path $Root 'backend\engine')
  try { cargo build 2>&1 | Out-Null } finally { Pop-Location }
}
if (-not (Test-Path $EngineExe)) {
  Write-Host '   FAILED: could not build engine. Run `cargo build` in backend\engine manually.' -ForegroundColor Red
} elseif (-not (Test-Port $EnginePort)) {
  Start-Process -FilePath $EngineExe -WorkingDirectory (Split-Path $EngineExe) -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Logs 'engine.out.log') `
    -RedirectStandardError  (Join-Path $Logs 'engine.err.log')
  if (Wait-Port $EnginePort) { Write-Host '   started on :8081' -ForegroundColor Green }
  else { Write-Host '   WARNING: engine did not answer on :8081 - check logs\engine.err.log' -ForegroundColor Red }
}

# ------------------------------------------------------------ 2b. Email worker
Write-Host '2b) Email worker ...' -ForegroundColor Yellow
$WorkerProc = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like '*email_worker*' } | Select-Object -First 1
if ($WorkerProc) {
  Write-Host "   already running (pid $($WorkerProc.ProcessId))" -ForegroundColor Green
} else {
  Start-Process -FilePath $Py -ArgumentList '-m','app.services.email_worker' `
    -WorkingDirectory (Join-Path $Root 'backend') -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Logs 'worker.out.log') `
    -RedirectStandardError  (Join-Path $Logs 'worker.err.log')
  Start-Sleep 2
  Write-Host '   started (processes queued emails 1-by-1, 1s apart)' -ForegroundColor Green
}

# ------------------------------------------------------------ 3. Backend API
Write-Host '3) Backend API ...' -ForegroundColor Yellow
$ApiProc = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue
if ($ApiProc) {
  Write-Host '   restarting (kills previous process on :8000)...' -ForegroundColor Yellow
  $ApiProc | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
  Start-Sleep 2
}
if (-not (Test-Path $Py)) {
  Write-Host '   FAILED: backend\.venv missing. Create it first (see README).' -ForegroundColor Red
} else {
  Start-Process -FilePath $Py -ArgumentList 'run.py' `
    -WorkingDirectory (Join-Path $Root 'backend') -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Logs 'api.out.log') `
    -RedirectStandardError  (Join-Path $Logs 'api.err.log')
  if (Wait-Port $ApiPort) { Write-Host '   started on :8000' -ForegroundColor Green }
  else { Write-Host '   WARNING: API did not answer on :8000 - check logs\api.err.log' -ForegroundColor Red }
}

# ------------------------------------------------------------ 4. Frontend
Write-Host '4) Frontend ...' -ForegroundColor Yellow
if (Test-Port $FrontendPort) {
  Write-Host '   already running on :5173' -ForegroundColor Green
} elseif (Test-Path (Join-Path $Root 'frontend\node_modules')) {
  $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
  if (-not $npm) { $npm = (Get-Command npm -ErrorAction SilentlyContinue).Source }
  if ($npm) {
    Start-Process -FilePath $npm -ArgumentList 'run', 'dev' `
      -WorkingDirectory (Join-Path $Root 'frontend') -WindowStyle Hidden `
      -RedirectStandardOutput (Join-Path $Logs 'web.out.log') `
      -RedirectStandardError  (Join-Path $Logs 'web.err.log')
    if (Wait-Port $FrontendPort) { Write-Host '   started on :5173' -ForegroundColor Green }
    else { Write-Host '   WARNING: dev server did not answer on :5173 - check logs\web.err.log' -ForegroundColor Red }
  } else {
    Write-Host '   FAILED: npm not found on PATH.' -ForegroundColor Red
  }
} else {
  Write-Host '   WARNING: frontend\node_modules missing - run `npm install` in frontend first.' -ForegroundColor Red
}

# ------------------------------------------------------------ 5. Verify
Write-Host '5) Verification...' -ForegroundColor Yellow
$checks = @(
  @{ Name = 'API       : http://127.0.0.1:8000/health'; Url = 'http://127.0.0.1:8000/health' },
  @{ Name = 'Engine    : http://127.0.0.1:8081/health'; Url = 'http://127.0.0.1:8081/health' },
  @{ Name = 'Frontend  : http://localhost:5173'       ; Url = 'http://localhost:5173' }
)
foreach ($c in $checks) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $c.Url -TimeoutSec 5
    Write-Host "   [OK] $($c.Name) -> $($r.StatusCode)" -ForegroundColor Green
  } catch {
    Write-Host "   [FAIL] $($c.Name)" -ForegroundColor Red
  }
}

Write-Host ''
Write-Host 'All set. Open http://localhost:5173  (login: admin / admin123)' -ForegroundColor Cyan
Write-Host 'Logs are written to: logs\' -ForegroundColor Cyan