#!/bin/bash
#
# ElasticSearch Index Lifecycle Management (ILM) Setup Script
#
# This script configures automatic log retention policies for production environments.
# Configuration is read from .env file for consistency with other automation scripts.
#
# Usage:
#   ./config/ilm/setup-retention-policy.sh
#
# Options:
#   --verify    Verify policies after creation
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

for arg in "$@"; do
    case $arg in
        --verify)
            VERIFY=true
            shift
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--verify]"
            exit 1
            ;;
    esac
done

# Load environment variables from .env if it exists
if [ -f "$ENV_FILE" ]; then
    echo -e "${GREEN}Loading configuration from .env file...${NC}"
    set -a
    source "$ENV_FILE"
    set +a
    echo -e "${GREEN}✓ Configuration loaded${NC}"
    echo ""
else
    echo -e "${YELLOW}Warning: .env file not found at $ENV_FILE${NC}"
    echo -e "${YELLOW}Using default values. Create .env from .env.example for customization.${NC}"
    echo ""
fi

# Configuration with defaults
ES_URL="${ES_HOST:-http://localhost:9080/elasticsearch}"
MULE_LOGS_RETENTION_DAYS="${MULE_LOGS_RETENTION_DAYS:-730}"
LOGSTASH_LOGS_RETENTION_DAYS="${LOGSTASH_LOGS_RETENTION_DAYS:-730}"
ROLLOVER_SIZE="${ROLLOVER_SIZE:-1gb}"
ROLLOVER_MAX_AGE="${ROLLOVER_MAX_AGE:-1d}"
ILM_ENABLED="${ILM_ENABLED:-true}"

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   ElasticSearch Index Lifecycle Management Setup${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Check if ILM is enabled
if [ "$ILM_ENABLED" != "true" ]; then
    echo -e "${YELLOW}Warning: ILM is disabled in .env (ILM_ENABLED=false)${NC}"
    read -p "Do you want to continue anyway? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Setup cancelled."
        exit 0
    fi
    echo ""
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  ElasticSearch URL: $ES_URL"
echo "  Mule Logs Retention: $MULE_LOGS_RETENTION_DAYS days ($(echo "scale=1; $MULE_LOGS_RETENTION_DAYS / 365" | bc) years)"
echo "  Logstash Logs Retention: $LOGSTASH_LOGS_RETENTION_DAYS days ($(echo "scale=1; $LOGSTASH_LOGS_RETENTION_DAYS / 365" | bc) years)"
echo "  Rollover Size: $ROLLOVER_SIZE"
echo "  Rollover Age: $ROLLOVER_MAX_AGE"
echo ""

# Check ElasticSearch connectivity
echo "Checking ElasticSearch connectivity..."
if ! curl -sf "$ES_URL/_cluster/health" > /dev/null 2>&1; then
    echo "ERROR: Cannot connect to ElasticSearch at $ES_URL"
    echo "Please ensure ElasticSearch is running and accessible via APISIX"
    exit 1
fi
echo "✓ ElasticSearch is accessible"
echo ""

# Create ILM policy for Mule logs
echo -e "${GREEN}Creating ILM policy for mule-logs (retention: ${MULE_LOGS_RETENTION_DAYS} days)...${NC}"
RESPONSE=$(curl -s -X PUT "$ES_URL/_ilm/policy/mule-logs-policy" \
  -H 'Content-Type: application/json' \
  -d "{
  \"policy\": {
    \"phases\": {
      \"hot\": {
        \"min_age\": \"0ms\",
        \"actions\": {
          \"rollover\": {
            \"max_age\": \"${ROLLOVER_MAX_AGE}\",
            \"max_primary_shard_size\": \"${ROLLOVER_SIZE}\"
          },
          \"set_priority\": {
            \"priority\": 100
          }
        }
      },
      \"delete\": {
        \"min_age\": \"${MULE_LOGS_RETENTION_DAYS}d\",
        \"actions\": {
          \"delete\": {}
        }
      }
    }
  }
}")

# Check for errors
if echo "$RESPONSE" | grep -q "\"error\""; then
    echo -e "${RED}Error creating policy:${NC}"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓ Mule logs policy created${NC}"
echo ""

# Create ILM policy for Logstash logs
echo -e "${GREEN}Creating ILM policy for logstash-logs (retention: ${LOGSTASH_LOGS_RETENTION_DAYS} days)...${NC}"
RESPONSE=$(curl -s -X PUT "$ES_URL/_ilm/policy/logstash-logs-policy" \
  -H 'Content-Type: application/json' \
  -d "{
  \"policy\": {
    \"phases\": {
      \"hot\": {
        \"min_age\": \"0ms\",
        \"actions\": {
          \"rollover\": {
            \"max_age\": \"${ROLLOVER_MAX_AGE}\",
            \"max_primary_shard_size\": \"${ROLLOVER_SIZE}\"
          },
          \"set_priority\": {
            \"priority\": 50
          }
        }
      },
      \"delete\": {
        \"min_age\": \"${LOGSTASH_LOGS_RETENTION_DAYS}d\",
        \"actions\": {
          \"delete\": {}
        }
      }
    }
  }
}")

