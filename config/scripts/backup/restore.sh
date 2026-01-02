#!/bin/bash
#
# Restore ElasticSearch Snapshot
#
# This script restores indices from an ElasticSearch snapshot.
#
# Usage:
#   ./config/backup/restore.sh <snapshot_name> [indices_pattern]
#
# Examples:
#   ./config/backup/restore.sh snapshot-20241228-120000
#   ./config/backup/restore.sh snapshot-20241228-120000 "mule-logs-*"
#   ./config/backup/restore.sh snapshot-20241228-120000 "mule-logs-2024.12.28"
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

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 <snapshot_name> [indices_pattern]"
    echo ""
    echo "Examples:"
    echo "  $0 snapshot-20241228-120000"
    echo "  $0 snapshot-20241228-120000 \"mule-logs-*\""
    echo "  $0 snapshot-20241228-120000 \"mule-logs-2024.12.28\""
    exit 1
fi

SNAPSHOT_NAME="$1"
INDICES_PATTERN="${2:-*}"

# Load environment variables from .env
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: .env file not found at $ENV_FILE${NC}"
    exit 1
fi

# Source the .env file
set -a
source "$ENV_FILE"
set +a

# ElasticSearch connection details
ES_HOST="${ES_HOST:-http://localhost:9080/elasticsearch}"
ES_USER="${ES_USER:-elastic}"
ES_PASSWORD="${ELASTIC_PASSWORD}"
REPO_NAME="${BACKUP_REPOSITORY_NAME:-backup-repo}"

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   ElasticSearch Snapshot Restore${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Check ElasticSearch connectivity
echo -e "${GREEN}Checking ElasticSearch connectivity...${NC}"
if ! curl -s -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_cluster/health" > /dev/null 2>&1; then
    echo -e "${RED}Error: Cannot connect to ElasticSearch at ${ES_HOST}${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Connected to ElasticSearch${NC}"
echo ""

# Check if repository exists
echo -e "${GREEN}Checking snapshot repository...${NC}"
REPO_EXISTS=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_snapshot/${REPO_NAME}" | grep -c "\"${REPO_NAME}\"" || true)

if [ "$REPO_EXISTS" -eq 0 ]; then
    echo -e "${RED}Error: Repository '${REPO_NAME}' does not exist${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Repository '${REPO_NAME}' found${NC}"
echo ""

# Check if snapshot exists
echo -e "${GREEN}Checking snapshot '${SNAPSHOT_NAME}'...${NC}"
SNAPSHOT_INFO=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" \
    "${ES_HOST}/_snapshot/${REPO_NAME}/${SNAPSHOT_NAME}")

if echo "$SNAPSHOT_INFO" | grep -q "\"error\""; then
    echo -e "${RED}Error: Snapshot '${SNAPSHOT_NAME}' not found${NC}"
    echo ""
    echo "Available snapshots:"
    curl -s -u "${ES_USER}:${ES_PASSWORD}" \
        "${ES_HOST}/_snapshot/${REPO_NAME}/_all" | \
        grep -o '"snapshot":"[^"]*"' | cut -d'"' -f4
    exit 1
fi
echo -e "${GREEN}✓ Snapshot found${NC}"
echo ""

# Display snapshot information
echo -e "${YELLOW}Snapshot Information:${NC}"
SNAPSHOT_STATE=$(echo "$SNAPSHOT_INFO" | grep -o '"state":"[^"]*"' | cut -d'"' -f4)
SNAPSHOT_START=$(echo "$SNAPSHOT_INFO" | grep -o '"start_time":"[^"]*"' | cut -d'"' -f4)
SNAPSHOT_END=$(echo "$SNAPSHOT_INFO" | grep -o '"end_time":"[^"]*"' | cut -d'"' -f4)

