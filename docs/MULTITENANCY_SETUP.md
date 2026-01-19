# Multi-Tenancy Setup Guide

This guide explains how to configure multi-tenancy with Document-Level Security (DLS) in the ELK stack, allowing each tenant to only view logs containing their specific `tenant_id`.

## Overview

Multi-tenancy is implemented using:
- **Document-Level Security (DLS)**: ElasticSearch X-Pack feature that filters query results based on user roles
- **tenant_id field**: Added to all log documents for filtering
- **Keycloak SSO**: Optional OIDC integration for centralized authentication with tenant claims
- **Dynamic tenant extraction**: Mule extracts tenant_id from request headers or JWT

## Architecture

```
HTTP Request (X-Tenant-ID header or JWT claim)
    ↓
Mule App (extracts tenant_id to MDC ThreadContext)
    ↓
log4j2.xml (reads tenant_id from MDC: ${ctx:tenant_id})
    ↓
Logstash (validates/normalizes tenant_id)
    ↓
ElasticSearch (stores with tenant_id field)
    ↓
DLS Role (filters queries by tenant_id)
    ↓
Tenant User (sees only their logs)
```

## Quick Start

### 1. Run Initial Setup

```bash
# Run the multitenancy setup script
./config/scripts/tenants/setup-multitenancy.sh

# Or skip Keycloak if not using OIDC
./config/scripts/tenants/setup-multitenancy.sh --skip-keycloak
```

### 2. Create Your First Tenant

```bash
# Create a tenant
./config/scripts/tenants/manage-tenants.sh create acme-corp

# Create a tenant with a user
./config/scripts/tenants/manage-tenants.sh create acme-corp --user acme_user --password SecurePass123
```

### 3. Test Tenant Isolation

```bash
# Send a request with tenant header
curl -H "X-Tenant-ID: acme-corp" http://localhost:9080/api/v1/status

# Verify logs are tagged with tenant_id
curl -u elastic:$ELASTIC_PASSWORD \
  "http://localhost:9200/mule-logs-*/_search?q=tenant_id:acme-corp&pretty"

# Login as tenant user and verify isolation
curl -u acme_user:SecurePass123 \
  "http://localhost:9200/mule-logs-*/_search?pretty"
# Should only return acme-corp logs
```

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Multi-Tenancy Configuration
KIBANA_OIDC_ENABLED=false          # Set to true for Keycloak SSO
KIBANA_OIDC_CLIENT_SECRET=kibana-oidc-secret-12345
DEFAULT_TENANT_ID=default

# Keycloak Configuration (for tenant management)
KEYCLOAK_HOST=http://keycloak:8080
KEYCLOAK_REALM=mule
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD=admin
```

### Mule Application

The Mule application automatically extracts `tenant_id` from incoming requests:

1. **X-Tenant-ID header** (highest priority)
2. **JWT tenant_id claim** (from Keycloak token)
3. **tenant.id property** (from configuration)
4. **"unknown"** (default fallback)

To use in your Mule flows, ensure the `extract-tenant-id` sub-flow is called:

```xml
<!-- Already added to ce-backend-main flow -->
<flow-ref name="extract-tenant-id" doc:name="Extract Tenant ID" />
```

You can also set tenant_id programmatically:

```java
// In Java
org.apache.logging.log4j.ThreadContext.put("tenant_id", "my-tenant");

// In DataWeave (via Java invocation)
%dw 2.0
import java!org::apache::logging::log4j::ThreadContext
---
ThreadContext::put("tenant_id", vars.tenantId)
```

## Tenant Management

### Create Tenant

```bash
# Basic tenant creation (creates ES role)
./config/scripts/tenants/manage-tenants.sh create <tenant_id>

# With ES user
./config/scripts/tenants/manage-tenants.sh create <tenant_id> --user <username> --password <password>

