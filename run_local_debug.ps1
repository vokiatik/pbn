$ErrorActionPreference = "Stop"

$root = "C:\Users\admin\pbn"

Write-Host "Starting Postgres and Redis..."
cd $root
docker compose up -d postgres redis
Start-Sleep -Seconds 5

Write-Host "Starting Python PBN..."
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$root\pbn'; `$env:PYTHONUNBUFFERED='1'; `$env:LOG_LEVEL='DEBUG'; python -m uvicorn runner:app --reload --host 127.0.0.1 --port 8081 --log-level debug"
)

Write-Host "Starting Worker..."
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$root\worker'; `$env:REDIS_ADDR='localhost'; `$env:REDIS_PORT='6379'; `$env:REDIS_DB='0'; `$env:REDIS_QUEUE_NAME='pbn:jobs'; `$env:REDIS_EVENTS_CHANNEL='pbn:events'; `$env:WORKER_CONCURRENCY='3'; `$env:BACKEND_INTERNAL_BASE='http://127.0.0.1:8080/api/internal'; `$env:PYTHON_RUNNER_BASE_URL='http://127.0.0.1:8081'; `$env:INTERNAL_API_SECRET='local-dev-secret'; python worker.py"
)

Write-Host "Starting Go Backend..."
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$root\backend'; `$env:HTTP_PORT='8080'; `$env:POSTGRES_DSN='postgres://pbn:pbn@127.0.0.1:5433/pbn?sslmode=disable'; `$env:REDIS_ADDR='localhost:6379'; `$env:REDIS_DB='0'; `$env:REDIS_QUEUE_NAME='pbn:jobs'; `$env:QUEUE_MAX_SIZE='20'; `$env:MAX_ACTIVE_PROJECTS_PER_CLIENT='2'; `$env:STORAGE_ROOT='$root\storage'; `$env:PUBLIC_ID_LENGTH='12'; `$env:INTERNAL_API_SECRET='local-dev-secret'; `$env:PYTHON_RUNNER_BASE_URL='http://127.0.0.1:8081'; `$env:LOG_LEVEL='debug'; go run .\cmd\server\main.go"
)

Write-Host "Starting Frontend..."
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$root\frontend'; npm run dev"
)

Write-Host "Starting Docker logs..."
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$root'; docker compose logs -f postgres redis"
)

Write-Host ""
Write-Host "Started:"
Write-Host "Frontend: http://localhost:5173"
Write-Host "Backend:  http://localhost:8080"
Write-Host "PBN:      http://localhost:8081"