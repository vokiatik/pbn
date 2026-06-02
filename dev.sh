#!/usr/bin/env bash
set -euo pipefail

# Development bootstrap script:
# 1) Stop and remove existing project containers
# 2) Start infra services first
# 3) Wait for infra health
# 4) Start backend, then worker/frontend

COMPOSE_FILE="docker-compose.yml"
PROJECT_NAME="pbn"
HEALTH_TIMEOUT_SECONDS="120"
BACKEND_HEALTH_URL="http://localhost:8080/healthz"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "[error] $COMPOSE_FILE not found in current directory"
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[error] Docker Compose is not installed"
  exit 1
fi

compose() {
  "${COMPOSE_CMD[@]}" -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

wait_for_service_healthy() {
  local service="$1"
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))

  local container_id
  container_id="$(compose ps -q "$service")"

  if [[ -z "$container_id" ]]; then
    echo "[error] Could not find container id for service: $service"
    exit 1
  fi

  echo "[wait] Waiting for $service to become healthy..."
  while (( SECONDS < deadline )); do
    local health
    health="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container_id" 2>/dev/null || true)"

    if [[ "$health" == "healthy" ]]; then
      echo "[ok] $service is healthy"
      return 0
    fi

    if [[ "$health" == "no-healthcheck" ]]; then
      echo "[warn] $service has no healthcheck; continuing"
      return 0
    fi

    sleep 2
  done

  echo "[error] Timed out waiting for $service health"
  compose logs "$service" || true
  exit 1
}

wait_for_backend_http() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  echo "[wait] Waiting for backend health endpoint..."

  while (( SECONDS < deadline )); do
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS "$BACKEND_HEALTH_URL" >/dev/null 2>&1; then
        echo "[ok] backend health endpoint is reachable"
        return 0
      fi
    else
      # If curl is unavailable, skip HTTP probe after containers are started.
      echo "[warn] curl not found; skipping backend HTTP health probe"
      return 0
    fi

    sleep 2
  done

  echo "[error] Timed out waiting for backend health endpoint"
  compose logs backend || true
  exit 1
}

echo "[step] Stopping and removing existing containers"
compose down --remove-orphans

echo "[step] Starting infrastructure (postgres, redis)"
compose up -d --build --force-recreate postgres redis
wait_for_service_healthy postgres
wait_for_service_healthy redis

echo "[step] Starting backend"
compose up -d --build --force-recreate backend
wait_for_backend_http

echo "[step] Starting worker and frontend"
compose up -d --build --force-recreate worker frontend

echo "[step] Final service status"
compose ps

echo "[done] Fresh stack is up."
echo "        Frontend: http://localhost:5173"
echo "        Backend:  http://localhost:8080"
