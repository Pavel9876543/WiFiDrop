#!/usr/bin/env bash
set -Eeuo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "[WiFiDrop] Created .env from .env.example."
fi

mkdir -p Files logs
export WIFIDROP_UID="$(id -u)"
export WIFIDROP_GID="$(id -g)"

COMPOSE=()

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
        COMPOSE=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE=(docker-compose)
    fi
elif command -v docker >/dev/null 2>&1 \
    && command -v sudo >/dev/null 2>&1 \
    && sudo -n docker info >/dev/null 2>&1; then
    if sudo -n docker compose version >/dev/null 2>&1; then
        COMPOSE=(sudo -n --preserve-env=WIFIDROP_UID,WIFIDROP_GID docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE=(sudo -n --preserve-env=WIFIDROP_UID,WIFIDROP_GID docker-compose)
    fi
elif command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    if podman compose version >/dev/null 2>&1; then
        COMPOSE=(podman compose)
    elif command -v podman-compose >/dev/null 2>&1; then
        COMPOSE=(podman-compose)
    fi
fi

if (( ${#COMPOSE[@]} == 0 )); then
    cat >&2 <<'EOF'
[WiFiDrop] Docker Compose is unavailable or the container engine is not running.
Start Docker/Podman and try again. On Linux, either add your user to the docker
group or configure passwordless sudo for Docker; the script uses it when available.
EOF
    exit 1
fi

read_env_port() {
    local value
    value="$(sed -nE 's/^[[:space:]]*PORT[[:space:]]*=[[:space:]]*([^#[:space:]]+).*$/\1/p' .env | tail -n 1)"
    printf '%s' "${value:-8000}"
}

action="${1:-up}"
case "$action" in
    up)
        echo "[WiFiDrop] Starting at http://localhost:$(read_env_port) ..."
        exec "${COMPOSE[@]}" up --build
        ;;
    --detach|-d)
        "${COMPOSE[@]}" up --build --detach
        echo "[WiFiDrop] Running at http://localhost:$(read_env_port)"
        echo "[WiFiDrop] Use ./docker-run.sh logs or ./docker-run.sh down."
        ;;
    down)
        exec "${COMPOSE[@]}" down
        ;;
    logs)
        exec "${COMPOSE[@]}" logs --follow
        ;;
    restart)
        "${COMPOSE[@]}" down
        exec "${COMPOSE[@]}" up --build
        ;;
    status|ps)
        exec "${COMPOSE[@]}" ps
        ;;
    *)
        echo "Usage: ./docker-run.sh [up|--detach|-d|down|logs|restart|status]" >&2
        exit 2
        ;;
esac
