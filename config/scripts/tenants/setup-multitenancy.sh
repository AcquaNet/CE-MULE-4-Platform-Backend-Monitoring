#!/bin/bash
#
# Setup Multi-Tenancy for ElasticSearch with Document-Level Security
#
# This script performs the complete initial setup for multi-tenancy:
# 1. Creates ES index templates with tenant_id mapping
# 2. Creates base DLS roles for tenant users
# 3. Configures OIDC role mappings for Keycloak integration
# 4. Creates default tenant groups in Keycloak
# 5. Verifies the configuration
#
# Usage:
#   ./setup-multitenancy.sh [--skip-keycloak] [--dry-run]
#
# Prerequisites:
#   - ElasticSearch must be running with X-Pack Security enabled
#   - Keycloak must be running (unless --skip-keycloak is used)
#   - .env file with proper credentials
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Load environment (safely handle special characters)
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$PROJECT_ROOT/.env" | grep -v '^#' | sed 's/=\(.*\)/="\1"/' | sed 's/"""/"/g')
    set +a
fi

# Configuration
ES_HOST="${ELASTICSEARCH_HOST:-http://localhost:9200}"
ES_USER="${ELASTICSEARCH_USERNAME:-elastic}"
ES_PASS="${ELASTIC_PASSWORD:-changeme}"
KEYCLOAK_HOST="${KEYCLOAK_HOST:-http://localhost:8080}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-mule}"
KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin}"

# Flags
SKIP_KEYCLOAK=false
DRY_RUN=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --skip-keycloak)
            SKIP_KEYCLOAK=true
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
        --help|-h)
            echo "Usage: $0 [--skip-keycloak] [--dry-run]"
            echo ""
            echo "Options:"
            echo "  --skip-keycloak  Skip Keycloak configuration"
            echo "  --dry-run        Show what would be done without making changes"
            exit 0
            ;;
    esac
done

# Banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Multi-Tenancy Setup for ElasticSearch DLS${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}DRY RUN MODE - No changes will be made${NC}"
    echo ""
fi

# Step 1: Check ElasticSearch connectivity
echo -e "${CYAN}Step 1: Checking ElasticSearch connectivity...${NC}"
ES_HEALTH=$(curl -s -u "$ES_USER:$ES_PASS" "$ES_HOST/_cluster/health" 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$ES_HEALTH" ]; then
    echo -e "${RED}Error: Cannot connect to ElasticSearch at $ES_HOST${NC}"
    exit 1
fi
ES_STATUS=$(echo "$ES_HEALTH" | jq -r '.status')
echo -e "${GREEN}✓ ElasticSearch is $ES_STATUS${NC}"
echo ""

# Step 2: Create index template
echo -e "${CYAN}Step 2: Creating index template with tenant_id mapping...${NC}"
TEMPLATE_FILE="$PROJECT_ROOT/config/elasticsearch/templates/mule-logs-template.json"

if [ -f "$TEMPLATE_FILE" ]; then
    if [ "$DRY_RUN" = false ]; then
        RESPONSE=$(curl -s -X PUT "$ES_HOST/_index_template/mule-logs-template" \
            -u "$ES_USER:$ES_PASS" \
            -H "Content-Type: application/json" \
            -d "@$TEMPLATE_FILE")
        if echo "$RESPONSE" | grep -q '"acknowledged":true'; then
            echo -e "${GREEN}✓ Index template 'mule-logs-template' created${NC}"
        else
            echo -e "${RED}✗ Failed to create index template: $RESPONSE${NC}"
        fi
    else
        echo "Would create index template from: $TEMPLATE_FILE"
    fi
else
    echo -e "${YELLOW}⚠ Template file not found: $TEMPLATE_FILE${NC}"
fi
echo ""

# Step 3: Create base tenant roles
echo -e "${CYAN}Step 3: Creating base DLS roles...${NC}"

# tenant_user role (read-only with DLS)
TENANT_USER_ROLE='{
  "cluster": ["monitor"],
  "indices": [
    {
      "names": ["mule-logs-*", "logstash-*"],
      "privileges": ["read", "view_index_metadata"],
      "query": {
        "template": {
          "source": "{\"term\":{\"tenant_id\":\"{{_user.metadata.tenant_id}}\"}}"
        }
      }
    }
  ],
  "applications": [
    {
      "application": "kibana-.kibana",
      "privileges": [
        "feature_discover.read",
        "feature_dashboard.read",
        "feature_visualize.read"
      ],
      "resources": ["*"]
    }
  ],
  "metadata": {
    "description": "Base role for tenant users with DLS",
    "version": "1.0"
  }
}'

