#!/usr/bin/env bash
# Collect everything needed to debug a failed install into diag.txt (no .env secrets).
# Usage: scripts/diag.sh [out-file]
cd "$(dirname "$0")/.." || exit 1
[ -f docker-compose.yml ] || { echo "Not in the project: keep this file in <project>/scripts/ and run it from there" >&2; exit 1; }
out=${1:-diag.txt}
{
    echo "===== $(date -u +%FT%TZ) $(uname -a)"
    echo "===== COMPOSE_PROFILES / GATEWAY_AUTH"; grep -E '^(COMPOSE_PROFILES|GATEWAY_AUTH|GATEWAY_HOSTNAMES)=' .env
    echo "===== docker version"; docker version
    echo "===== docker info"; docker info
    echo "===== compose ps"; docker compose ps -a
    echo "===== pool workers"; docker ps -a --filter label=rm.pool
    echo "===== disk"; docker system df
    echo "===== stats"; docker stats --no-stream
    echo "===== compose config check"; docker compose config -q && echo ok
    for c in $(docker compose ps -a -q); do
        name=$(docker inspect -f '{{.Name}}' "$c" | tr -d /)
        echo; echo "===== $name state"
        docker inspect -f '{{json .State}}' "$c"
        echo "===== $name logs"
        # ponytail: 1000 lines per container; raise if the cause scrolled off
        docker logs --tail 1000 "$c" 2>&1
    done
    for c in $(docker ps -a -q --filter label=rm.pool); do
        echo; echo "===== $(docker inspect -f '{{.Name}}' "$c") logs"
        docker logs --tail 300 "$c" 2>&1
    done
} > "$out" 2>&1
echo "Wrote $out ($(wc -l < "$out") lines). Check it before sharing outside your machines."
