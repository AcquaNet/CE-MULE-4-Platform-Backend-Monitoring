#!/bin/bash
#
# Configure ElasticSearch Snapshot Repository
#
# This script configures the ElasticSearch snapshot repository based on settings
# in the .env file. It supports filesystem, S3, Azure, and GCS repositories.
#
# Usage:
#   ./config/backup/configure-backup.sh
#
# Options:
#   --force    Delete and recreate repository if it already exists
#   --verify   Verify repository after creation
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
FORCE=false
VERIFY=false

for arg in "$@"; do
    case $arg in
        --force)
            FORCE=true
            shift
            ;;
        --verify)
            VERIFY=true
            shift
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--force] [--verify]"
            exit 1
            ;;
    esac
done

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

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   ElasticSearch Snapshot Repository Configuration${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Check if backups are enabled
if [ "${BACKUP_ENABLED:-true}" != "true" ]; then
    echo -e "${YELLOW}Warning: Backups are disabled in .env (BACKUP_ENABLED=false)${NC}"
    read -p "Do you want to continue anyway? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Configuration cancelled."
        exit 0
    fi
fi

# ElasticSearch connection details
ES_HOST="${ES_HOST:-http://localhost:9080/elasticsearch}"
ES_USER="${ES_USER:-elastic}"
ES_PASSWORD="${ELASTIC_PASSWORD}"
REPO_NAME="${BACKUP_REPOSITORY_NAME:-backup-repo}"
REPO_TYPE="${BACKUP_REPOSITORY_TYPE:-fs}"

# Check ElasticSearch connectivity
echo -e "${GREEN}Checking ElasticSearch connectivity...${NC}"
if ! curl -s -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_cluster/health" > /dev/null 2>&1; then
    echo -e "${RED}Error: Cannot connect to ElasticSearch at ${ES_HOST}${NC}"
    echo ""
    echo "Please ensure:"
    echo "  1. ElasticSearch is running: docker-compose ps elasticsearch"
    echo "  2. ELASTIC_PASSWORD is set correctly in .env"
    echo "  3. ES_HOST is correct (default: http://localhost:9080/elasticsearch)"
    exit 1
fi
echo -e "${GREEN}✓ Connected to ElasticSearch${NC}"
echo ""

# Check if repository already exists
REPO_EXISTS=$(curl -s -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_snapshot/${REPO_NAME}" | grep -c "\"${REPO_NAME}\"" || true)

if [ "$REPO_EXISTS" -gt 0 ]; then
    echo -e "${YELLOW}Repository '${REPO_NAME}' already exists${NC}"

    if [ "$FORCE" = true ]; then
        echo -e "${YELLOW}Deleting existing repository...${NC}"
        curl -s -X DELETE -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_snapshot/${REPO_NAME}" > /dev/null
        echo -e "${GREEN}✓ Repository deleted${NC}"
    else
        echo ""
        echo "Use --force to delete and recreate the repository"
        exit 0
    fi
fi

# Configure repository based on type
echo -e "${GREEN}Configuring ${REPO_TYPE} repository...${NC}"

case "$REPO_TYPE" in
    fs)
        # Filesystem repository
        REPO_PATH="${SNAPSHOT_REPOSITORY_PATH:-/mnt/elasticsearch-backups}"
        COMPRESS="${BACKUP_COMPRESS:-true}"

        echo "  Repository: ${REPO_NAME}"
        echo "  Type: Filesystem"
        echo "  Location: ${REPO_PATH}"
        echo "  Compress: ${COMPRESS}"
        echo ""

        # Create repository
        RESPONSE=$(curl -s -X PUT -u "${ES_USER}:${ES_PASSWORD}" \
            "${ES_HOST}/_snapshot/${REPO_NAME}" \
            -H 'Content-Type: application/json' \
            -d "{
                \"type\": \"fs\",
                \"settings\": {
                    \"location\": \"${REPO_PATH}\",
                    \"compress\": ${COMPRESS}
                }
            }")
        ;;

    s3)
        # AWS S3 repository
        if [ -z "$AWS_S3_BUCKET" ]; then
            echo -e "${RED}Error: AWS_S3_BUCKET not set in .env${NC}"
            exit 1
        fi

        S3_BUCKET="${AWS_S3_BUCKET}"
        S3_REGION="${AWS_S3_REGION:-us-east-1}"
        S3_BASE_PATH="${AWS_S3_BASE_PATH:-elasticsearch-backups}"
        S3_STORAGE_CLASS="${AWS_S3_STORAGE_CLASS:-STANDARD_IA}"
        COMPRESS="${BACKUP_COMPRESS:-true}"

        echo "  Repository: ${REPO_NAME}"
        echo "  Type: AWS S3"
        echo "  Bucket: ${S3_BUCKET}"
        echo "  Region: ${S3_REGION}"
        echo "  Base Path: ${S3_BASE_PATH}"
        echo "  Storage Class: ${S3_STORAGE_CLASS}"
        echo "  Compress: ${COMPRESS}"
        echo ""

        # Create repository
        RESPONSE=$(curl -s -X PUT -u "${ES_USER}:${ES_PASSWORD}" \
            "${ES_HOST}/_snapshot/${REPO_NAME}" \
            -H 'Content-Type: application/json' \
            -d "{
                \"type\": \"s3\",
                \"settings\": {
                    \"bucket\": \"${S3_BUCKET}\",
                    \"region\": \"${S3_REGION}\",
                    \"base_path\": \"${S3_BASE_PATH}\",
                    \"storage_class\": \"${S3_STORAGE_CLASS}\",
                    \"compress\": ${COMPRESS}
                }
            }")
        ;;

    azure)
        # Azure Blob repository
        if [ -z "$AZURE_STORAGE_ACCOUNT" ] || [ -z "$AZURE_CONTAINER" ]; then
            echo -e "${RED}Error: AZURE_STORAGE_ACCOUNT and AZURE_CONTAINER must be set in .env${NC}"
            exit 1
        fi

        CONTAINER="${AZURE_CONTAINER}"
        BASE_PATH="${AZURE_BASE_PATH:-}"
        COMPRESS="${BACKUP_COMPRESS:-true}"

        echo "  Repository: ${REPO_NAME}"
        echo "  Type: Azure Blob"
        echo "  Account: ${AZURE_STORAGE_ACCOUNT}"
        echo "  Container: ${CONTAINER}"
        echo "  Base Path: ${BASE_PATH}"
        echo "  Compress: ${COMPRESS}"
        echo ""

        # Create repository
        RESPONSE=$(curl -s -X PUT -u "${ES_USER}:${ES_PASSWORD}" \
            "${ES_HOST}/_snapshot/${REPO_NAME}" \
            -H 'Content-Type: application/json' \
            -d "{
                \"type\": \"azure\",
                \"settings\": {
                    \"container\": \"${CONTAINER}\",
                    \"base_path\": \"${BASE_PATH}\",
                    \"compress\": ${COMPRESS}
                }
            }")
        ;;

    gcs)
        # Google Cloud Storage repository
        if [ -z "$GCS_BUCKET" ]; then
            echo -e "${RED}Error: GCS_BUCKET not set in .env${NC}"
            exit 1
        fi

        BUCKET="${GCS_BUCKET}"
        BASE_PATH="${GCS_BASE_PATH:-elasticsearch-backups}"
        COMPRESS="${BACKUP_COMPRESS:-true}"

        echo "  Repository: ${REPO_NAME}"
        echo "  Type: Google Cloud Storage"
        echo "  Bucket: ${BUCKET}"
        echo "  Base Path: ${BASE_PATH}"
        echo "  Compress: ${COMPRESS}"
        echo ""

        # Create repository
        RESPONSE=$(curl -s -X PUT -u "${ES_USER}:${ES_PASSWORD}" \
            "${ES_HOST}/_snapshot/${REPO_NAME}" \
            -H 'Content-Type: application/json' \
            -d "{
                \"type\": \"gcs\",
                \"settings\": {
                    \"bucket\": \"${BUCKET}\",
                    \"base_path\": \"${BASE_PATH}\",
                    \"compress\": ${COMPRESS}
                }
            }")
        ;;

    *)
        echo -e "${RED}Error: Unsupported repository type: ${REPO_TYPE}${NC}"
        echo "Supported types: fs, s3, azure, gcs"
        exit 1
        ;;
