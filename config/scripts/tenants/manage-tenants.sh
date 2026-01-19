#!/bin/bash
#
# Multi-Tenant Management for ElasticSearch Document-Level Security
#
# This script manages tenant roles with DLS for log access isolation.
# It integrates with both ElasticSearch and Keycloak for complete
# tenant management.
#
# Usage:
#   ./manage-tenants.sh create <tenant_id> [--user <username>] [--password <password>]
#   ./manage-tenants.sh list
#   ./manage-tenants.sh delete <tenant_id> [--force]
#   ./manage-tenants.sh verify <tenant_id>
#   ./manage-tenants.sh info <tenant_id>
#   ./manage-tenants.sh setup
#
# Examples:
#   ./manage-tenants.sh create acme-corp
#   ./manage-tenants.sh create acme-corp --user acme_user --password SecurePass123
#   ./manage-tenants.sh list
#   ./manage-tenants.sh verify acme-corp
#   ./manage-tenants.sh delete acme-corp
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Load environment variables (safely handle special characters)
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

# Print banner
print_banner() {
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}   Multi-Tenant Management for ElasticSearch DLS${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Print usage
print_usage() {
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  create <tenant_id>    Create a new tenant"
    echo "      --user <name>     Create ES user for tenant"
    echo "      --password <pwd>  Set user password"
    echo "  list                  List all tenants"
    echo "  delete <tenant_id>    Delete a tenant"
    echo "      --force           Skip confirmation"
    echo "  verify <tenant_id>    Verify tenant access"
    echo "  info <tenant_id>      Show tenant details"
    echo "  setup                 Initial multitenancy setup"
    echo ""
    echo "Examples:"
    echo "  $0 create acme-corp"
    echo "  $0 create acme-corp --user acme_user --password MySecretPass123"
    echo "  $0 list"
    echo "  $0 delete acme-corp --force"
    echo ""
}

# Validate tenant_id format
validate_tenant_id() {
    local tenant_id="$1"
    if [[ ! "$tenant_id" =~ ^[a-zA-Z0-9_-]{2,50}$ ]]; then
        echo -e "${RED}Error: Invalid tenant_id format${NC}"
        echo "Tenant ID must be 2-50 characters, alphanumeric with hyphens/underscores"
        exit 1
    fi
}

# Check ElasticSearch connectivity
check_es_connection() {
    echo -e "${CYAN}Checking ElasticSearch connection...${NC}"
    local response
    response=$(curl -s -o /dev/null -w "%{http_code}" -u "$ES_USER:$ES_PASS" "$ES_HOST/_cluster/health")
    if [ "$response" != "200" ]; then
        echo -e "${RED}Error: Cannot connect to ElasticSearch at $ES_HOST${NC}"
        echo "HTTP Status: $response"
        exit 1
    fi
    echo -e "${GREEN}✓ Connected to ElasticSearch${NC}"
}

# Create tenant role in ElasticSearch with DLS
create_es_role() {
    local tenant_id="$1"
    local role_name="tenant_${tenant_id}"

    echo -e "${CYAN}Creating ElasticSearch role: $role_name${NC}"

    local role_body=$(cat <<EOF
{
  "cluster": ["monitor"],
  "indices": [
    {
      "names": ["mule-logs-*", "logstash-*"],
      "privileges": ["read", "view_index_metadata"],
      "query": {
        "term": {
          "tenant_id": "$tenant_id"
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
    "tenant_id": "$tenant_id",
    "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "description": "DLS role for tenant $tenant_id"
  }
}
EOF
)

    local response
    response=$(curl -s -X PUT "$ES_HOST/_security/role/$role_name" \
        -u "$ES_USER:$ES_PASS" \
        -H "Content-Type: application/json" \
        -d "$role_body")

    if echo "$response" | grep -q '"created":true\|"role":{"created":true}'; then
        echo -e "${GREEN}✓ Role created: $role_name${NC}"
    elif echo "$response" | grep -q '"created":false'; then
        echo -e "${YELLOW}⚠ Role already exists: $role_name (updated)${NC}"
    else
        echo -e "${RED}✗ Failed to create role: $response${NC}"
        return 1
    fi
}

# Create ES user for tenant
create_es_user() {
    local tenant_id="$1"
    local username="$2"
    local password="$3"
    local role_name="tenant_${tenant_id}"

    echo -e "${CYAN}Creating ElasticSearch user: $username${NC}"

    local user_body=$(cat <<EOF
{
  "password": "$password",
  "roles": ["$role_name"],
  "full_name": "Tenant User ($tenant_id)",
  "email": "$username@tenant.local",
  "metadata": {
    "tenant_id": "$tenant_id"
  }
}
EOF
)

    local response
    response=$(curl -s -X PUT "$ES_HOST/_security/user/$username" \
        -u "$ES_USER:$ES_PASS" \
        -H "Content-Type: application/json" \
        -d "$user_body")

    if echo "$response" | grep -q '"created":true'; then
        echo -e "${GREEN}✓ User created: $username${NC}"
    elif echo "$response" | grep -q '"created":false'; then
        echo -e "${YELLOW}⚠ User already exists: $username (updated)${NC}"
    else
        echo -e "${RED}✗ Failed to create user: $response${NC}"
        return 1
    fi
}

# Get Keycloak admin token
get_keycloak_token() {
    local token
    token=$(curl -s -X POST "$KEYCLOAK_HOST/auth/realms/master/protocol/openid-connect/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "username=$KEYCLOAK_ADMIN" \
        -d "password=$KEYCLOAK_ADMIN_PASS" \
        -d "grant_type=password" \
        -d "client_id=admin-cli" | jq -r '.access_token')

    if [ "$token" == "null" ] || [ -z "$token" ]; then
        echo ""
        return 1
    fi
    echo "$token"
}

# Create Keycloak group for tenant
create_keycloak_group() {
    local tenant_id="$1"
    local token="$2"

    echo -e "${CYAN}Creating Keycloak group: tenant-$tenant_id${NC}"

    # First, get or create the tenants parent group
    local parent_id
    parent_id=$(curl -s "$KEYCLOAK_HOST/auth/admin/realms/$KEYCLOAK_REALM/groups" \
        -H "Authorization: Bearer $token" | jq -r '.[] | select(.name=="tenants") | .id')

    if [ -z "$parent_id" ] || [ "$parent_id" == "null" ]; then
        # Create parent group
        curl -s -X POST "$KEYCLOAK_HOST/auth/admin/realms/$KEYCLOAK_REALM/groups" \
            -H "Authorization: Bearer $token" \
            -H "Content-Type: application/json" \
            -d '{"name": "tenants"}' > /dev/null

        parent_id=$(curl -s "$KEYCLOAK_HOST/auth/admin/realms/$KEYCLOAK_REALM/groups" \
            -H "Authorization: Bearer $token" | jq -r '.[] | select(.name=="tenants") | .id')
    fi

    # Create tenant subgroup
    local group_body=$(cat <<EOF
{
  "name": "tenant-$tenant_id",
  "attributes": {
    "tenant_id": ["$tenant_id"]
  }
}
EOF
)

    local response
    response=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        "$KEYCLOAK_HOST/auth/admin/realms/$KEYCLOAK_REALM/groups/$parent_id/children" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "$group_body")

    if [ "$response" == "201" ]; then
        echo -e "${GREEN}✓ Keycloak group created: tenant-$tenant_id${NC}"
    elif [ "$response" == "409" ]; then
        echo -e "${YELLOW}⚠ Keycloak group already exists: tenant-$tenant_id${NC}"
    else
        echo -e "${RED}✗ Failed to create Keycloak group (HTTP $response)${NC}"
    fi
}

# List all tenant roles
list_tenants() {
    echo -e "${CYAN}Fetching tenant roles from ElasticSearch...${NC}"
    echo ""

    local roles
    roles=$(curl -s "$ES_HOST/_security/role" -u "$ES_USER:$ES_PASS" | \
        jq -r 'to_entries[] | select(.key | startswith("tenant_")) | .key')

    if [ -z "$roles" ]; then
        echo -e "${YELLOW}No tenant roles found${NC}"
        return 0
    fi

    echo -e "${GREEN}Tenant Roles:${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf "%-25s %-20s\n" "ROLE NAME" "TENANT ID"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    while IFS= read -r role; do
        tenant_id="${role#tenant_}"
        printf "%-25s %-20s\n" "$role" "$tenant_id"
    done <<< "$roles"

    echo ""

    # List Keycloak groups if available
    local token
    token=$(get_keycloak_token 2>/dev/null)
    if [ -n "$token" ]; then
        echo -e "${CYAN}Keycloak Tenant Groups:${NC}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        local groups
        groups=$(curl -s "$KEYCLOAK_HOST/auth/admin/realms/$KEYCLOAK_REALM/groups" \
            -H "Authorization: Bearer $token" | \
            jq -r '.. | objects | select(.name? | startswith("tenant-")) | .name')

        if [ -n "$groups" ]; then
            echo "$groups"
        else
            echo "No tenant groups found"
        fi
    fi
}

# Delete tenant
delete_tenant() {
    local tenant_id="$1"
    local force="$2"
    local role_name="tenant_${tenant_id}"

    if [ "$force" != "--force" ]; then
        echo -e "${YELLOW}Warning: This will delete the tenant role and any associated users${NC}"
        read -p "Are you sure you want to delete tenant '$tenant_id'? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Cancelled"
            exit 0
        fi
    fi

    echo -e "${CYAN}Deleting ElasticSearch role: $role_name${NC}"

    local response
    response=$(curl -s -X DELETE "$ES_HOST/_security/role/$role_name" -u "$ES_USER:$ES_PASS")

    if echo "$response" | grep -q '"found":true'; then
        echo -e "${GREEN}✓ Role deleted: $role_name${NC}"
    else
        echo -e "${YELLOW}⚠ Role not found or already deleted${NC}"
    fi

    # Delete Keycloak group
    local token
    token=$(get_keycloak_token 2>/dev/null)
    if [ -n "$token" ]; then
        local group_id
        group_id=$(curl -s "$KEYCLOAK_HOST/auth/admin/realms/$KEYCLOAK_REALM/groups" \
            -H "Authorization: Bearer $token" | \
            jq -r ".. | objects | select(.name? == \"tenant-$tenant_id\") | .id" | head -1)

        if [ -n "$group_id" ] && [ "$group_id" != "null" ]; then
            curl -s -X DELETE "$KEYCLOAK_HOST/auth/admin/realms/$KEYCLOAK_REALM/groups/$group_id" \
                -H "Authorization: Bearer $token"
            echo -e "${GREEN}✓ Keycloak group deleted: tenant-$tenant_id${NC}"
        fi
    fi
}

# Verify tenant access
verify_tenant() {
    local tenant_id="$1"
    local role_name="tenant_${tenant_id}"

    echo -e "${CYAN}Verifying tenant: $tenant_id${NC}"
    echo ""

    # Check role exists
    local role_response
    role_response=$(curl -s "$ES_HOST/_security/role/$role_name" -u "$ES_USER:$ES_PASS")

    if echo "$role_response" | grep -q "$role_name"; then
        echo -e "${GREEN}✓ Role exists: $role_name${NC}"

        # Show role details
        echo -e "${CYAN}Role Configuration:${NC}"
        echo "$role_response" | jq ".${role_name}.indices[0].query"
    else
        echo -e "${RED}✗ Role not found: $role_name${NC}"
        return 1
    fi

    # Check for sample documents
    echo ""
    echo -e "${CYAN}Checking for logs with tenant_id: $tenant_id${NC}"

    local doc_count
    doc_count=$(curl -s "$ES_HOST/mule-logs-*/_count" -u "$ES_USER:$ES_PASS" \
        -H "Content-Type: application/json" \
        -d "{\"query\":{\"term\":{\"tenant_id\":\"$tenant_id\"}}}" | jq '.count')

    echo "Document count: $doc_count"

    if [ "$doc_count" -gt 0 ]; then
        echo -e "${GREEN}✓ Found $doc_count documents for tenant${NC}"
    else
        echo -e "${YELLOW}⚠ No documents found for tenant (this is normal for new tenants)${NC}"
    fi
}

# Show tenant info
tenant_info() {
    local tenant_id="$1"
    local role_name="tenant_${tenant_id}"

    echo -e "${CYAN}Tenant Information: $tenant_id${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Role info
    echo -e "${BLUE}ElasticSearch Role:${NC}"
    curl -s "$ES_HOST/_security/role/$role_name" -u "$ES_USER:$ES_PASS" | jq .

    echo ""

    # Users with this role
    echo -e "${BLUE}Users with this role:${NC}"
    curl -s "$ES_HOST/_security/user" -u "$ES_USER:$ES_PASS" | \
        jq -r "to_entries[] | select(.value.roles[]? == \"$role_name\") | .key"

    # Keycloak info
    local token
    token=$(get_keycloak_token 2>/dev/null)
    if [ -n "$token" ]; then
        echo ""
        echo -e "${BLUE}Keycloak Group:${NC}"
        curl -s "$KEYCLOAK_HOST/auth/admin/realms/$KEYCLOAK_REALM/groups" \
            -H "Authorization: Bearer $token" | \
            jq ".. | objects | select(.name? == \"tenant-$tenant_id\")"
    fi
}

# Initial setup
setup_multitenancy() {
    echo -e "${CYAN}Setting up multi-tenancy infrastructure...${NC}"
    echo ""

    check_es_connection

    # Create index template
    echo -e "${CYAN}Creating index template with tenant_id mapping...${NC}"

    local template_file="$PROJECT_ROOT/config/elasticsearch/templates/mule-logs-template.json"
    if [ -f "$template_file" ]; then
        curl -s -X PUT "$ES_HOST/_index_template/mule-logs-template" \
            -u "$ES_USER:$ES_PASS" \
            -H "Content-Type: application/json" \
            -d "@$template_file" | jq .
        echo -e "${GREEN}✓ Index template created${NC}"
    else
        echo -e "${YELLOW}⚠ Template file not found: $template_file${NC}"
    fi

    # Create base tenant_user role
    echo -e "${CYAN}Creating base tenant_user role...${NC}"

    local role_mappings="$PROJECT_ROOT/config/elasticsearch/role-mappings/tenant-role-mapping.json"
    if [ -f "$role_mappings" ]; then
        local tenant_user_role=$(jq '.tenant_user_role' "$role_mappings")
        curl -s -X PUT "$ES_HOST/_security/role/tenant_user" \
            -u "$ES_USER:$ES_PASS" \
            -H "Content-Type: application/json" \
            -d "$tenant_user_role" | jq .
        echo -e "${GREEN}✓ Base tenant_user role created${NC}"
    fi

    echo ""
    echo -e "${GREEN}Multi-tenancy setup complete!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Create tenants: ./manage-tenants.sh create <tenant_id>"
    echo "  2. Configure Mule apps with tenant_id header extraction"
    echo "  3. Test with: curl -H 'X-Tenant-ID: <tenant_id>' http://localhost:9080/api/v1/status"
}

# Main
main() {
    print_banner

    if [ $# -lt 1 ]; then
        print_usage
        exit 1
    fi

    local command="$1"
    shift

    case "$command" in
        create)
            if [ $# -lt 1 ]; then
                echo -e "${RED}Error: tenant_id required${NC}"
                print_usage
                exit 1
            fi

            local tenant_id="$1"
            shift
            validate_tenant_id "$tenant_id"

            # Parse optional arguments
            local username=""
            local password=""
            while [ $# -gt 0 ]; do
                case "$1" in
                    --user)
                        username="$2"
                        shift 2
                        ;;
                    --password)
                        password="$2"
                        shift 2
                        ;;
                    *)
                        echo -e "${RED}Unknown option: $1${NC}"
                        exit 1
                        ;;
                esac
            done

            check_es_connection
            create_es_role "$tenant_id"

            if [ -n "$username" ]; then
                if [ -z "$password" ]; then
                    # Generate random password
                    password=$(openssl rand -base64 16 | tr -d "=+/")
                    echo -e "${YELLOW}Generated password: $password${NC}"
                fi
                create_es_user "$tenant_id" "$username" "$password"
            fi

            # Create Keycloak group
            local token
            token=$(get_keycloak_token 2>/dev/null)
            if [ -n "$token" ]; then
                create_keycloak_group "$tenant_id" "$token"
            else
                echo -e "${YELLOW}⚠ Keycloak not available - skipping group creation${NC}"
            fi

            echo ""
            echo -e "${GREEN}Tenant created successfully: $tenant_id${NC}"
            ;;

        list)
            check_es_connection
            list_tenants
            ;;

        delete)
            if [ $# -lt 1 ]; then
                echo -e "${RED}Error: tenant_id required${NC}"
                exit 1
            fi
            local tenant_id="$1"
            local force="$2"
            validate_tenant_id "$tenant_id"
            check_es_connection
            delete_tenant "$tenant_id" "$force"
            ;;

        verify)
            if [ $# -lt 1 ]; then
                echo -e "${RED}Error: tenant_id required${NC}"
                exit 1
            fi
            local tenant_id="$1"
            validate_tenant_id "$tenant_id"
            check_es_connection
            verify_tenant "$tenant_id"
            ;;

        info)
            if [ $# -lt 1 ]; then
                echo -e "${RED}Error: tenant_id required${NC}"
                exit 1
            fi
            local tenant_id="$1"
            validate_tenant_id "$tenant_id"
            check_es_connection
            tenant_info "$tenant_id"
            ;;

        setup)
            setup_multitenancy
            ;;

        help|--help|-h)
            print_usage
            ;;

        *)
            echo -e "${RED}Unknown command: $command${NC}"
            print_usage
            exit 1
            ;;
    esac
}

main "$@"
