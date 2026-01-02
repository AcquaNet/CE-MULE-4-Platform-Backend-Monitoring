#!/bin/bash
#
# Clean Up Old ElasticSearch Snapshots
#
# This script removes old snapshots based on retention policy defined in .env
# Can be run manually or via cron for automated cleanup.
#
# Usage:
#   ./config/backup/backup-cleanup.sh
#
# Options:
#   --dry-run    Show what would be deleted without actually deleting
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
DRY_RUN=false

for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--dry-run]"
            exit 1
            ;;
    esac
done

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

# Retention settings
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
MAX_COUNT="${BACKUP_MAX_COUNT:-50}"

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   ElasticSearch Snapshot Cleanup${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}DRY RUN MODE - No snapshots will be deleted${NC}"
    echo ""
fi

# Check ElasticSearch connectivity
echo -e "${GREEN}Checking ElasticSearch connectivity...${NC}"
if ! curl -s -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_cluster/health" > /dev/null 2>&1; then
    echo -e "${RED}Error: Cannot connect to ElasticSearch at ${ES_HOST}${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Connected to ElasticSearch${NC}"
echo ""

# Check if repository exists
REPO_EXISTS=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_snapshot/${REPO_NAME}" | grep -c "\"${REPO_NAME}\"" || true)

if [ "$REPO_EXISTS" -eq 0 ]; then
    echo -e "${RED}Error: Repository '${REPO_NAME}' does not exist${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Repository '${REPO_NAME}' found${NC}"
echo ""

# Get all snapshots
echo -e "${GREEN}Fetching snapshot list...${NC}"
ALL_SNAPSHOTS=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" \
    "${ES_HOST}/_snapshot/${REPO_NAME}/_all")

# Extract snapshot names and start times
SNAPSHOT_LIST=$(echo "$ALL_SNAPSHOTS" | grep -o '"snapshot":"[^"]*","uuid":"[^"]*","[^"]*","[^"]*","start_time":"[^"]*","start_time_in_millis":[0-9]*' | \
    awk -F'"' '{print $4","$18}' || true)

if [ -z "$SNAPSHOT_LIST" ]; then
    echo -e "${YELLOW}No snapshots found in repository${NC}"
    exit 0
fi

# Count snapshots
TOTAL_SNAPSHOTS=$(echo "$SNAPSHOT_LIST" | wc -l)
echo -e "${GREEN}✓ Found ${TOTAL_SNAPSHOTS} snapshot(s)${NC}"
echo ""

# Calculate cutoff date
CUTOFF_DATE=$(date -d "${RETENTION_DAYS} days ago" +%s)000  # Convert to milliseconds

# Display retention policy
echo -e "${YELLOW}Retention Policy:${NC}"
echo "  Maximum Age: ${RETENTION_DAYS} days"
echo "  Maximum Count: ${MAX_COUNT}"
echo "  Cutoff Date: $(date -d "${RETENTION_DAYS} days ago" '+%Y-%m-%d %H:%M:%S')"
echo ""

# Find snapshots to delete
TO_DELETE=()
TO_KEEP=()

while IFS=',' read -r snapshot_name snapshot_time; do
    # Check if snapshot is older than retention period
    if [ "$snapshot_time" -lt "$CUTOFF_DATE" ]; then
        TO_DELETE+=("$snapshot_name")
    else
        TO_KEEP+=("$snapshot_name")
    fi
done <<< "$SNAPSHOT_LIST"