# Examples
./config/scripts/tenants/manage-tenants.sh create acme-corp
./config/scripts/tenants/manage-tenants.sh create customer-123 --user cust123_user --password MySecretPass
```

### List Tenants

```bash
./config/scripts/tenants/manage-tenants.sh list
```

Output:
```
Tenant Roles:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROLE NAME                 TENANT ID
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
tenant_acme-corp          acme-corp
tenant_customer-123       customer-123
tenant_default            default
```

### Verify Tenant

```bash
./config/scripts/tenants/manage-tenants.sh verify <tenant_id>
```

### Delete Tenant

```bash
# With confirmation prompt
./config/scripts/tenants/manage-tenants.sh delete <tenant_id>

# Force delete (no prompt)
./config/scripts/tenants/manage-tenants.sh delete <tenant_id> --force
```

### Show Tenant Info

```bash
./config/scripts/tenants/manage-tenants.sh info <tenant_id>
```

## Keycloak SSO Integration

### Enable Kibana OIDC

1. Set environment variables:

```bash
# In .env
KIBANA_OIDC_ENABLED=true
KIBANA_OIDC_CLIENT_SECRET=kibana-oidc-secret-12345
```

2. Configure ElasticSearch OIDC realm:

```bash
# Add to elasticsearch.yml or via API
curl -X PUT "localhost:9200/_security/realm/oidc1" \
  -u elastic:$ELASTIC_PASSWORD \
  -H "Content-Type: application/json" \
  -d '{
    "type": "oidc",
    "order": 2,
    "rp.client_id": "kibana",
    "rp.client_secret": "kibana-oidc-secret-12345",
    "rp.response_type": "code",
    "rp.redirect_uri": "http://localhost:9080/kibana/api/security/oidc/callback",
    "op.issuer": "http://keycloak:8080/auth/realms/mule",
    "op.authorization_endpoint": "http://keycloak:8080/auth/realms/mule/protocol/openid-connect/auth",
    "op.token_endpoint": "http://keycloak:8080/auth/realms/mule/protocol/openid-connect/token",
    "op.userinfo_endpoint": "http://keycloak:8080/auth/realms/mule/protocol/openid-connect/userinfo",
    "op.jwkset_path": "http://keycloak:8080/auth/realms/mule/protocol/openid-connect/certs",
    "claims.principal": "preferred_username",
    "claims.groups": "roles",
    "claims.mail": "email",
    "claim_patterns.principal": "^(.*)$"
  }'
```

3. Restart services:

```bash
docker-compose restart kibana
```

### Keycloak User Setup

Users in Keycloak must have the `tenant_id` attribute:

1. Go to Keycloak Admin Console
2. Navigate to Users → Select User → Attributes
3. Add attribute: `tenant_id` = `<tenant-id>`
4. Or assign user to a tenant group (e.g., `/tenants/tenant-acme-corp`)

The tenant_id is automatically included in JWT tokens via the protocol mapper.

### Verify JWT Contains tenant_id

```bash
# Get token from Keycloak
TOKEN=$(curl -s -X POST "http://localhost:8080/auth/realms/mule/protocol/openid-connect/token" \
  -d "grant_type=password" \
  -d "client_id=mule-api-gateway" \
  -d "client_secret=mule-gateway-secret-12345" \
  -d "username=developer" \
  -d "password=dev123" \
  | jq -r '.access_token')

