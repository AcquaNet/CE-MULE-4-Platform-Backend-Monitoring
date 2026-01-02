#!/bin/bash
#
# Create ElasticSearch Snapshot Backup
#
# This script creates a snapshot of ElasticSearch indices based on settings
# in the .env file. Can be run manually or via cron for automated backups.
#
# Usage:
#   ./config/backup/backup.sh [snapshot_name]
#
# If snapshot_name is not provided, it will be auto-generated based on timestamp.
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

# Load environment variables from .env
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: .env file not found at $ENV_FILE${NC}"
    echo ""
    echo "Please create .env file first:"
    echo "  cp .env.example .env"
    echo "  ./config/backup/generate-secrets.sh"
    exit 1
fi

# Source the .env file
set -a
source "$ENV_FILE"
set +a

# Check if backups are enabled
if [ "${BACKUP_ENABLED:-true}" != "true" ]; then
    echo -e "${YELLOW}Warning: Backups are disabled in .env (BACKUP_ENABLED=false)${NC}"
    exit 0
fi

# ElasticSearch connection details
ES_HOST="${ES_HOST:-http://localhost:9080/elasticsearch}"
ES_USER="${ES_USER:-elastic}"
ES_PASSWORD="${ELASTIC_PASSWORD}"
REPO_NAME="${BACKUP_REPOSITORY_NAME:-backup-repo}"

# Snapshot name (auto-generate if not provided)
SNAPSHOT_NAME="${1:-snapshot-$(date +%Y%m%d-%H%M%S)}"

# Backup settings
BACKUP_MODE="${BACKUP_INDICES:-daily}"
EXCLUDE_INDICES="${BACKUP_EXCLUDE_INDICES:-.monitoring-*,.watcher-*,.security-*}"
VERIFY="${BACKUP_VERIFY:-true}"

# Determine which indices to backup
if [ "$BACKUP_MODE" = "daily" ]; then
    # Backup only today's indices (compartmentalized daily backups)
    TODAY=$(date +%Y.%m.%d)
    INDICES="mule-logs-${TODAY},logstash-${TODAY}"
    echo -e "${YELLOW}Mode: Daily compartmentalized backup${NC}"
    echo -e "${YELLOW}Backing up only today's indices: ${TODAY}${NC}"
    echo ""
elif [ "$BACKUP_MODE" = "*" ]; then
    # Backup all indices (legacy mode - creates interdependent snapshots)
    INDICES="*"
    echo -e "${YELLOW}Mode: Full backup (all indices)${NC}"
    echo -e "${YELLOW}Warning: This creates interdependent snapshots. Consider using 'daily' mode.${NC}"
    echo ""
else
    # Custom indices pattern from .env
    INDICES="$BACKUP_MODE"
    echo -e "${YELLOW}Mode: Custom indices pattern${NC}"
    echo ""
fi

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   ElasticSearch Snapshot Backup${NC}"
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
    echo ""
    echo "Configure the repository first:"
    echo "  ./config/backup/configure-backup.sh"
    exit 1
fi
echo -e "${GREEN}✓ Repository '${REPO_NAME}' found${NC}"
echo ""

# Display backup settings
echo -e "${YELLOW}Backup Configuration:${NC}"
echo "  Snapshot Name: ${SNAPSHOT_NAME}"
echo "  Repository: ${REPO_NAME}"
echo "  Include Indices: ${INDICES}"
echo "  Exclude Indices: ${EXCLUDE_INDICES}"
echo "  Verify: ${VERIFY}"
echo ""

# Get cluster health
CLUSTER_HEALTH=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_cluster/health" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
echo "  Cluster Status: ${CLUSTER_HEALTH}"

if [ "$CLUSTER_HEALTH" = "red" ]; then
    echo -e "${RED}Warning: Cluster is in RED state. Backup may fail or be incomplete.${NC}"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Backup cancelled."
        exit 0
    fi
fi
echo ""

# Create snapshot
echo -e "${GREEN}Creating snapshot '${SNAPSHOT_NAME}'...${NC}"
START_TIME=$(date +%s)

