#!/bin/bash
#
# Generate Secure Secrets for ELK Stack
#
# This script generates secure random passwords and keys for all ELK stack services.
# It creates or updates the .env file with cryptographically secure values.
#
# Usage:
#   ./scripts/generate-secrets.sh
#
# Options:
#   --force    Overwrite existing .env file without prompting
#   --dry-run  Show what would be generated without creating .env file
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
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

# Parse arguments
FORCE=false
DRY_RUN=false

for arg in "$@"; do
    case $arg in
        --force)
            FORCE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--force] [--dry-run]"
            exit 1
            ;;
    esac
done

# Functions to generate secure random values
generate_password_32() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-32
}

generate_password_48() {
    openssl rand -base64 48 | tr -d "=+/" | cut -c1-48
}

generate_hex_32() {
    openssl rand -hex 32
}

generate_uuid() {
    cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen 2>/dev/null || echo "$(openssl rand -hex 16)"
}

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   ELK Stack Secure Secrets Generator${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Check if .env.example exists
if [ ! -f "$ENV_EXAMPLE" ]; then
    echo -e "${RED}Error: .env.example not found at $ENV_EXAMPLE${NC}"
    exit 1
fi

# Check if .env already exists
if [ -f "$ENV_FILE" ] && [ "$FORCE" != true ] && [ "$DRY_RUN" != true ]; then
    echo -e "${YELLOW}Warning: .env file already exists at $ENV_FILE${NC}"
    echo ""
    read -p "Do you want to overwrite it? This will generate NEW passwords. (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Operation cancelled. Use --force to override.${NC}"
        exit 0
    fi
fi

# Generate all secrets
echo -e "${GREEN}Generating secure random passwords and keys...${NC}"
echo ""

ELASTIC_PASSWORD=$(generate_password_32)
KIBANA_PASSWORD=$(generate_password_32)
KIBANA_ENCRYPTION_KEY=$(generate_password_48)
KIBANA_REPORTING_ENCRYPTION_KEY=$(generate_password_48)
APISIX_ADMIN_KEY=$(generate_hex_32)
APISIX_DASHBOARD_PASSWORD=$(generate_password_32)
GRAFANA_ADMIN_PASSWORD=$(generate_password_32)
GRAFANA_SECRET_KEY=$(generate_password_32)
APM_SECRET_TOKEN=$(generate_password_32)

# Display generated secrets (if dry-run)
if [ "$DRY_RUN" = true ]; then
    echo -e "${BLUE}Generated secrets (dry-run, not saved):${NC}"
    echo ""
    echo "ELASTIC_PASSWORD=$ELASTIC_PASSWORD"
    echo "KIBANA_PASSWORD=$KIBANA_PASSWORD"
    echo "KIBANA_ENCRYPTION_KEY=$KIBANA_ENCRYPTION_KEY"
    echo "KIBANA_REPORTING_ENCRYPTION_KEY=$KIBANA_REPORTING_ENCRYPTION_KEY"
    echo "APISIX_ADMIN_KEY=$APISIX_ADMIN_KEY"
    echo "APISIX_DASHBOARD_PASSWORD=$APISIX_DASHBOARD_PASSWORD"
    echo "GRAFANA_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD"
    echo "GRAFANA_SECRET_KEY=$GRAFANA_SECRET_KEY"
    echo "APM_SECRET_TOKEN=$APM_SECRET_TOKEN"
    echo ""
    echo -e "${BLUE}Dry-run complete. No files were modified.${NC}"
    exit 0
fi

# Create .env from .env.example and replace placeholders
echo -e "${GREEN}Creating .env file from template...${NC}"

cp "$ENV_EXAMPLE" "$ENV_FILE"

# Replace CHANGE_ME_PLEASE placeholders with generated values
sed -i "s|ELASTIC_PASSWORD=CHANGE_ME_PLEASE|ELASTIC_PASSWORD=$ELASTIC_PASSWORD|" "$ENV_FILE"
sed -i "s|KIBANA_PASSWORD=CHANGE_ME_PLEASE|KIBANA_PASSWORD=$KIBANA_PASSWORD|" "$ENV_FILE"
sed -i "s|KIBANA_ENCRYPTION_KEY=CHANGE_ME_PLEASE_MINIMUM_32_CHARACTERS_REQUIRED|KIBANA_ENCRYPTION_KEY=$KIBANA_ENCRYPTION_KEY|" "$ENV_FILE"
sed -i "s|KIBANA_REPORTING_ENCRYPTION_KEY=CHANGE_ME_PLEASE_MINIMUM_32_CHARACTERS_REQUIRED|KIBANA_REPORTING_ENCRYPTION_KEY=$KIBANA_REPORTING_ENCRYPTION_KEY|" "$ENV_FILE"
sed -i "s|APISIX_ADMIN_KEY=CHANGE_ME_PLEASE|APISIX_ADMIN_KEY=$APISIX_ADMIN_KEY|" "$ENV_FILE"
sed -i "s|APISIX_DASHBOARD_PASSWORD=CHANGE_ME_PLEASE|APISIX_DASHBOARD_PASSWORD=$APISIX_DASHBOARD_PASSWORD|" "$ENV_FILE"
sed -i "s|GRAFANA_ADMIN_PASSWORD=CHANGE_ME_PLEASE|GRAFANA_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD|" "$ENV_FILE"
sed -i "s|GRAFANA_SECRET_KEY=CHANGE_ME_PLEASE|GRAFANA_SECRET_KEY=$GRAFANA_SECRET_KEY|" "$ENV_FILE"

# Set secure permissions
chmod 600 "$ENV_FILE"

echo ""
echo -e "${GREEN}✓ Successfully created .env file with secure passwords${NC}"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  IMPORTANT: Save these credentials in a secure location${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}ElasticSearch Credentials:${NC}"
echo "  Username: elastic"
echo "  Password: $ELASTIC_PASSWORD"
echo ""
echo -e "${YELLOW}Kibana System User:${NC}"
echo "  Username: kibana_system"
echo "  Password: $KIBANA_PASSWORD"
echo ""
echo -e "${YELLOW}APISIX Admin:${NC}"
echo "  API Key: $APISIX_ADMIN_KEY"
echo ""
echo -e "${YELLOW}Grafana Admin:${NC}"
echo "  Username: admin"
echo "  Password: $GRAFANA_ADMIN_PASSWORD"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo ""
echo "  1. Review and customize .env file for your deployment:"
echo "     - Memory settings (ES_JAVA_OPTS, LS_JAVA_OPTS)"
echo "     - Client information (CLIENT_NAME, ENVIRONMENT)"
echo "     - Retention policies (RETENTION_DAYS)"
echo ""
echo "  2. Start the ELK stack:"
echo "     ${BLUE}docker-compose up -d${NC}"
echo ""
echo "  3. Access services:"
echo "     - Kibana:    http://localhost:9080/kibana"
echo "     - Grafana:   http://localhost:9080/grafana"
echo "     - Prometheus: http://localhost:9080/prometheus"
echo ""
echo -e "${YELLOW}Note: The .env file contains sensitive credentials.${NC}"
echo -e "${YELLOW}      File permissions set to 600 (owner read/write only).${NC}"
echo -e "${YELLOW}      Never commit .env to version control!${NC}"
echo ""
echo -e "${GREEN}Secrets generation complete!${NC}"
echo ""
