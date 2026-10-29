#!/bin/bash
#
# Log/trace retention for OpenSearch (ISM): every daily index is deleted N days after it was created.
#   mule-logs-*                   MULE_LOGS_RETENTION_DAYS      (default 730)
#   logstash-*                    LOGSTASH_LOGS_RETENTION_DAYS  (default 730)
#   jaeger-span-*, jaeger-service-*  JAEGER_RETENTION_DAYS      (default 30)
# Policies carry an ism_template, so new daily indices get them automatically; existing indices are attached too.
# Idempotent: re-run after changing a value in .env. No rollover: Fluent Bit and Jaeger already write one index per day.
#
# Usage: ./config/scripts/ilm/setup-retention-policy.sh [--verify]
set -euo pipefail
cd "$(dirname "$0")/../../.."
[ -f .env ] && { set -a; . ./.env; set +a; }

OS="${OPENSEARCH_URL:-http://localhost:9080/opensearch}"   # gateway; 9080 is published on 127.0.0.1 only
AUTH="admin:${OPENSEARCH_ADMIN_PASSWORD:?OPENSEARCH_ADMIN_PASSWORD not set (.env)}"
os() { curl -s -u "$AUTH" -H 'Content-Type: application/json' "$@"; }

curl -s -o /dev/null -w '%{http_code}' -u "$AUTH" "$OS/_cluster/health" | grep -q 200 \
    || { echo "ERROR: cannot reach OpenSearch at $OS (is the logging/tracing profile up?)" >&2; exit 1; }

# how often ISM evaluates policies (minutes); ISM_POLL_INTERVAL like 10m
os -X PUT "$OS/_cluster/settings" \
    -d "{\"persistent\":{\"plugins.index_state_management.job_interval\":$(echo "${ISM_POLL_INTERVAL:-10m}" | tr -dc 0-9)}}" >/dev/null

# policy <id> <days> <pattern>...
policy() {
    local id=$1 days=$2; shift 2
    local patterns; patterns=$(printf '"%s",' "$@"); patterns="[${patterns%,}]"
    local body="{\"policy\":{\"description\":\"delete after ${days}d\",\"default_state\":\"hot\",
      \"states\":[{\"name\":\"hot\",\"actions\":[],\"transitions\":[{\"state_name\":\"delete\",\"conditions\":{\"min_index_age\":\"${days}d\"}}]},
                {\"name\":\"delete\",\"actions\":[{\"delete\":{}}],\"transitions\":[]}],
      \"ism_template\":[{\"index_patterns\":${patterns},\"priority\":100}]}}"
    # update needs the current seq_no/primary_term
    local cur seq term
    cur=$(os "$OS/_plugins/_ism/policies/$id")
    seq=$(echo "$cur" | grep -o '"_seq_no":[0-9]*' | cut -d: -f2 || true)
    term=$(echo "$cur" | grep -o '"_primary_term":[0-9]*' | cut -d: -f2 || true)
    if [ -n "$seq" ]; then
        os -X PUT "$OS/_plugins/_ism/policies/$id?if_seq_no=$seq&if_primary_term=$term" -d "$body" >/dev/null
        # indices already managed by the old version switch to the new one
        for p in "$@"; do os -X POST "$OS/_plugins/_ism/change_policy/$p" -d "{\"policy_id\":\"$id\"}" >/dev/null; done
    else
        os -X PUT "$OS/_plugins/_ism/policies/$id" -d "$body" >/dev/null
    fi
    # existing indices without a policy
    for p in "$@"; do os -X POST "$OS/_plugins/_ism/add/$p" -d "{\"policy_id\":\"$id\"}" >/dev/null; done
    echo "policy $id: delete after ${days} days ($*)"
}

policy mule-logs-retention "${MULE_LOGS_RETENTION_DAYS:-730}" "mule-logs-*"
policy logstash-retention  "${LOGSTASH_LOGS_RETENTION_DAYS:-730}" "logstash-*"
policy jaeger-retention    "${JAEGER_RETENTION_DAYS:-30}" "jaeger-span-*" "jaeger-service-*"

if [ "${1:-}" = "--verify" ]; then
    echo; echo "indices -> policy:"
    for p in "mule-logs-*" "logstash-*" "jaeger-span-*" "jaeger-service-*"; do
        os "$OS/_plugins/_ism/explain/$p" | grep -o '"[a-z0-9._-]*":{"index.plugins.index_state_management.policy_id":"[^"]*"' \
            | sed 's/"\([^"]*\)":{"index.plugins.index_state_management.policy_id":"\([^"]*\)"/  \1 -> \2/' || true
    done
fi
