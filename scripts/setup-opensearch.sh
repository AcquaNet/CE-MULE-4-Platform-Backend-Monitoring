#!/bin/sh
# OpenSearch Setup Script
# Configures index templates and security roles for multi-tenancy with DLS

set -e

OPENSEARCH_HOST="${OPENSEARCH_HOST:-opensearch:9200}"
OPENSEARCH_USER="${OPENSEARCH_USER:-admin}"
# Demo mode uses admin/admin as default credentials
OPENSEARCH_PASSWORD="${OPENSEARCH_PASSWORD:-admin}"
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
curl -s -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/_index_template/mule-logs-template" \
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
curl -s -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/_index_template/logstash-template" \
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
curl -s -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/_plugins/_security/api/roles/tenant_viewer_template" \
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
curl -s -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/_plugins/_security/api/roles/tenant_acme-corp" \
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
curl -s -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/_plugins/_security/api/roles/tenant_globex" \
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

# Create internal users for testing
echo ""
echo "=== Creating Test Users ==="

# Create acme-corp user
curl -s -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/_plugins/_security/api/internalusers/acme_user" \
    -H "Content-Type: application/json" \
    -d '{
  "password": "AcmePass123!",
  "opendistro_security_roles": ["tenant_acme-corp"],
  "backend_roles": [],
  "attributes": {
    "tenant_id": "acme-corp"
  }
}'
echo ""

# Create globex user
curl -s -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/_plugins/_security/api/internalusers/globex_user" \
    -H "Content-Type: application/json" \
    -d '{
  "password": "GlobexPass123!",
  "opendistro_security_roles": ["tenant_globex"],
  "backend_roles": [],
  "attributes": {
    "tenant_id": "globex"
  }
}'
echo ""

# Map users to roles
echo ""
echo "=== Mapping Users to Roles ==="

curl -s -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/_plugins/_security/api/rolesmapping/tenant_acme-corp" \
    -H "Content-Type: application/json" \
    -d '{
  "backend_roles": [],
  "hosts": [],
  "users": ["acme_user"]
}'
echo ""

curl -s -X PUT -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/_plugins/_security/api/rolesmapping/tenant_globex" \
    -H "Content-Type: application/json" \
    -d '{
  "backend_roles": [],
  "hosts": [],
  "users": ["globex_user"]
}'
echo ""

# Insert sample test documents
echo ""
echo "=== Inserting Sample Test Documents ==="

# Acme Corp log
curl -s -X POST -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/mule-logs-test/_doc" \
    -H "Content-Type: application/json" \
    -d '{
  "tenant_id": "acme-corp",
  "@timestamp": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
  "level": "INFO",
  "message": "Test log from ACME Corp tenant",
  "application": "mule-api",
  "log_type": "mule"
}'
echo ""

# Globex log
curl -s -X POST -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/mule-logs-test/_doc" \
    -H "Content-Type: application/json" \
    -d '{
  "tenant_id": "globex",
  "@timestamp": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
  "level": "INFO",
  "message": "Test log from Globex tenant",
  "application": "mule-api",
  "log_type": "mule"
}'
echo ""

# Refresh index
curl -s -X POST -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/mule-logs-test/_refresh"
echo ""

# Verify DLS is working
echo ""
echo "=== Verifying Document-Level Security ==="
echo ""
echo "Admin user (should see ALL documents):"
curl -s -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
    "http://$OPENSEARCH_HOST/mule-logs-test/_search?pretty" \
    -H "Content-Type: application/json" \
    -d '{"query": {"match_all": {}}}' | grep -E '"total"|"tenant_id"'

echo ""
echo "Acme user (should see ONLY acme-corp documents):"
curl $CURL_OPTS -u "acme_user:AcmePass123!" \
    "https://$OPENSEARCH_HOST/mule-logs-test/_search?pretty" \
    -H "Content-Type: application/json" \
    -d '{"query": {"match_all": {}}}' | grep -E '"total"|"tenant_id"'

echo ""
echo "Globex user (should see ONLY globex documents):"
curl $CURL_OPTS -u "globex_user:GlobexPass123!" \
    "https://$OPENSEARCH_HOST/mule-logs-test/_search?pretty" \
    -H "Content-Type: application/json" \
    -d '{"query": {"match_all": {}}}' | grep -E '"total"|"tenant_id"'

echo ""
echo "=== OpenSearch Setup Complete ==="
echo ""
echo "Summary:"
echo "- Index templates created: mule-logs-*, logstash-*"
echo "- Tenant roles with DLS: tenant_acme-corp, tenant_globex"
echo "- Test users: acme_user (password: AcmePass123!), globex_user (password: GlobexPass123!)"
echo ""
echo "Access URLs:"
echo "- OpenSearch: http://localhost:9080/opensearch"
echo "- OpenSearch Dashboards: http://localhost:9080/dashboards"
echo "- Jaeger UI: http://localhost:9080/jaeger or http://localhost:16686"
echo ""
echo "OpenTelemetry Mule 4 Agent Configuration:"
echo "- OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317"
echo "- OTEL_SERVICE_NAME=mule-application"
echo ""
