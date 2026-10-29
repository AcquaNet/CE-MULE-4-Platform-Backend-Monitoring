#!/bin/bash
#
# Monitoring/alerting setup. What runs is chosen by COMPOSE_PROFILES in .env:
#   monitoring             Prometheus + Grafana   (https://localhost:9443/prometheus (ops / GATEWAY_OPS_PASSWORD), /grafana)
#   alerting               Alertmanager           (no gateway route: docker compose logs alertmanager)
#   opensearch-monitoring  OpenSearch exporter    (scraped by Prometheus)
#
# This script renders config/alertmanager/alertmanager.yml from alertmanager.yml.template with the SMTP_* and
# ALERT_GROUP_* / ALERT_*_INTERVAL values of .env, then restarts what needs it.
#
# Usage: ./config/scripts/monitoring/setup-monitoring.sh            render alertmanager.yml (if `alerting` is on) + status
#        ./config/scripts/monitoring/setup-monitoring.sh --reload   also restart Prometheus (re-reads prometheus.yml + rules)
set -euo pipefail
cd "$(dirname "$0")/../../.."
[ -f .env ] || { echo "ERROR: no .env (run ./install.sh)" >&2; exit 1; }
set -a; . ./.env; set +a
running() { docker compose ps --status running --services 2>/dev/null | grep -qx "$1"; }

if [[ ",${COMPOSE_PROFILES:-}," == *,alerting,* ]]; then
    out=config/alertmanager/alertmanager.yml
    group_by="['$(echo "${ALERT_GROUP_BY:-alertname,cluster,service}" | sed "s/,/','/g")']"
    # | as sed delimiter: values may contain / (e.g. URLs); passwords must not contain |
    sed -e "s|\${SMTP_HOST}|${SMTP_HOST:-smtp.gmail.com}|g" \
        -e "s|\${SMTP_PORT}|${SMTP_PORT:-587}|g" \
        -e "s|\${SMTP_FROM_ADDRESS}|${SMTP_FROM_ADDRESS:-alerts@example.com}|g" \
        -e "s|\${SMTP_USERNAME}|${SMTP_USERNAME:-}|g" \
        -e "s|\${SMTP_PASSWORD}|${SMTP_PASSWORD:-}|g" \
        -e "s|\${SMTP_USE_TLS}|${SMTP_USE_TLS:-true}|g" \
        -e "s|\${ALERT_GROUP_BY_ARRAY}|${group_by}|g" \
        -e "s|\${ALERT_GROUP_WAIT}|${ALERT_GROUP_WAIT:-30s}|g" \
        -e "s|\${ALERT_GROUP_INTERVAL}|${ALERT_GROUP_INTERVAL:-5m}|g" \
        -e "s|\${ALERT_REPEAT_INTERVAL}|${ALERT_REPEAT_INTERVAL:-4h}|g" \
        config/alertmanager/alertmanager.yml.template > "$out"
    chmod 600 "$out"   # holds the SMTP password
    echo "rendered $out"
    running alertmanager && docker compose restart alertmanager >/dev/null && echo "restarted alertmanager"
else
    echo "alerting profile is off (COMPOSE_PROFILES): alertmanager.yml left as is"
fi

if [ "${1:-}" = "--reload" ] && running prometheus; then
    docker compose restart prometheus >/dev/null && echo "restarted prometheus"
fi

echo
docker compose ps -a --format '  {{.Name}}: {{.State}} {{.Health}}' prometheus grafana alertmanager opensearch-exporter 2>/dev/null \
    || echo "  (none of the monitoring services is running: add monitoring/alerting/opensearch-monitoring to COMPOSE_PROFILES)"
