#!/bin/bash
#
# Health Check Script for ELK Stack and Monitoring Services
#
# This script checks the health status of all services in the ELK stack
# and monitoring infrastructure.
#
# Usage:
#   ./config/monitoring/check-health.sh [options]
#
# Options:
#   --json      Output results in JSON format
#   --verbose   Show detailed health information
#   --watch     Continuously monitor health (updates every 10s)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
JSON_OUTPUT=false
VERBOSE=false
WATCH=false

for arg in "$@"; do
    case $arg in
        --json)
            JSON_OUTPUT=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --watch)
            WATCH=true
            shift
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--json] [--verbose] [--watch]"
            exit 1
            ;;
    esac
done

# Function to check HTTP endpoint
check_http() {
    local name=$1
    local url=$2
    local timeout=${3:-5}

    if curl -sf --max-time "$timeout" "$url" > /dev/null 2>&1; then
        echo "healthy"
    else
        echo "unhealthy"
    fi
}

# Function to check Docker container
check_container() {
    local name=$1

    if docker ps --filter "name=$name" --filter "status=running" --format '{{.Names}}' 2>/dev/null | grep -q "$name"; then
        echo "running"
    else
        echo "stopped"
    fi
}

# Function to perform health checks
perform_health_checks() {
    # Initialize results
    declare -A health_status

    # ELK Stack Services
    health_status[elasticsearch]=$(check_http "ElasticSearch" "http://localhost:9080/elasticsearch/_cluster/health" 10)
    health_status[elasticsearch_container]=$(check_container "elasticsearch")

    health_status[logstash]=$(check_http "Logstash" "http://localhost:9080/logstash" 10)
    health_status[logstash_container]=$(check_container "logstash")

    health_status[kibana]=$(check_http "Kibana" "http://localhost:9080/kibana/api/status" 10)
    health_status[kibana_container]=$(check_container "kibana")

    health_status[apm_server]=$(check_container "apm-server")

    # APISIX Gateway
    health_status[apisix]=$(check_http "APISIX" "http://localhost:9080/" 5)
    health_status[apisix_container]=$(check_container "apisix")

    health_status[etcd]=$(check_container "etcd")

    # Monitoring Services
    health_status[prometheus]=$(check_http "Prometheus" "http://localhost:9090/-/healthy" 5)
    health_status[prometheus_container]=$(check_container "prometheus")

    health_status[grafana]=$(check_http "Grafana" "http://localhost:3000/api/health" 5)
    health_status[grafana_container]=$(check_container "grafana")

    # Optional monitoring services
    health_status[alertmanager]=$(check_http "Alertmanager" "http://localhost:9093/-/healthy" 5)
    health_status[alertmanager_container]=$(check_container "alertmanager")

    health_status[elasticsearch_exporter]=$(check_http "ES Exporter" "http://localhost:9114/health" 5)
    health_status[elasticsearch_exporter_container]=$(check_container "elasticsearch-exporter")

    # ElasticSearch cluster health details
    if [ "${health_status[elasticsearch]}" = "healthy" ]; then
        ES_CLUSTER_HEALTH=$(curl -sf "http://localhost:9080/elasticsearch/_cluster/health" 2>/dev/null || echo '{"status":"unknown"}')
        health_status[es_cluster_status]=$(echo "$ES_CLUSTER_HEALTH" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        health_status[es_cluster_nodes]=$(echo "$ES_CLUSTER_HEALTH" | grep -o '"number_of_nodes":[0-9]*' | cut -d':' -f2)
        health_status[es_unassigned_shards]=$(echo "$ES_CLUSTER_HEALTH" | grep -o '"unassigned_shards":[0-9]*' | cut -d':' -f2)
    else
        health_status[es_cluster_status]="unknown"
        health_status[es_cluster_nodes]="0"
        health_status[es_unassigned_shards]="0"
    fi

    # Export for use in output functions
    for key in "${!health_status[@]}"; do
        export "health_${key}=${health_status[$key]}"
    done
}

# Function to output JSON
output_json() {
    cat <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "elk_stack": {
    "elasticsearch": {
      "health": "$health_elasticsearch",
      "container": "$health_elasticsearch_container",
      "cluster_status": "$health_es_cluster_status",
      "cluster_nodes": $health_es_cluster_nodes,
      "unassigned_shards": $health_es_unassigned_shards
    },
    "logstash": {
      "health": "$health_logstash",
      "container": "$health_logstash_container"
    },
    "kibana": {
      "health": "$health_kibana",
      "container": "$health_kibana_container"
    },
    "apm_server": {
      "container": "$health_apm_server"
    }
  },
  "gateway": {
    "apisix": {
      "health": "$health_apisix",
      "container": "$health_apisix_container"
    },
    "etcd": {
      "container": "$health_etcd"
    }
  },
  "monitoring": {
    "prometheus": {
      "health": "$health_prometheus",
      "container": "$health_prometheus_container"
    },
    "grafana": {
      "health": "$health_grafana",
      "container": "$health_grafana_container"
    },
    "alertmanager": {
      "health": "$health_alertmanager",
      "container": "$health_alertmanager_container"
    },
    "elasticsearch_exporter": {
      "health": "$health_elasticsearch_exporter",
      "container": "$health_elasticsearch_exporter_container"
    }
  }
}
EOF
}