# Also delete excess snapshots if count exceeds maximum
KEEP_COUNT=${#TO_KEEP[@]}

if [ "$KEEP_COUNT" -gt "$MAX_COUNT" ]; then
    EXCESS=$((KEEP_COUNT - MAX_COUNT))
    echo -e "${YELLOW}Warning: Keeping ${KEEP_COUNT} snapshots exceeds maximum of ${MAX_COUNT}${NC}"
    echo "  Will delete ${EXCESS} oldest snapshots to enforce count limit"
    echo ""

    # Sort TO_KEEP by timestamp and move oldest to TO_DELETE
    # This is a simplified approach - in production you'd want more sophisticated sorting
    for ((i=0; i<EXCESS; i++)); do
        TO_DELETE+=("${TO_KEEP[$i]}")
        unset 'TO_KEEP[$i]'
    done

    # Reindex TO_KEEP array
    TO_KEEP=("${TO_KEEP[@]}")
fi

# Display results
DELETE_COUNT=${#TO_DELETE[@]}
KEEP_COUNT=${#TO_KEEP[@]}

echo -e "${GREEN}Snapshots to keep: ${KEEP_COUNT}${NC}"
if [ "$KEEP_COUNT" -gt 0 ] && [ "$KEEP_COUNT" -le 10 ]; then
    for snapshot in "${TO_KEEP[@]}"; do
        echo "  ✓ $snapshot"
    done
    echo ""
elif [ "$KEEP_COUNT" -gt 10 ]; then
    echo "  (${KEEP_COUNT} snapshots - list truncated)"
    echo ""
fi

echo -e "${YELLOW}Snapshots to delete: ${DELETE_COUNT}${NC}"
if [ "$DELETE_COUNT" -gt 0 ]; then
    for snapshot in "${TO_DELETE[@]}"; do
        echo "  ✗ $snapshot"
    done
    echo ""
else
    echo "  No snapshots to delete"
    echo ""
    exit 0
fi

# Confirm deletion
if [ "$DRY_RUN" != true ]; then
    read -p "Delete ${DELETE_COUNT} snapshot(s)? (yes/no): " CONFIRM

    if [ "$CONFIRM" != "yes" ]; then
        echo "Cleanup cancelled."
        exit 0
    fi
    echo ""
fi

# Delete snapshots
DELETED=0
FAILED=0

for snapshot in "${TO_DELETE[@]}"; do
    if [ "$DRY_RUN" = true ]; then
        echo -e "${BLUE}[DRY RUN] Would delete: ${snapshot}${NC}"
        DELETED=$((DELETED + 1))
    else
        echo -e "${GREEN}Deleting: ${snapshot}${NC}"

        RESPONSE=$(curl -s -X DELETE -u "${ES_USER}:${ES_PASSWORD}" \
            "${ES_HOST}/_snapshot/${REPO_NAME}/${snapshot}")

        if echo "$RESPONSE" | grep -q "\"acknowledged\":true"; then
            echo -e "${GREEN}✓ Deleted${NC}"
            DELETED=$((DELETED + 1))
        else
            echo -e "${RED}✗ Failed${NC}"
            echo "$RESPONSE"
            FAILED=$((FAILED + 1))
        fi
    fi
done

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Cleanup Complete${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN Summary:"
    echo "  Would delete: ${DELETE_COUNT} snapshot(s)"
    echo "  Would keep: ${KEEP_COUNT} snapshot(s)"
else
    echo "Summary:"
    echo "  Deleted: ${DELETED} snapshot(s)"
    echo "  Failed: ${FAILED} snapshot(s)"
    echo "  Remaining: ${KEEP_COUNT} snapshot(s)"
fi
echo ""

# Send notification if enabled (only for actual deletions)
if [ "$DRY_RUN" != true ] && [ "$DELETED" -gt 0 ]; then
    if [ "${BACKUP_NOTIFICATIONS_ENABLED:-false}" = "true" ] && [ -n "${BACKUP_WEBHOOK_URL}" ]; then
        NOTIFICATION_PAYLOAD=$(cat <<EOF
{
  "text": "🗑️ ElasticSearch Backup Cleanup",
  "attachments": [
    {
      "color": "warning",
      "fields": [
        {"title": "Deleted", "value": "${DELETED}", "short": true},
        {"title": "Remaining", "value": "${KEEP_COUNT}", "short": true},
        {"title": "Repository", "value": "${REPO_NAME}", "short": true},
        {"title": "Retention", "value": "${RETENTION_DAYS} days", "short": true}
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
fi

exit 0