echo "  Snapshot: ${SNAPSHOT_NAME}"
echo "  State: ${SNAPSHOT_STATE}"
echo "  Start Time: ${SNAPSHOT_START}"
echo "  End Time: ${SNAPSHOT_END}"
echo ""

# Get indices in snapshot
echo -e "${GREEN}Indices in snapshot:${NC}"
INDICES_JSON=$(echo "$SNAPSHOT_INFO" | grep -o '"indices":\[[^]]*\]' | sed 's/"indices"://')
echo "$INDICES_JSON" | python3 -m json.tool 2>/dev/null || echo "$INDICES_JSON"
echo ""

# Restore configuration
echo -e "${YELLOW}Restore Configuration:${NC}"
echo "  Indices Pattern: ${INDICES_PATTERN}"
echo ""

# Warning about existing indices
echo -e "${RED}WARNING: This will restore indices from the snapshot.${NC}"
echo -e "${RED}Existing indices with the same names will be closed during restore.${NC}"
echo ""
read -p "Do you want to continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi
echo ""

# Build restore request
RESTORE_REQUEST=$(cat <<EOF
{
  "indices": "${INDICES_PATTERN}",
  "ignore_unavailable": true,
  "include_global_state": false,
  "rename_pattern": "(.+)",
  "rename_replacement": "\$1",
  "include_aliases": true
}
EOF
)

echo -e "${GREEN}Starting restore operation...${NC}"
START_TIME=$(date +%s)

# Execute restore
RESPONSE=$(curl -s -X POST -u "${ES_USER}:${ES_PASSWORD}" \
    "${ES_HOST}/_snapshot/${REPO_NAME}/${SNAPSHOT_NAME}/_restore?wait_for_completion=false" \
    -H 'Content-Type: application/json' \
    -d "$RESTORE_REQUEST")

# Check for errors
if echo "$RESPONSE" | grep -q "\"error\""; then
    echo -e "${RED}Error during restore:${NC}"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    exit 1
fi

# Check if restore was accepted
if echo "$RESPONSE" | grep -q "\"accepted\":true"; then
    echo -e "${GREEN}✓ Restore operation started${NC}"
else
    echo -e "${YELLOW}Warning: Unexpected response:${NC}"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
fi
echo ""

# Wait for restore to complete
echo -e "${GREEN}Waiting for restore to complete...${NC}"
echo "(This may take a while depending on data size)"
echo ""

RESTORE_COMPLETE=false
DOTS=0

while [ "$RESTORE_COMPLETE" = false ]; do
    sleep 5

    # Check recovery status
    RECOVERY_STATUS=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" \
        "${ES_HOST}/_recovery?active_only=true")

    # If no active recoveries, restore is complete
    if [ -z "$RECOVERY_STATUS" ] || [ "$RECOVERY_STATUS" = "{}" ]; then
        RESTORE_COMPLETE=true
    else
        # Show progress dots
        printf "."
        DOTS=$((DOTS + 1))

        if [ $DOTS -ge 60 ]; then
            echo ""
            DOTS=0
        fi
    fi
done

echo ""
echo ""

# Calculate duration
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
DURATION_MIN=$((DURATION / 60))
DURATION_SEC=$((DURATION % 60))

echo -e "${GREEN}✓ Restore completed successfully${NC}"
echo ""
echo "  Duration: ${DURATION_MIN}m ${DURATION_SEC}s"
echo ""

# Show restored indices
echo -e "${GREEN}Restored indices:${NC}"
curl -s -u "${ES_USER}:${ES_PASSWORD}" \
    "${ES_HOST}/_cat/indices/${INDICES_PATTERN}?v&h=index,docs.count,store.size,health,status"
echo ""
echo ""

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Restore Complete${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Snapshot: ${SNAPSHOT_NAME}"
echo "Indices Pattern: ${INDICES_PATTERN}"
echo ""
echo "Verify data in Kibana:"
echo "  ${BLUE}http://localhost:9080/kibana${NC}"
echo ""