# Function to output human-readable format
output_human() {
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}   ELK Stack Health Check - $(date)${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo ""

    echo -e "${YELLOW}ELK Stack Services:${NC}"
    print_service_status "ElasticSearch" "$health_elasticsearch" "$health_elasticsearch_container"
    if [ "$VERBOSE" = true ] && [ "$health_elasticsearch" = "healthy" ]; then
        echo "    Cluster Status: $(get_status_color "$health_es_cluster_status")"
        echo "    Nodes: $health_es_cluster_nodes"
        echo "    Unassigned Shards: $health_es_unassigned_shards"
    fi

    print_service_status "Logstash" "$health_logstash" "$health_logstash_container"
    print_service_status "Kibana" "$health_kibana" "$health_kibana_container"
    print_service_status "APM Server" "-" "$health_apm_server"
    echo ""

    echo -e "${YELLOW}APISIX Gateway:${NC}"
    print_service_status "APISIX" "$health_apisix" "$health_apisix_container"
    print_service_status "etcd" "-" "$health_etcd"
    echo ""

    echo -e "${YELLOW}Monitoring Services:${NC}"
    print_service_status "Prometheus" "$health_prometheus" "$health_prometheus_container"
    print_service_status "Grafana" "$health_grafana" "$health_grafana_container"
    print_service_status "Alertmanager" "$health_alertmanager" "$health_alertmanager_container"
    print_service_status "ES Exporter" "$health_elasticsearch_exporter" "$health_elasticsearch_exporter_container"
    echo ""

    # Summary
    total_healthy=0
    total_unhealthy=0

    for status in "$health_elasticsearch" "$health_logstash" "$health_kibana" "$health_apisix" "$health_prometheus" "$health_grafana"; do
        if [ "$status" = "healthy" ]; then
            ((total_healthy++))
        elif [ "$status" = "unhealthy" ]; then
            ((total_unhealthy++))
        fi
    done

    echo -e "${YELLOW}Summary:${NC}"
    echo -e "  Healthy: ${GREEN}$total_healthy${NC}"
    echo -e "  Unhealthy: ${RED}$total_unhealthy${NC}"
    echo ""

    if [ "$total_unhealthy" -gt 0 ]; then
        echo -e "${RED}⚠ Some services are unhealthy!${NC}"
        echo ""
        echo "Troubleshooting steps:"
        echo "  1. Check service logs: docker-compose logs <service-name>"
        echo "  2. Restart unhealthy services: docker-compose restart <service-name>"
        echo "  3. Check Docker resources: docker stats"
        echo ""
        return 1
    else
        echo -e "${GREEN}✓ All monitored services are healthy${NC}"
        echo ""
        return 0
    fi
}

# Function to print service status
print_service_status() {
    local name=$1
    local health=$2
    local container=$3

    local health_color=""
    local container_color=""

    case "$health" in
        healthy)
            health_color="${GREEN}●${NC}"
            ;;
        unhealthy)
            health_color="${RED}●${NC}"
            ;;
        *)
            health_color="${YELLOW}●${NC}"
            ;;
    esac

    case "$container" in
        running)
            container_color="${GREEN}running${NC}"
            ;;
        stopped)
            container_color="${RED}stopped${NC}"
            ;;
        *)
            container_color="${YELLOW}unknown${NC}"
            ;;
    esac

    printf "  %-20s %s  Container: %s\n" "$name" "$health_color" "$container_color"
}

# Function to get status color
get_status_color() {
    local status=$1

    case "$status" in
        green)
            echo -e "${GREEN}$status${NC}"
            ;;
        yellow)
            echo -e "${YELLOW}$status${NC}"
            ;;
        red)
            echo -e "${RED}$status${NC}"
            ;;
        *)
            echo "$status"
            ;;
    esac
}

# Main execution
if [ "$WATCH" = true ]; then
    # Watch mode - continuously monitor
    while true; do
        clear
        perform_health_checks
        if [ "$JSON_OUTPUT" = true ]; then
            output_json
        else
            output_human
        fi
        echo "Refreshing in 10 seconds... (Ctrl+C to exit)"
        sleep 10
    done
else
    # Single check
    perform_health_checks
    if [ "$JSON_OUTPUT" = true ]; then
        output_json
    else
        output_human
    fi
fi