# Build the snapshot request JSON
SNAPSHOT_REQUEST=$(cat <<EOF
{
  "indices": "${INDICES}",
  "ignore_unavailable": true,
  "include_global_state": false,
  "metadata": {
    "taken_by": "backup.sh",
    "taken_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "client": "${CLIENT_NAME:-unknown}",
    "environment": "${ENVIRONMENT:-development}"
  }
}
EOF
)

# Add exclude_indices if specified
if [ -n "$EXCLUDE_INDICES" ]; then
    SNAPSHOT_REQUEST=$(echo "$SNAPSHOT_REQUEST" | sed "s/\"include_global_state\":/\"exclude_indices\": \"${EXCLUDE_INDICES}\",\n  \"include_global_state\":/")
fi

# Execute snapshot creation
RESPONSE=$(curl -s -X PUT -u "${ES_USER}:${ES_PASSWORD}" \
    "${ES_HOST}/_snapshot/${REPO_NAME}/${SNAPSHOT_NAME}?wait_for_completion=false" \
    -H 'Content-Type: application/json' \
    -d "$SNAPSHOT_REQUEST")

# Check for errors
if echo "$RESPONSE" | grep -q "\"error\""; then
    echo -e "${RED}Error creating snapshot:${NC}"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    exit 1
fi

# Check if snapshot was accepted
if echo "$RESPONSE" | grep -q "\"accepted\":true"; then
    echo -e "${GREEN}✓ Snapshot creation started${NC}"
else
    echo -e "${YELLOW}Warning: Unexpected response:${NC}"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
fi
echo ""

# Wait for snapshot to complete
echo -e "${GREEN}Waiting for snapshot to complete...${NC}"
echo "(This may take a while depending on data size)"
echo ""

SNAPSHOT_STATE="IN_PROGRESS"
DOTS=0

while [ "$SNAPSHOT_STATE" = "IN_PROGRESS" ]; do
    sleep 5

    # Get snapshot status
    STATUS_RESPONSE=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" \
        "${ES_HOST}/_snapshot/${REPO_NAME}/${SNAPSHOT_NAME}")

    SNAPSHOT_STATE=$(echo "$STATUS_RESPONSE" | grep -o '"state":"[^"]*"' | head -1 | cut -d'"' -f4)

    # Show progress dots
    printf "."
    DOTS=$((DOTS + 1))

    if [ $DOTS -ge 60 ]; then
        echo ""
        DOTS=0
    fi
done

echo ""
echo ""

# Calculate duration
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
DURATION_MIN=$((DURATION / 60))
DURATION_SEC=$((DURATION % 60))