if [ "$DRY_RUN" = false ]; then
    RESPONSE=$(curl -s -X PUT "$ES_HOST/_security/role/tenant_user" \
        -u "$ES_USER:$ES_PASS" \
        -H "Content-Type: application/json" \
        -d "$TENANT_USER_ROLE")
    echo -e "${GREEN}✓ Created role: tenant_user${NC}"
else
    echo "Would create role: tenant_user"
fi

# tenant_admin role (with dashboard management)
TENANT_ADMIN_ROLE='{
  "cluster": ["monitor"],
  "indices": [
    {
      "names": ["mule-logs-*", "logstash-*"],
      "privileges": ["read", "view_index_metadata"],
      "query": {
        "template": {
          "source": "{\"term\":{\"tenant_id\":\"{{_user.metadata.tenant_id}}\"}}"
        }
      }
    }
  ],
  "applications": [
    {
      "application": "kibana-.kibana",
      "privileges": [
        "feature_discover.all",
        "feature_dashboard.all",
        "feature_visualize.all",
        "feature_savedObjectsManagement.all"
      ],
      "resources": ["*"]
    }
  ],
  "metadata": {
    "description": "Admin role for tenants with dashboard management",
    "version": "1.0"
  }
}'

if [ "$DRY_RUN" = false ]; then
    RESPONSE=$(curl -s -X PUT "$ES_HOST/_security/role/tenant_admin" \
        -u "$ES_USER:$ES_PASS" \
        -H "Content-Type: application/json" \
        -d "$TENANT_ADMIN_ROLE")
    echo -e "${GREEN}✓ Created role: tenant_admin${NC}"
else
    echo "Would create role: tenant_admin"
fi
echo ""

