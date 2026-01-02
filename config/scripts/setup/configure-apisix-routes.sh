#!/bin/bash

# APISIX Route Configuration Script
# Run this after the ELK + APISIX stack is running

set -e

ADMIN_URL="http://localhost:9180/apisix/admin"
ADMIN_KEY="edd1c9f034335f136f87ad84b625c8f1"

echo "Configuring APISIX Routes..."
echo ""

# Test APISIX Admin API
echo "[1/6] Testing APISIX Admin API..."
curl -s "${ADMIN_URL}/routes" -H "X-API-KEY: ${ADMIN_KEY}" > /dev/null
echo "✓ Admin API accessible"

# Create Kibana Route
echo "[2/6] Creating Kibana route..."
curl -s -X PUT "${ADMIN_URL}/routes/kibana" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/kibana/*",
    "name": "kibana-proxy",
    "upstream": {
      "nodes": {
        "kibana:5601": 1
      },
      "type": "roundrobin"
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/kibana(.*)", "$1"]
      }
    }
  }' > /dev/null
echo "✓ Kibana route created"

# Create ElasticSearch Route
echo "[3/6] Creating ElasticSearch route..."
curl -s -X PUT "${ADMIN_URL}/routes/elasticsearch" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/elasticsearch/*",
    "name": "elasticsearch-api",
    "upstream": {
      "nodes": {
        "elasticsearch:9200": 1
      },
      "type": "roundrobin"
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/elasticsearch(.*)", "$1"]
      }
    }
  }' > /dev/null
echo "✓ ElasticSearch route created"

# Create Mule Upstream (Load Balancer)
echo "[4/6] Creating Mule workers upstream..."
curl -s -X PUT "${ADMIN_URL}/upstreams/mule-workers" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mule-workers",
    "type": "roundrobin",
    "nodes": {
      "ce-base-mule-backend:8081": 100
    },
    "checks": {
      "active": {
        "type": "http",
        "http_path": "/api/v1/status",
        "healthy": {
          "interval": 30,
          "http_statuses": [200, 201, 204],
          "successes": 2
        },
        "unhealthy": {
          "interval": 30,
          "http_statuses": [429, 500, 502, 503, 504],
          "http_failures": 3
        }
      }
    }
  }' > /dev/null
echo "✓ Mule upstream created (currently 1 worker - update for 2 workers when new setup is deployed)"

# Create Mule API Route
echo "[5/6] Creating Mule API route..."
curl -s -X PUT "${ADMIN_URL}/routes/mule-api" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/api/*",
    "name": "mule-api",
    "upstream_id": "mule-workers",
    "plugins": {
      "cors": {
        "allow_origins": "**",
        "allow_methods": "**",
        "allow_headers": "**"
      }
    }
  }' > /dev/null
echo "✓ Mule API route created"

# Create ActiveMQ Route
echo "[6/6] Creating ActiveMQ route..."
curl -s -X PUT "${ADMIN_URL}/routes/activemq" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/activemq/*",
    "name": "activemq-console",
    "upstream": {
      "nodes": {
        "ce-base-apachemq-backend:8161": 1
      },
      "type": "roundrobin"
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/activemq(.*)", "$1"]
      }
    }
  }' > /dev/null
echo "✓ ActiveMQ route created"

echo ""
echo "========================================="
echo "APISIX Routes Configured Successfully!"
echo "========================================="
echo ""
echo "Test the routes:"
echo "  - Kibana:        curl http://localhost:9080/kibana"
echo "  - ElasticSearch: curl http://localhost:9080/elasticsearch"
echo "  - Mule API:      curl http://localhost:9080/api/v1/status"
echo "  - ActiveMQ:      curl http://localhost:9080/activemq"
echo ""
echo "APISIX Dashboard: http://localhost:9000 (admin/admin)"
echo ""