# Decode and check tenant_id
echo $TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | jq '.tenant_id'
```

## ElasticSearch Roles

### DLS Role Structure

Each tenant gets a role with Document-Level Security:

```json
{
  "cluster": ["monitor"],
  "indices": [
    {
      "names": ["mule-logs-*", "logstash-*"],
      "privileges": ["read", "view_index_metadata"],
      "query": {
        "term": { "tenant_id": "acme-corp" }
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
  ]
}
```

### Role Mapping for OIDC

For Keycloak users, role mapping is used:

```json
{
  "enabled": true,
  "roles": ["tenant_user"],
  "rules": {
    "all": [
      { "field": { "realm.name": "oidc1" } },
      { "field": { "metadata.tenant_id": "*" } }
    ]
  }
}
```

## Logstash Pipeline

The Logstash pipeline validates and normalizes tenant_id:

1. **Validates format**: 2-50 characters, alphanumeric with hyphens/underscores
2. **Normalizes to lowercase**: Ensures consistent querying
3. **Tags invalid/missing**: For monitoring and debugging
4. **Sets default "unknown"**: For logs without tenant_id

Invalid tenant_ids are sanitized, not dropped, to prevent data loss.

## Monitoring

### Check for Missing tenant_id

```bash
# Count logs without tenant_id
curl -u elastic:$ELASTIC_PASSWORD \
  "http://localhost:9200/mule-logs-*/_count" \
  -H "Content-Type: application/json" \
  -d '{"query":{"term":{"tags":"missing_tenant_id"}}}'

# Search for logs with invalid tenant_id
curl -u elastic:$ELASTIC_PASSWORD \
  "http://localhost:9200/mule-logs-*/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{"query":{"term":{"tags":"invalid_tenant_id"}}}'
```

### Create Kibana Alert

In Kibana, create an alert for:
- Query: `tags:missing_tenant_id`
- Threshold: > 0 in last 15 minutes
- Action: Email/Slack notification

## Troubleshooting

### Tenant Cannot See Their Logs

1. **Check tenant_id in logs**:
   ```bash
   curl -u elastic:$ELASTIC_PASSWORD \
     "http://localhost:9200/mule-logs-*/_search?q=tenant_id:acme-corp&pretty"
   ```

2. **Verify role exists**:
   ```bash
   ./config/scripts/tenants/manage-tenants.sh info acme-corp
   ```

3. **Check user has role**:
   ```bash
   curl -u elastic:$ELASTIC_PASSWORD \
     "http://localhost:9200/_security/user/acme_user?pretty"
   ```

### Logs Missing tenant_id

1. **Check Mule flow has extract-tenant-id**:
   Ensure `<flow-ref name="extract-tenant-id"/>` is in your main flow

2. **Check log4j2.xml configuration**:
   ```xml
   <KeyValuePair key="tenant_id" value="${ctx:tenant_id:-unknown}"/>
   ```

3. **Verify X-Tenant-ID header is being sent**:
   ```bash
   curl -v -H "X-Tenant-ID: my-tenant" http://localhost:9080/api/v1/status
   ```

### OIDC Login Not Working

1. **Check Keycloak is running**:
   ```bash
   curl http://localhost:8080/auth/realms/mule/.well-known/openid-configuration
   ```

2. **Verify KIBANA_OIDC_ENABLED=true** in .env

3. **Check Kibana logs**:
   ```bash
   docker logs kibana | grep -i oidc
   ```

## Security Considerations

1. **tenant_id validation**: Always validate tenant_id format to prevent injection
2. **DLS bypass**: Admin users (elastic) can see all logs - use tenant roles for regular users
3. **JWT validation**: Ensure Mule validates JWT signatures before trusting tenant_id claims
4. **Keycloak secrets**: Use strong, unique secrets for OIDC clients
5. **Network isolation**: Tenant users should not have direct access to ElasticSearch

## Files Reference

| File | Purpose |
|------|---------|
| `config/scripts/tenants/manage-tenants.sh` | Tenant CRUD operations |
| `config/scripts/tenants/setup-multitenancy.sh` | Initial setup script |
| `config/elasticsearch/templates/mule-logs-template.json` | Index template with tenant_id mapping |
| `config/elasticsearch/role-mappings/tenant-role-mapping.json` | OIDC role mapping |
| `config/keycloak/realms/mule-realm.json` | Keycloak realm with tenant_id mapper |
| `config/logstash/pipeline/logstash.conf` | Pipeline with tenant validation |
| `git/CE-MULE-4-Platform-Backend-Mule/src/main/mule/global-tenant-handler.xml` | Mule tenant extraction |

## Related Documentation

- [Security Setup Guide](SECURITY_SETUP.md)
- [JWT Authentication Guide](JWT_AUTHENTICATION_GUIDE.md)
- [Retention Policy Guide](RETENTION_POLICY_GUIDE.md)
