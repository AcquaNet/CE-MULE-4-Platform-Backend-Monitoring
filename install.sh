#!/usr/bin/env bash
# One command to install (fresh clone) or start the platform:  ./install.sh
#
#  1. No .env yet: creates it from .env.example with generated secrets.
#  2. Builds and starts the profiles in COMPOSE_PROFILES (.env) and waits until they are healthy.
#     APISIX creates its HTTPS certificate (certs/) on first start.
#  3. Waits until the Runtime Manager has started the Mule workers and the default app.
#  4. Prints where everything is.
# Offline server: scripts/docker-images/import-images.sh <tar>, then NO_BUILD=1 ./install.sh.
# Safe to re-run. Day to day `docker compose up -d` / `docker compose down` do the same minus the waiting.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop (or the Docker service) and run ./install.sh again."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required ('docker compose ...')."

if [ ! -f .env ]; then
    say "Creating .env from .env.example with generated secrets"
    bash config/scripts/setup/generate-secrets.sh >/dev/null
fi
env_get() { sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r'; }
[ -n "$(env_get RM_PASSWORD)" ] && [ "$(env_get RM_PASSWORD)" != CHANGE_ME_PLEASE ] \
    || die ".env has no RM_PASSWORD: run config/scripts/setup/generate-secrets.sh --force (new secrets) or set it"

say "Building and starting: core + profiles '$(env_get COMPOSE_PROFILES)' (first run downloads images, a few minutes)"
# NO_BUILD=1: offline server with images from scripts/docker-images/import-images.sh (builds would need downloads)
build=--build; [ "${NO_BUILD:-}" = 1 ] && build=--no-build
docker compose up -d $build --remove-orphans --wait --wait-timeout 900

# Services that read mounted config only at start: `up` doesn't recreate them for a changed file, so restart
# any whose config is newer than the running container (apisix.yaml itself hot-reloads, no restart needed).
restart_if_changed() {
    local svc=$1; shift
    local started newest=0 f
    started=$(docker inspect -f '{{.State.StartedAt}}' "$svc" 2>/dev/null) || return 0
    started=$(date -d "$started" +%s 2>/dev/null) || return 0
    for f in "$@"; do
        [ -e "$f" ] || continue
        f=$(find "$f" -type f -newermt "@$started" 2>/dev/null | head -n 1)
        [ -n "$f" ] && newest=1
    done
    if [ "$newest" = 1 ]; then
        say "Config of $svc changed since it started: restarting it"
        docker compose restart "$svc" >/dev/null 2>&1
    fi
}
restart_if_changed apisix config/apisix/config/config.yaml
restart_if_changed prometheus config/prometheus
restart_if_changed alertmanager config/alertmanager
restart_if_changed grafana config/grafana

RM="https://localhost:9443/runtime-manager"
AUTH="$(env_get RM_USER):$(env_get RM_PASSWORD)"
[ "$AUTH" = ":$(env_get RM_PASSWORD)" ] && AUTH="admin:$(env_get RM_PASSWORD)"
say "Waiting for the Runtime Manager to start the Mule workers (first run builds the Mule runtime image)"
last="" deadline=$((SECONDS + 1200))
while :; do
    pools=$(curl -sk -u "$AUTH" "$RM/api/pools" 2>/dev/null || true)
    apps=$(curl -sk -u "$AUTH" "$RM/api/apps" 2>/dev/null || true)
    # pool states and app worker states, without needing jq or python on the host
    states=$(printf '%s' "$pools" | grep -o '"state": "[a-z]*", "message": "[^"]*"' | sed 's/"state": "\([a-z]*\)", "message": "\(.*\)"/\1: \2/' | tr '\n' ';')
    [ "$states" != "$last" ] && [ -n "$states" ] && echo "    $states" && last=$states
    if printf '%s' "$states" | grep -q "error:"; then
        die "a runtime pool failed: $states (details: docker compose logs ce-base-runtime-manager)"
    fi
    if [ -n "$states" ] && ! printf '%s' "$states" | grep -qE "(pending|working):"; then
        if ! printf '%s' "$apps" | grep -qE '"(DEPLOYING|FAILED)"'; then
            break
        fi
        printf '%s' "$apps" | grep -q '"FAILED"' && die "an app failed to deploy, see its Logs tab in the Runtime Manager"
    fi
    [ $SECONDS -gt $deadline ] && die "timed out waiting for the Mule workers (docker compose logs ce-base-runtime-manager)"
    sleep 5
done

running=$(docker compose ps --services --status running)
has() { printf '%s\n' "$running" | grep -qx "$1"; }
say "Ready"
echo
if has keycloak; then
    echo "  Home (all tools)  https://localhost:9443/   one Keycloak sign-in: admin / KEYCLOAK_REALM_ADMIN_PASSWORD from .env"
    ops=""
else
    ops="   (ops / GATEWAY_OPS_PASSWORD from .env)"
fi
echo "  Runtime Manager   $RM/"
echo "                    scripts: $(env_get RM_USER | sed 's/^$/admin/') / RM_PASSWORD from .env, or an API token"
echo "                    API docs: $RM/api/docs"
echo "  Mule API          https://localhost:9443/api/v1/status$(has keycloak && echo '   (token of client mule-api-gateway with role api-access)')"
has opensearch-dashboards && echo "  Dashboards        https://localhost:9443/dashboards/"
has jaeger && echo "  Jaeger            https://localhost:9443/jaeger/$ops"
has grafana && echo "  Grafana           https://localhost:9443/grafana/"
has prometheus && echo "  Prometheus        https://localhost:9443/prometheus/$ops"
has keycloak && echo "  Keycloak admin    https://localhost:9443/auth/admin/   (KEYCLOAK_ADMIN_USER / KEYCLOAK_ADMIN_PASSWORD)"
echo
echo "  HTTPS uses a local CA: trust certs/ca/ca.crt in your OS/browser to drop the warning (curl --cacert certs/ca/ca.crt; on Windows add --ssl-no-revoke)."
echo "  Stop: docker compose down     Start again: docker compose up -d (or ./install.sh)"
