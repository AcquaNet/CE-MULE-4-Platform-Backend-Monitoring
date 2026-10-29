#!/bin/bash
# OpenSearch Dashboards entrypoint: the image's own entrypoint, plus (in the background) the index patterns of the
# Global tenant: mule-logs-*, logstash-*, jaeger-span-*. Created when missing on every start, never overwritten
# (an edited pattern stays), so Discover works on a fresh install and they come back if they were ever lost.
# API calls go to Dashboards itself as admin (Basic, OPENSEARCH_USERNAME/PASSWORD) with securitytenant: global.

provision() {
    local api="http://localhost:5601/dashboards/api" auth="$OPENSEARCH_USERNAME:$OPENSEARCH_PASSWORD"
    local h=(-H 'osd-xsrf: true' -H 'securitytenant: global' -H 'Content-Type: application/json')
    for _ in $(seq 120); do   # up to 10 min: the first start migrates the saved-objects index
        curl -sf -o /dev/null -u "$auth" "${h[@]}" "$api/saved_objects/_find?type=index-pattern&per_page=1" && break
        sleep 5
    done
    # id title time-field
    while read -r id title time; do
        code=$(curl -s -o /tmp/ip.out -w '%{http_code}' -u "$auth" "${h[@]}" -X POST "$api/saved_objects/index-pattern/$id" \
            -d "{\"attributes\":{\"title\":\"$title\",\"timeFieldName\":\"$time\"}}")
        case $code in
            200) echo "index pattern $title created (Global tenant)" ;;
            409) ;;   # exists: leave it as the users left it
            *) echo "index pattern $title not created: HTTP $code $(head -c 200 /tmp/ip.out)" ;;
        esac
    done <<'EOF'
mule-logs mule-logs-* @timestamp
logstash logstash-* @timestamp
jaeger-span jaeger-span-* startTimeMillis
EOF
    # Discover opens mule-logs-* unless someone picked another default
    if ! curl -s -u "$auth" "${h[@]}" "$api/saved_objects/_find?type=config&fields=defaultIndex" | grep -q '"defaultIndex":"[^"]'; then
        curl -s -o /dev/null -u "$auth" "${h[@]}" -X POST "$api/opensearch-dashboards/settings" -d '{"changes":{"defaultIndex":"mule-logs"}}'
    fi
}

provision &
# the image's ENTRYPOINT with its CMD (compose's entrypoint: drops the image's CMD)
cd /usr/share/opensearch-dashboards && exec ./opensearch-dashboards-docker-entrypoint.sh "${@:-opensearch-dashboards}"
