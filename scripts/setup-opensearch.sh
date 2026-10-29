#!/bin/sh
# OpenSearch Setup Script
# Configures index templates and security roles for multi-tenancy with DLS.
# Runs in the background inside the opensearch container on every start (docker-compose.yml);
# it waits for the cluster and every step is idempotent.

set -e

OPENSEARCH_HOST="${OPENSEARCH_HOST:-opensearch:9200}"
OPENSEARCH_USER="${OPENSEARCH_USER:-admin}"
# admin password: OPENSEARCH_ADMIN_PASSWORD from .env (docker-compose.yml passes it in)
OPENSEARCH_PASSWORD="${OPENSEARCH_PASSWORD:?OPENSEARCH_PASSWORD not set}"
# Use HTTPS with -k to skip certificate verification (demo mode uses self-signed certs)
CURL_OPTS="-s -k"

echo "=== OpenSearch Setup Script ==="
echo "OpenSearch Host: $OPENSEARCH_HOST"

# Wait for OpenSearch to be ready
echo "Waiting for OpenSearch to be ready..."
max_attempts=60
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl $CURL_OPTS -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" "https://$OPENSEARCH_HOST/_cluster/health" | grep -q '"status"'; then
        echo "OpenSearch is ready!"
        break
    fi
    attempt=$((attempt + 1))
    echo "Waiting for OpenSearch... (attempt $attempt/$max_attempts)"
    sleep 5
done

if [ $attempt -eq $max_attempts ]; then
    echo "ERROR: OpenSearch did not become ready in time"
    exit 1
fi

# Get cluster health
echo ""
echo "=== Cluster Health ==="
curl $CURL_OPTS -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" "https://$OPENSEARCH_HOST/_cluster/health?pretty"

# Create index template for mule-logs with tenant_id mapping
echo ""
echo "=== Creating Index Template for Mule Logs ==="
curl $CURL_OPTS -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "https://$OPENSEARCH_HOST/_index_template/mule-logs-template" \
    -H "Content-Type: application/json" \
    -d '{
  "index_patterns": ["mule-logs-*"],
  "priority": 100,
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 0,
      "index.refresh_interval": "5s"
    },
    "mappings": {
      "properties": {
        "tenant_id": {
          "type": "keyword",
          "doc_values": true
        },
        "@timestamp": {
          "type": "date"
        },
        "level": {
          "type": "keyword"
        },
        "loggerName": {
          "type": "keyword"
        },
        "message": {
          "type": "text",
          "fields": {
            "keyword": {
              "type": "keyword",
              "ignore_above": 256
            }
          }
        },
        "application": {
          "type": "keyword"
        },
        "environment": {
          "type": "keyword"
        },
        "worker_id": {
          "type": "keyword"
        },
        "correlationId": {
          "type": "keyword"
        },
        "log_type": {
          "type": "keyword"
        },
        "thread": {
          "type": "keyword"
        },
        "source_host": {
          "type": "keyword"
        },
        "tags": {
          "type": "keyword"
        }
      }
    }
  }
}'
echo ""

# Create index template for logstash indices
echo ""
echo "=== Creating Index Template for Logstash ==="
curl $CURL_OPTS -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "https://$OPENSEARCH_HOST/_index_template/logstash-template" \
    -H "Content-Type: application/json" \
    -d '{
  "index_patterns": ["logstash-*"],
  "priority": 50,
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 0
    },
    "mappings": {
      "properties": {
        "tenant_id": {
          "type": "keyword"
        },
        "@timestamp": {
          "type": "date"
        }
      }
    }
  }
}'
echo ""

# Create base tenant role template (DLS enabled - FREE in OpenSearch!)
echo ""
echo "=== Creating Base Tenant Role Template ==="
# Note: This creates a role that uses DLS to filter by tenant_id
# Individual tenant roles will inherit from this pattern
curl $CURL_OPTS -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "https://$OPENSEARCH_HOST/_plugins/_security/api/roles/tenant_viewer_template" \
    -H "Content-Type: application/json" \
    -d '{
  "cluster_permissions": [],
  "index_permissions": [
    {
      "index_patterns": ["mule-logs-*", "logstash-*"],
      "allowed_actions": [
        "read",
        "search"
      ]
    }
  ],
  "tenant_permissions": []
}'
echo ""