esac

# Check for errors in response
if echo "$RESPONSE" | grep -q "\"error\""; then
    echo -e "${RED}Error creating repository:${NC}"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓ Repository created successfully${NC}"
echo ""

# Verify repository
if [ "$VERIFY" = true ] || [ "${BACKUP_VERIFY:-true}" = "true" ]; then
    echo -e "${GREEN}Verifying repository...${NC}"

    VERIFY_RESPONSE=$(curl -s -X POST -u "${ES_USER}:${ES_PASSWORD}" \
        "${ES_HOST}/_snapshot/${REPO_NAME}/_verify")

    if echo "$VERIFY_RESPONSE" | grep -q "\"nodes\""; then
        NODE_COUNT=$(echo "$VERIFY_RESPONSE" | grep -o "\"nodes\":{" | wc -l)
        echo -e "${GREEN}✓ Repository verified on ${NODE_COUNT} node(s)${NC}"
    else
        echo -e "${YELLOW}Warning: Repository verification failed${NC}"
        echo "$VERIFY_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$VERIFY_RESPONSE"
    fi
    echo ""
fi

# Display repository info
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Repository Configuration Complete${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Repository Details:${NC}"
curl -s -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_snapshot/${REPO_NAME}" | python3 -m json.tool 2>/dev/null || \
    curl -s -u "${ES_USER}:${ES_PASSWORD}" "${ES_HOST}/_snapshot/${REPO_NAME}"
echo ""
echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo ""
echo "  1. Create a manual backup:"
echo "     ${BLUE}./config/backup/backup.sh${NC}"
echo ""
echo "  2. Set up automated backups (cron job):"
echo "     ${BLUE}./config/backup/setup-backup-cron.sh${NC}"
echo ""
echo "  3. View existing snapshots:"
echo "     ${BLUE}curl -u ${ES_USER}:****** \"${ES_HOST}/_snapshot/${REPO_NAME}/_all?pretty\"${NC}"
echo ""
echo "  4. Restore from a snapshot:"
echo "     ${BLUE}./config/backup/restore.sh <snapshot_name>${NC}"
echo ""
