#!/bin/bash
#
# Setup Monitoring and Alerting System
#
# This script configures the monitoring and alerting system based on .env settings.
# It handles:
# - Enabling/disabling monitoring services (Prometheus, Grafana, ElasticSearch exporter)
# - Configuring Alertmanager with notification channels
# - Setting up alert rules and thresholds
#
# Usage:
#   ./config/monitoring/setup-monitoring.sh [options]
#
# Options:
#   --verify    Verify configuration after setup
#   --status    Show current monitoring status
#   --reload    Reload Prometheus configuration
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# Parse arguments
VERIFY=false
STATUS_ONLY=false
RELOAD=false

for arg in "$@"; do
    case $arg in
        --verify)
            VERIFY=true
            shift
            ;;
        --status)
            STATUS_ONLY=true
            shift
            ;;
        --reload)
            RELOAD=true
            shift
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--verify] [--status] [--reload]"
            exit 1
            ;;
    esac
done

# Load environment variables from .env
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}Warning: .env file not found at $ENV_FILE${NC}"
    echo -e "${YELLOW}Using default values. Copy .env.example to .env for customization.${NC}"
    echo ""
    # Set defaults
    MONITORING_ENABLED="${MONITORING_ENABLED:-true}"
    ALERTING_ENABLED="${ALERTING_ENABLED:-false}"
else
    echo -e "${GREEN}Loading configuration from .env file...${NC}"
    set -a
    source "$ENV_FILE"
    set +a
    echo -e "${GREEN}✓ Configuration loaded${NC}"
    echo ""
fi