# Create a sample tenant role with DLS (example: acme-corp)
echo ""
echo "=== Creating Sample Tenant Role (acme-corp) with Document-Level Security ==="
curl $CURL_OPTS -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "https://$OPENSEARCH_HOST/_plugins/_security/api/roles/tenant_acme-corp" \
    -H "Content-Type: application/json" \
    -d '{
  "cluster_permissions": [],
  "index_permissions": [
    {
      "index_patterns": ["mule-logs-*", "logstash-*"],
      "dls": "{\"term\": {\"tenant_id\": \"acme-corp\"}}",
      "allowed_actions": [
        "read",
        "search"
      ]
    }
  ],
  "tenant_permissions": []
}'
echo ""

# Create a second sample tenant role (example: globex)
echo ""
echo "=== Creating Sample Tenant Role (globex) with Document-Level Security ==="
curl $CURL_OPTS -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "https://$OPENSEARCH_HOST/_plugins/_security/api/roles/tenant_globex" \
    -H "Content-Type: application/json" \
    -d '{
  "cluster_permissions": [],
  "index_permissions": [
    {
      "index_patterns": ["mule-logs-*", "logstash-*"],
      "dls": "{\"term\": {\"tenant_id\": \"globex\"}}",
      "allowed_actions": [
        "read",
        "search"
      ]
    }
  ],
  "tenant_permissions": []
}'
echo ""

# Keycloak single sign-on (OpenSearch Dashboards sends the user's ID token): internal users (admin, tenant users of
# manage-tenants.sh) keep basic auth (order 1: the domain that challenges must come last, or it answers 401 before the
# token is tried); tokens are checked against realm mule's keys and must be issued to client dashboards (aud), so
# another client's token can't be replayed here. Token claim roles = backend roles:
# admin -> all_access (default mapping), user -> sso_tenant_logs (only documents of the token's tenant_id).
# user also gets kibana_user (Dashboards app access; the static role keeps its old name); the shared Global tenant
# is read-only for user (one tenant can't change the saved objects everyone sees), its Private tenant stays writable.
echo ""
echo "=== Keycloak sign-in (openid auth domain) ==="
curl $CURL_OPTS -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "https://$OPENSEARCH_HOST/_plugins/_security/api/securityconfig/config" \
    -H "Content-Type: application/json" \
    -d '{"dynamic": {"http": {"anonymous_auth_enabled": false}, "authc": {
  "basic_internal_auth_domain": {"http_enabled": true, "transport_enabled": true, "order": 1,
    "http_authenticator": {"type": "basic", "challenge": true}, "authentication_backend": {"type": "intern"}},
  "openid_auth_domain": {"http_enabled": true, "transport_enabled": false, "order": 0,
    "http_authenticator": {"type": "openid", "challenge": false, "config": {"subject_key": "preferred_username",
      "roles_key": "roles", "required_audience": "dashboards", "openid_connect_url": "http://keycloak:8080/auth/realms/mule/.well-known/openid-configuration"}},
    "authentication_backend": {"type": "noop"}}}}}'
echo ""
curl $CURL_OPTS -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "https://$OPENSEARCH_HOST/_plugins/_security/api/roles/sso_tenant_logs" \
    -H "Content-Type: application/json" \
    -d '{"cluster_permissions": ["cluster_composite_ops_ro"], "index_permissions": [{
  "index_patterns": ["mule-logs-*", "logstash-*"],
  "dls": "{\"term\": {\"tenant_id\": \"${attr.jwt.tenant_id}\"}}",
  "allowed_actions": ["read", "search", "indices:admin/mappings/get", "indices:admin/resolve/index"]}],
  "tenant_permissions": [{"tenant_patterns": ["global_tenant"], "allowed_actions": ["kibana_all_read"]}]}'
echo ""
curl $CURL_OPTS -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "https://$OPENSEARCH_HOST/_plugins/_security/api/rolesmapping/sso_tenant_logs" \
    -H "Content-Type: application/json" -d '{"backend_roles": ["user"]}'
echo ""
curl $CURL_OPTS -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "https://$OPENSEARCH_HOST/_plugins/_security/api/rolesmapping/kibana_user" \
    -H "Content-Type: application/json" -d '{"backend_roles": ["kibanauser", "user"]}'
echo ""

echo ""
echo "=== OpenSearch Setup Complete ==="
echo "- Index templates: mule-logs-*, logstash-*"
echo "- Tenant roles with DLS: tenant_acme-corp, tenant_globex (no users: add them with config/scripts/tenants/)"