# Check final state
if [ "$SNAPSHOT_STATE" = "SUCCESS" ]; then
    echo -e "${GREEN}✓ Snapshot completed successfully${NC}"
    echo ""
    echo "  Duration: ${DURATION_MIN}m ${DURATION_SEC}s"

    # Get snapshot details
    SNAPSHOT_INFO=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" \
        "${ES_HOST}/_snapshot/${REPO_NAME}/${SNAPSHOT_NAME}")

    # Extract statistics
    TOTAL_SHARDS=$(echo "$SNAPSHOT_INFO" | grep -o '"total_shards":[0-9]*' | cut -d':' -f2)
    SUCCESSFUL_SHARDS=$(echo "$SNAPSHOT_INFO" | grep -o '"successful_shards":[0-9]*' | cut -d':' -f2)
    FAILED_SHARDS=$(echo "$SNAPSHOT_INFO" | grep -o '"failed_shards":[0-9]*' | cut -d':' -f2)

    echo "  Total Shards: ${TOTAL_SHARDS}"
    echo "  Successful: ${SUCCESSFUL_SHARDS}"
    echo "  Failed: ${FAILED_SHARDS}"
    echo ""

    # Verify snapshot if enabled
    if [ "${VERIFY}" = "true" ]; then
        echo -e "${GREEN}Verifying snapshot integrity...${NC}"

        VERIFY_RESPONSE=$(curl -s -X POST -u "${ES_USER}:${ES_PASSWORD}" \
            "${ES_HOST}/_snapshot/${REPO_NAME}/${SNAPSHOT_NAME}/_verify")

        if echo "$VERIFY_RESPONSE" | grep -q "error"; then
            echo -e "${YELLOW}Warning: Snapshot verification encountered issues${NC}"
            echo "$VERIFY_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$VERIFY_RESPONSE"
        else
            echo -e "${GREEN}✓ Snapshot verified successfully${NC}"
        fi
        echo ""
    fi

    # Send notification if enabled
    if [ "${BACKUP_NOTIFICATIONS_ENABLED:-false}" = "true" ] && [ -n "${BACKUP_WEBHOOK_URL}" ]; then
        echo -e "${GREEN}Sending success notification...${NC}"

        NOTIFICATION_PAYLOAD=$(cat <<EOF
{
  "text": "✅ ElasticSearch Backup Successful",
  "attachments": [
    {
      "color": "good",
      "fields": [
        {"title": "Snapshot", "value": "${SNAPSHOT_NAME}", "short": true},
        {"title": "Repository", "value": "${REPO_NAME}", "short": true},
        {"title": "Duration", "value": "${DURATION_MIN}m ${DURATION_SEC}s", "short": true},
        {"title": "Shards", "value": "${SUCCESSFUL_SHARDS}/${TOTAL_SHARDS}", "short": true},
        {"title": "Client", "value": "${CLIENT_NAME:-unknown}", "short": true},
        {"title": "Environment", "value": "${ENVIRONMENT:-development}", "short": true}
      ]
    }
  ]
}
EOF
)

        curl -s -X POST "${BACKUP_WEBHOOK_URL}" \
            -H 'Content-Type: application/json' \
            -d "$NOTIFICATION_PAYLOAD" > /dev/null

        echo -e "${GREEN}✓ Notification sent${NC}"
        echo ""
    fi

    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  Backup Complete${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "Snapshot: ${SNAPSHOT_NAME}"
    echo "Repository: ${REPO_NAME}"
    echo ""
    echo "To restore this snapshot:"
    echo "  ${BLUE}./config/backup/restore.sh ${SNAPSHOT_NAME}${NC}"
    echo ""

    exit 0

elif [ "$SNAPSHOT_STATE" = "FAILED" ]; then
    echo -e "${RED}✗ Snapshot failed${NC}"
    echo ""

    # Get failure details
    SNAPSHOT_INFO=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" \
        "${ES_HOST}/_snapshot/${REPO_NAME}/${SNAPSHOT_NAME}")

    echo "Failure details:"
    echo "$SNAPSHOT_INFO" | python3 -m json.tool 2>/dev/null || echo "$SNAPSHOT_INFO"
    echo ""

    # Send failure notification if enabled
    if [ "${BACKUP_NOTIFICATIONS_ENABLED:-false}" = "true" ] && [ -n "${BACKUP_WEBHOOK_URL}" ]; then
        NOTIFICATION_PAYLOAD=$(cat <<EOF
{
  "text": "❌ ElasticSearch Backup Failed",
  "attachments": [
    {
      "color": "danger",
      "fields": [
        {"title": "Snapshot", "value": "${SNAPSHOT_NAME}", "short": true},
        {"title": "Repository", "value": "${REPO_NAME}", "short": true},
        {"title": "Client", "value": "${CLIENT_NAME:-unknown}", "short": true},
        {"title": "Environment", "value": "${ENVIRONMENT:-development}", "short": true}
      ]
    }
  ]
}
EOF
)

        curl -s -X POST "${BACKUP_WEBHOOK_URL}" \
            -H 'Content-Type: application/json' \
            -d "$NOTIFICATION_PAYLOAD" > /dev/null
    fi

    exit 1

else
    echo -e "${YELLOW}Warning: Unknown snapshot state: ${SNAPSHOT_STATE}${NC}"
    exit 1
fi
