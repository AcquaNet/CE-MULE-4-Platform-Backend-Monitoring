#!/usr/bin/env bash
# Collect everything needed to debug a failed install into diag.txt (no .env secrets).
# Usage: scripts/diag.sh [out-file]
export MSYS_NO_PATHCONV=1   # Git Bash: keep /usr/... container paths as they are
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
    echo "===== log pipeline: gateway stream (TCP 9100)"; docker exec apisix tail -20 /usr/local/apisix/logs/stream-access.log
    echo "===== log pipeline: fluent-bit metrics"; docker exec fluent-bit /busybox wget -qO- http://127.0.0.1:2020/api/v1/metrics
    echo; echo "===== log pipeline: indices"
    pw=$(grep '^OPENSEARCH_ADMIN_PASSWORD=' .env | cut -d= -f2-)
    docker exec opensearch curl -sk -u "admin:$pw" "https://localhost:9200/_cat/indices?v&s=index"
    echo "===== log pipeline: newest mule-logs (no auth_token: fluent-bit strips it)"
    docker exec opensearch curl -sk -u "admin:$pw" "https://localhost:9200/mule-logs-*/_search?size=5&sort=@timestamp:desc&pretty"
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