# Step 4: Create OIDC role mapping (if Keycloak integration enabled)
if [ "$SKIP_KEYCLOAK" = false ]; then
    echo -e "${CYAN}Step 4: Creating OIDC role mappings...${NC}"

    OIDC_ROLE_MAPPING='{
      "enabled": true,
      "roles": ["tenant_user"],
      "rules": {
        "all": [
          { "field": { "realm.name": "oidc1" } },
          { "field": { "metadata.tenant_id": "*" } }
        ]
      },
      "metadata": {
        "description": "Map OIDC users with tenant_id to tenant_user role"
      }
    }'

    if [ "$DRY_RUN" = false ]; then
        RESPONSE=$(curl -s -X PUT "$ES_HOST/_security/role_mapping/oidc_tenant_mapping" \
            -u "$ES_USER:$ES_PASS" \
            -H "Content-Type: application/json" \
            -d "$OIDC_ROLE_MAPPING")
        echo -e "${GREEN}✓ Created OIDC role mapping${NC}"
    else
        echo "Would create OIDC role mapping"
    fi
    echo ""

    # Step 5: Configure Keycloak
    echo -e "${CYAN}Step 5: Configuring Keycloak...${NC}"

    # Get admin token
    TOKEN=$(curl -s -X POST "$KEYCLOAK_HOST/auth/realms/master/protocol/openid-connect/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "username=$KEYCLOAK_ADMIN" \
        -d "password=$KEYCLOAK_ADMIN_PASS" \
        -d "grant_type=password" \
        -d "client_id=admin-cli" 2>/dev/null | jq -r '.access_token')

    if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
        echo -e "${YELLOW}⚠ Cannot connect to Keycloak - skipping Keycloak setup${NC}"
        echo "  You may need to configure Keycloak manually or restart it"
    else
        echo -e "${GREEN}✓ Connected to Keycloak${NC}"

        # Create tenants parent group
        if [ "$DRY_RUN" = false ]; then
            curl -s -X POST "$KEYCLOAK_HOST/auth/admin/realms/$KEYCLOAK_REALM/groups" \
                -H "Authorization: Bearer $TOKEN" \
                -H "Content-Type: application/json" \
                -d '{"name": "tenants"}' > /dev/null 2>&1 || true
            echo -e "${GREEN}✓ Created/verified tenants group${NC}"
        else
            echo "Would create tenants group in Keycloak"
        fi
    fi
else
    echo -e "${YELLOW}Step 4-5: Skipping Keycloak configuration (--skip-keycloak)${NC}"
fi
echo ""

# Step 6: Create default tenant
echo -e "${CYAN}Step 6: Creating default tenant...${NC}"

DEFAULT_TENANT_ROLE='{
  "cluster": ["monitor"],
  "indices": [
    {
      "names": ["mule-logs-*", "logstash-*"],
      "privileges": ["read", "view_index_metadata"],
      "query": {
        "term": { "tenant_id": "default" }
      }
    }
  ],
  "applications": [
    {
      "application": "kibana-.kibana",
      "privileges": [
        "feature_discover.read",
        "feature_dashboard.read"
      ],
      "resources": ["*"]
    }
  ],
  "metadata": {
    "tenant_id": "default",
    "description": "Default tenant role"
  }
}'

if [ "$DRY_RUN" = false ]; then
    RESPONSE=$(curl -s -X PUT "$ES_HOST/_security/role/tenant_default" \
        -u "$ES_USER:$ES_PASS" \
        -H "Content-Type: application/json" \
        -d "$DEFAULT_TENANT_ROLE")
    echo -e "${GREEN}✓ Created default tenant role${NC}"
else
    echo "Would create default tenant role"
fi
echo ""

# Step 7: Verify setup
echo -e "${CYAN}Step 7: Verifying setup...${NC}"

# Check roles
ROLES=$(curl -s "$ES_HOST/_security/role" -u "$ES_USER:$ES_PASS" | jq -r 'keys[]' | grep -E "^tenant_" | wc -l)
echo "  Tenant roles created: $ROLES"

# Check template
TEMPLATE=$(curl -s "$ES_HOST/_index_template/mule-logs-template" -u "$ES_USER:$ES_PASS" 2>/dev/null | jq -r '.index_templates[0].name' 2>/dev/null)
if [ "$TEMPLATE" = "mule-logs-template" ]; then
    echo -e "  Index template: ${GREEN}✓${NC}"
else
    echo -e "  Index template: ${YELLOW}⚠ not found${NC}"
fi

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}   Multi-Tenancy Setup Complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Next steps:"
echo ""
echo "  1. Create tenants:"
echo "     ${BLUE}./config/scripts/tenants/manage-tenants.sh create <tenant_id>${NC}"
echo ""
echo "  2. Test with X-Tenant-ID header:"
echo "     ${BLUE}curl -H 'X-Tenant-ID: your-tenant' http://localhost:9080/api/v1/status${NC}"
echo ""
echo "  3. Verify tenant isolation:"
echo "     ${BLUE}./config/scripts/tenants/manage-tenants.sh verify <tenant_id>${NC}"
echo ""
echo "  4. For Kibana OIDC with Keycloak, update docker-compose.yml"
echo "     See docs/MULTITENANCY_SETUP.md for details"
echo ""