# Configuration with defaults
MONITORING_ENABLED="${MONITORING_ENABLED:-true}"
ALERTING_ENABLED="${ALERTING_ENABLED:-false}"
ELASTICSEARCH_EXPORTER_ENABLED="${ELASTICSEARCH_EXPORTER_ENABLED:-true}"
PROMETHEUS_RETENTION="${PROMETHEUS_RETENTION:-30d}"

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   ELK Stack Monitoring and Alerting Setup${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Status check mode
if [ "$STATUS_ONLY" = true ]; then
    echo -e "${YELLOW}Current Monitoring Status:${NC}"
    echo ""
    echo "Configuration (.env):"
    echo "  Monitoring Enabled: ${MONITORING_ENABLED}"
    echo "  Alerting Enabled: ${ALERTING_ENABLED}"
    echo "  ElasticSearch Exporter: ${ELASTICSEARCH_EXPORTER_ENABLED}"
    echo ""

    echo "Running Services:"
    cd "$PROJECT_ROOT"

    # Check if services are running
    if command -v docker-compose &> /dev/null || command -v docker &> /dev/null; then
        echo "  Prometheus: $(docker ps --filter 'name=prometheus' --format '{{.Status}}' 2>/dev/null || echo 'Not running')"
        echo "  Grafana: $(docker ps --filter 'name=grafana' --format '{{.Status}}' 2>/dev/null || echo 'Not running')"
        echo "  Alertmanager: $(docker ps --filter 'name=alertmanager' --format '{{.Status}}' 2>/dev/null || echo 'Not running')"
        echo "  ES Exporter: $(docker ps --filter 'name=elasticsearch-exporter' --format '{{.Status}}' 2>/dev/null || echo 'Not running')"
    fi
    echo ""

    echo "Access URLs:"
    echo "  Prometheus: http://localhost:9080/prometheus"
    echo "  Grafana: http://localhost:9080/grafana"
    echo "  Alertmanager: http://localhost:9080/alertmanager (if enabled)"
    echo ""
    exit 0
fi

# Configuration summary
echo -e "${YELLOW}Configuration:${NC}"
echo "  Monitoring Enabled: ${MONITORING_ENABLED}"
echo "  Alerting Enabled: ${ALERTING_ENABLED}"
echo "  ElasticSearch Exporter: ${ELASTICSEARCH_EXPORTER_ENABLED}"
echo "  Metrics Retention: ${PROMETHEUS_RETENTION}"
echo ""

# Check if monitoring is disabled
if [ "$MONITORING_ENABLED" != "true" ]; then
    echo -e "${YELLOW}Warning: Monitoring is disabled in .env (MONITORING_ENABLED=false)${NC}"
    echo "No monitoring services will be started."
    echo ""
    echo "To enable monitoring:"
    echo "  1. Edit .env and set MONITORING_ENABLED=true"
    echo "  2. Run: $0"
    echo ""
    exit 0
fi

# Generate Alertmanager configuration if alerting is enabled
if [ "$ALERTING_ENABLED" = "true" ]; then
    echo -e "${GREEN}Generating Alertmanager configuration...${NC}"

    ALERTMANAGER_CONFIG="$PROJECT_ROOT/alertmanager/alertmanager.yml"
    ALERTMANAGER_TEMPLATE="$PROJECT_ROOT/alertmanager/alertmanager.yml.template"

    # Read template
    if [ ! -f "$ALERTMANAGER_TEMPLATE" ]; then
        echo -e "${RED}Error: Alertmanager template not found at $ALERTMANAGER_TEMPLATE${NC}"
        exit 1
    fi

    # Generate configuration from template
    cp "$ALERTMANAGER_TEMPLATE" "$ALERTMANAGER_CONFIG"

    # Replace environment variables
    sed -i "s/\${SMTP_HOST}/${SMTP_HOST:-smtp.gmail.com}/g" "$ALERTMANAGER_CONFIG"
    sed -i "s/\${SMTP_PORT}/${SMTP_PORT:-587}/g" "$ALERTMANAGER_CONFIG"
    sed -i "s/\${SMTP_FROM_ADDRESS}/${SMTP_FROM_ADDRESS:-alerts@example.com}/g" "$ALERTMANAGER_CONFIG"
    sed -i "s/\${SMTP_USERNAME}/${SMTP_USERNAME}/g" "$ALERTMANAGER_CONFIG"
    sed -i "s/\${SMTP_PASSWORD}/${SMTP_PASSWORD}/g" "$ALERTMANAGER_CONFIG"
    sed -i "s/\${SMTP_USE_TLS}/${SMTP_USE_TLS:-true}/g" "$ALERTMANAGER_CONFIG"

    # Convert group_by to array format
    ALERT_GROUP_BY_ARRAY="['$(echo ${ALERT_GROUP_BY:-alertname,cluster,service} | sed "s/,/','/g")']"
    sed -i "s/\${ALERT_GROUP_BY_ARRAY}/${ALERT_GROUP_BY_ARRAY}/g" "$ALERTMANAGER_CONFIG"

    sed -i "s/\${ALERT_GROUP_WAIT}/${ALERT_GROUP_WAIT:-30s}/g" "$ALERTMANAGER_CONFIG"
    sed -i "s/\${ALERT_GROUP_INTERVAL}/${ALERT_GROUP_INTERVAL:-5m}/g" "$ALERTMANAGER_CONFIG"
    sed -i "s/\${ALERT_REPEAT_INTERVAL}/${ALERT_REPEAT_INTERVAL:-4h}/g" "$ALERTMANAGER_CONFIG"

    # TODO: Generate receiver sections based on enabled notification channels
    # This would require more complex template processing

    echo -e "${GREEN}✓ Alertmanager configuration generated${NC}"
    echo ""
fi

# Reload Prometheus configuration if requested
if [ "$RELOAD" = true ]; then
    echo -e "${GREEN}Reloading Prometheus configuration...${NC}"

    # Send reload signal to Prometheus
    PROMETHEUS_URL="http://localhost:9090"

    if curl -sf -X POST "${PROMETHEUS_URL}/-/reload" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Prometheus configuration reloaded${NC}"
    else
        echo -e "${YELLOW}Warning: Could not reload Prometheus (is it running?)${NC}"
        echo "You may need to restart the Prometheus container:"
        echo "  docker-compose restart prometheus"
    fi
    echo ""
fi

# Instructions for starting services
echo -e "${GREEN}Starting monitoring services...${NC}"
echo ""

cd "$PROJECT_ROOT"

# Determine which profiles to enable
PROFILES=""
if [ "$ALERTING_ENABLED" = "true" ]; then
    PROFILES="$PROFILES --profile alerting"
fi
if [ "$ELASTICSEARCH_EXPORTER_ENABLED" = "true" ]; then
    PROFILES="$PROFILES --profile elasticsearch-monitoring"
fi

echo "Services to start:"
echo "  - Prometheus (always enabled)"
echo "  - Grafana (always enabled)"
if [ "$ELASTICSEARCH_EXPORTER_ENABLED" = "true" ]; then
    echo "  - ElasticSearch Exporter"
fi
if [ "$ALERTING_ENABLED" = "true" ]; then
    echo "  - Alertmanager"
fi
echo ""

echo "Run the following command to start services:"
echo ""
if [ -n "$PROFILES" ]; then
    echo -e "${BLUE}docker-compose $PROFILES up -d${NC}"
else
    echo -e "${BLUE}docker-compose up -d${NC}"
fi
echo ""

# Verify if requested
if [ "$VERIFY" = true ]; then
    echo -e "${GREEN}Waiting for services to start...${NC}"
    sleep 10

    echo ""
    echo -e "${YELLOW}Verifying services:${NC}"
    echo ""

    # Check Prometheus
    if curl -sf "http://localhost:9090/-/healthy" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Prometheus is healthy${NC}"
    else
        echo -e "${RED}✗ Prometheus is not responding${NC}"
    fi

    # Check Grafana
    if curl -sf "http://localhost:3000/api/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Grafana is healthy${NC}"
    else
        echo -e "${RED}✗ Grafana is not responding${NC}"
    fi

    # Check Alertmanager if enabled
    if [ "$ALERTING_ENABLED" = "true" ]; then
        if curl -sf "http://localhost:9093/-/healthy" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ Alertmanager is healthy${NC}"
        else
            echo -e "${RED}✗ Alertmanager is not responding${NC}"
        fi
    fi

    # Check ElasticSearch Exporter if enabled
    if [ "$ELASTICSEARCH_EXPORTER_ENABLED" = "true" ]; then
        if curl -sf "http://localhost:9114/health" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ ElasticSearch Exporter is healthy${NC}"
        else
            echo -e "${RED}✗ ElasticSearch Exporter is not responding${NC}"
        fi
    fi

    echo ""
fi

echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  ✓ Monitoring Setup Complete${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Access URLs:${NC}"
echo ""
echo "  Prometheus:"
echo "    ${BLUE}http://localhost:9080/prometheus${NC}"
echo ""
echo "  Grafana:"
echo "    ${BLUE}http://localhost:9080/grafana${NC}"
echo "    Default credentials: ${GRAFANA_ADMIN_USER:-admin} / (from .env)"
echo ""
if [ "$ALERTING_ENABLED" = "true" ]; then
    echo "  Alertmanager:"
    echo "    ${BLUE}http://localhost:9080/alertmanager${NC}"
    echo ""
fi
echo -e "${YELLOW}Useful Commands:${NC}"
echo ""
echo "  View monitoring status:"
echo "    ${BLUE}$0 --status${NC}"
echo ""
echo "  Reload Prometheus configuration:"
echo "    ${BLUE}$0 --reload${NC}"
echo ""
echo "  View Prometheus logs:"
echo "    ${BLUE}docker-compose logs -f prometheus${NC}"
echo ""
echo "  View Grafana logs:"
echo "    ${BLUE}docker-compose logs -f grafana${NC}"
echo ""
if [ "$ALERTING_ENABLED" = "true" ]; then
    echo "  View Alertmanager logs:"
    echo "    ${BLUE}docker-compose logs -f alertmanager${NC}"
    echo ""
fi
echo "  Check service health:"
echo "    ${BLUE}./config/monitoring/check-health.sh${NC}"
echo ""