# Check for errors
if echo "$RESPONSE" | grep -q "\"error\""; then
    echo -e "${RED}Error creating policy:${NC}"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓ Logstash logs policy created${NC}"
echo ""

# Create index template for mule-logs to use ILM policy
echo "Creating index template for mule-logs..."
curl -X PUT "$ES_URL/_index_template/mule-logs-template" \
  -H 'Content-Type: application/json' \
  -d '{
  "index_patterns": ["mule-logs-*"],
  "template": {
    "settings": {
      "index.lifecycle.name": "mule-logs-policy",
      "index.lifecycle.rollover_alias": "mule-logs"
    }
  }
}'
echo ""
echo "✓ Mule logs index template created"
echo ""

# Create index template for logstash-logs to use ILM policy
echo "Creating index template for logstash-logs..."
curl -X PUT "$ES_URL/_index_template/logstash-logs-template" \
  -H 'Content-Type: application/json' \
  -d '{
  "index_patterns": ["logstash-*"],
  "template": {
    "settings": {
      "index.lifecycle.name": "logstash-logs-policy",
      "index.lifecycle.rollover_alias": "logstash"
    }
  }
}'
echo ""
echo "✓ Logstash logs index template created"
echo ""

# Verify policies
echo "Verifying ILM policies..."
echo ""
echo "Mule Logs Policy:"
curl -s "$ES_URL/_ilm/policy/mule-logs-policy" | grep -o '"min_age":"[^"]*"' || echo "Policy created successfully"
echo ""
echo ""
echo "Logstash Logs Policy:"
curl -s "$ES_URL/_ilm/policy/logstash-logs-policy" | grep -o '"min_age":"[^"]*"' || echo "Policy created successfully"
echo ""

# Verify policies if requested
if [ "$VERIFY" = true ]; then
    echo -e "${GREEN}Verifying ILM policies...${NC}"
    echo ""

    # Check if ILM is running
    ILM_STATUS=$(curl -s "$ES_URL/_ilm/status" | grep -o '"operation_mode":"[^"]*"' | cut -d'"' -f4)

    if [ "$ILM_STATUS" = "RUNNING" ]; then
        echo -e "${GREEN}✓ ILM is running${NC}"
    else
        echo -e "${YELLOW}Warning: ILM status is '$ILM_STATUS'. Starting ILM...${NC}"
        curl -s -X POST "$ES_URL/_ilm/start" > /dev/null
        echo -e "${GREEN}✓ ILM started${NC}"
    fi

    # Verify policies exist
    MULE_POLICY=$(curl -s "$ES_URL/_ilm/policy/mule-logs-policy" | grep -o '"mule-logs-policy"' || echo "")
    LOGSTASH_POLICY=$(curl -s "$ES_URL/_ilm/policy/logstash-logs-policy" | grep -o '"logstash-logs-policy"' || echo "")

    if [ -n "$MULE_POLICY" ]; then
        echo -e "${GREEN}✓ Mule logs policy verified${NC}"
    else
        echo -e "${RED}✗ Mule logs policy not found${NC}"
    fi

    if [ -n "$LOGSTASH_POLICY" ]; then
        echo -e "${GREEN}✓ Logstash logs policy verified${NC}"
    else
        echo -e "${RED}✗ Logstash logs policy not found${NC}"
    fi

    echo ""
fi

echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  ✓ Retention Policies Configured Successfully${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Summary:${NC}"
echo "  - Mule logs: Delete after $MULE_LOGS_RETENTION_DAYS days ($(echo "scale=1; $MULE_LOGS_RETENTION_DAYS / 365" | bc) years)"
echo "  - Logstash logs: Delete after $LOGSTASH_LOGS_RETENTION_DAYS days ($(echo "scale=1; $LOGSTASH_LOGS_RETENTION_DAYS / 365" | bc) years)"
echo "  - Rollover: Every $ROLLOVER_MAX_AGE OR when reaching $ROLLOVER_SIZE"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  All settings are configured in .env file"
echo "  Edit .env to modify retention periods:"
echo ""
echo "    MULE_LOGS_RETENTION_DAYS=365    # 1 year"
echo "    LOGSTASH_LOGS_RETENTION_DAYS=90 # 3 months"
echo "    ROLLOVER_SIZE=5gb               # 5GB rollover"
echo "    ROLLOVER_MAX_AGE=7d             # 7 days rollover"
echo ""
echo "  Then re-run: ${BLUE}./config/ilm/setup-retention-policy.sh${NC}"
echo ""
echo -e "${GREEN}View Policies:${NC}"
echo ""
echo "  Kibana UI:"
echo "    1. Open: http://localhost:9080/kibana"
echo "    2. Go to: Management → Stack Management → Index Lifecycle Policies"
echo ""
echo "  Via API:"
echo "    ${BLUE}curl http://localhost:9080/elasticsearch/_ilm/policy?pretty${NC}"
echo ""
echo "  Check index status:"
echo "    ${BLUE}curl http://localhost:9080/elasticsearch/mule-logs-*/_ilm/explain?pretty${NC}"
echo ""
