#!/bin/bash
#
# Health of the running platform: the Docker healthcheck of every compose service, the Mule pool workers
# (Runtime Manager containers, label rm.pool) and the OpenSearch cluster status. Exit code 1 if anything is unhealthy.
#
# Usage: ./config/scripts/monitoring/check-health.sh [--watch]
set -uo pipefail
cd "$(dirname "$0")/../../.."
[ -f .env ] && { set -a; . ./.env; set +a; }

check() {
    local bad=0 name state health
    echo "Services (docker compose healthchecks):"
    while read -r name state health; do
        [ -z "$name" ] && continue
        if [ "$state" = running ] && { [ "$health" = healthy ] || [ -z "$health" ]; }; then mark=OK; else mark=FAIL; bad=1; fi
        printf '  %-4s %-28s %s %s\n' "$mark" "$name" "$state" "$health"
    done < <(docker compose ps -a --format '{{.Name}} {{.State}} {{.Health}}')

    echo "Mule pool workers:"
    while read -r name status; do
        [ -z "$name" ] && continue
        if [[ "$status" == Up* && "$status" != *unhealthy* ]]; then mark=OK; else mark=FAIL; bad=1; fi
        printf '  %-4s %-28s %s\n' "$mark" "$name" "$status"
    done < <(docker ps -a --filter label=rm.pool --format '{{.Names}} {{.Status}}')

    if docker compose ps --status running --services 2>/dev/null | grep -qx opensearch; then
        local cs
        cs=$(curl -s -u "admin:${OPENSEARCH_ADMIN_PASSWORD:-}" http://localhost:9080/opensearch/_cluster/health \
            | grep -o '"status":"[a-z]*"' | cut -d'"' -f4)
        [ "$cs" = green ] || [ "$cs" = yellow ] && mark=OK || { mark=FAIL; bad=1; }
        printf 'OpenSearch cluster: %s %s\n' "$mark" "${cs:-unreachable}"
    fi
    return $bad
}

if [ "${1:-}" = "--watch" ]; then
    while true; do clear; date; check; sleep 10; done
fi
check
