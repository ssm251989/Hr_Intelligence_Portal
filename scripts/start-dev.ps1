# Start the HR app for development on Windows (fix 2026-10-04: the worker must run too).
#   powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
# Opens one window each for the backend API and the frontend. All background jobs run inside the
# backend (JOBS_IN_APP, default when there's no REDIS_URL). A Celery worker is optional (needs Redis).
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontend'; npm run dev"

$redis = (Get-Content (Join-Path $backend ".env") -ErrorAction SilentlyContinue | Where-Object { $_ -match "^REDIS_URL=\S" })
if ($redis) {
    # Optional: a real Celery worker (+ beat). Put JOBS_IN_APP=false in backend\.env so jobs don't run twice.
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backend'; .\.venv\Scripts\celery.exe -A app.platform.jobs.celery_app:celery_app worker -B --pool=solo -l info"
    Write-Host "Started backend, frontend and the Celery worker."
} else {
    Write-Host "Started backend and frontend. Background jobs (interview times after shortlist, reminders, the 24 h"
    Write-Host "salary-form reminder, activation email retries ...) run INSIDE the backend - no separate worker needed."
    Write-Host "Check them in Settings > Data > Health (Background jobs: green, with each job's last run)."
}
