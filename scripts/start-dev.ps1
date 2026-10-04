# Start the HR app for development on Windows (fix 2026-10-04: the worker must run too).
#   powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
# Opens one window each for: backend API, frontend, and the background worker (when Redis is set).
# Interview scheduling after a shortlist (undo-window release, mailbox retries) also runs inside
# the backend itself when there is no worker (INTERVIEW_JOBS_IN_APP), so it never silently stops.
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontend'; npm run dev"

$redis = (Get-Content (Join-Path $backend ".env") -ErrorAction SilentlyContinue | Where-Object { $_ -match "^REDIS_URL=\S" })
if ($redis) {
    # -B = the scheduler (beat) in the same process; --pool=solo because Windows has no fork
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backend'; .\.venv\Scripts\celery.exe -A app.platform.jobs.celery_app:celery_app worker -B --pool=solo -l info"
    Write-Host "Started backend, frontend and the background worker."
} else {
    Write-Host "Started backend and frontend. No REDIS_URL in backend\.env, so the background worker was NOT started:" -ForegroundColor Yellow
    Write-Host "  reminders, salary/document forms and report schedules won't run (Settings > Data > Health shows red)." -ForegroundColor Yellow
    Write-Host "  Interview scheduling after a shortlist still runs inside the backend." -ForegroundColor Yellow
    Write-Host "  To enable the worker: run Redis (e.g. Memurai on Windows), set REDIS_URL=redis://localhost:6379/0 in backend\.env, run this again."
}
