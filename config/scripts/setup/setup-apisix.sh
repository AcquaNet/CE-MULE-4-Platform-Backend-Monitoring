#!/bin/sh
#
# APISIX Route Configuration Script
# This script sets up routes and upstreams via the Admin API
# Alternative to declarative apisix.yaml configuration
#

set -e

APISIX_ADMIN_URL="http://apisix:9180/apisix/admin"

# Load ADMIN_KEY from environment variable or .env file
if [ -z "$APISIX_ADMIN_KEY" ]; then
    if [ -f "$(dirname "$0")/../.env" ]; then
        export $(grep -v '^#' "$(dirname "$0")/../.env" | grep APISIX_ADMIN_KEY | xargs)
    fi
fi

# Fallback to default (dev only) if still not set
ADMIN_KEY="${APISIX_ADMIN_KEY:-edd1c9f034335f136f87ad84b625c8f1}"

if [ "$ADMIN_KEY" = "edd1c9f034335f136f87ad84b625c8f1" ]; then
    echo "WARNING: Using default APISIX admin key. Set APISIX_ADMIN_KEY in .env file for production!"
fi

echo "Waiting for APISIX to be ready..."
until curl -s -f "${APISIX_ADMIN_URL}/routes" -H "X-API-KEY: ${ADMIN_KEY}" > /dev/null 2>&1; do
  echo "APISIX not ready yet, waiting..."
  sleep 5
done

echo "APISIX is ready! Configuring routes and upstreams..."

#
# 1. Create Mule Workers Upstream with Load Balancing and Health Checks
#
echo "Creating Mule workers upstream..."
curl -s -X PUT "${APISIX_ADMIN_URL}/upstreams/1" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mule-workers",
    "desc": "Mule runtime workers with round-robin load balancing",
    "type": "roundrobin",
    "scheme": "http",
    "timeout": {
      "connect": 60,
      "send": 60,
      "read": 60
    },
    "nodes": {
      "ce-base-mule-backend-1:8081": 100,
      "ce-base-mule-backend-2:8081": 100
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
          "http_failures": 3,
          "timeouts": 3
        }
      },
      "passive": {
        "type": "http",
        "healthy": {
          "http_statuses": [200, 201, 202, 204, 206, 301, 302],
          "successes": 5
        },
        "unhealthy": {
          "http_statuses": [429, 500, 502, 503, 504],
          "http_failures": 5,
          "timeouts": 2
        }
      }
    }
  }'

#
# 2. Create Kibana Routes
#
echo "Creating Kibana routes..."

# Redirect /kibana to /kibana/
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/kibana-redirect" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/kibana",
    "name": "kibana-redirect",
    "desc": "Redirect /kibana to /kibana/",
    "priority": 10,
    "plugins": {
      "redirect": {
        "uri": "/kibana/",
        "ret_code": 301
      }
    }
  }'

# Main Kibana route
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/kibana-proxy" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/kibana/*",
    "name": "kibana-proxy",
    "desc": "Kibana web UI and API proxy",
    "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    "upstream": {
      "nodes": {
        "kibana:5601": 1
      },
      "type": "roundrobin",
      "timeout": {
        "connect": 60,
        "send": 60,
        "read": 60
      }
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/kibana(.*)", "$1"]
      },
      "cors": {
        "allow_origins": "**",
        "allow_methods": "**",
        "allow_headers": "**"
      }
    }
  }'

#
# 3. Create ElasticSearch Routes
#
echo "Creating ElasticSearch routes..."
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/elasticsearch-api" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/elasticsearch/*",
    "name": "elasticsearch-api",
    "desc": "ElasticSearch API proxy",
    "methods": ["GET", "POST", "PUT", "DELETE", "HEAD"],
    "upstream": {
      "nodes": {
        "elasticsearch:9200": 1
      },
      "type": "roundrobin",
      "timeout": {
        "connect": 60,
        "send": 60,
        "read": 60
      }
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/elasticsearch(.*)", "$1"]
      }
    }
  }'

#
# 4. Create Logstash Monitoring Upstream with Load Balancing Support
#
echo "Creating Logstash monitoring upstream..."
curl -s -X PUT "${APISIX_ADMIN_URL}/upstreams/2" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "logstash-monitoring",
    "desc": "Logstash monitoring API with load balancing support",
    "type": "roundrobin",
    "scheme": "http",
    "timeout": {
      "connect": 30,
      "send": 30,
      "read": 30
    },
    "nodes": {
      "logstash:9600": 100
    },
    "checks": {
      "active": {
        "type": "http",
        "http_path": "/",
        "healthy": {
          "interval": 30,
          "http_statuses": [200],
          "successes": 2
        },
        "unhealthy": {
          "interval": 30,
          "http_statuses": [500, 502, 503, 504],
          "http_failures": 3
        }
      }
    }
  }'

#
# 4a. Create Logstash Monitoring API Route
#
echo "Creating Logstash monitoring routes..."
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/logstash-api" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/logstash/*",
    "name": "logstash-api",
    "desc": "Logstash monitoring API - load balanced",
    "methods": ["GET", "POST"],
    "upstream_id": "2",
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/logstash(.*)", "$1"]
      }
    }
  }'

#
# 4a. Create APM Server Routes
#
echo "Creating APM Server routes..."
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/apm-server-api" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/apm-server/*",
    "name": "apm-server-api",
    "desc": "APM Server data ingestion and API",
    "methods": ["GET", "POST"],
    "upstream": {
      "nodes": {
        "apm-server:8200": 1
      },
      "type": "roundrobin",
      "timeout": {
        "connect": 60,
        "send": 60,
        "read": 60
      }
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/apm-server(.*)", "$1"]
      }
    }
  }'

#
# 5. Create Mule API Routes (Load Balanced)
#
echo "Creating Mule API routes..."
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/mule-api-v1" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/api/v1/*",
    "name": "mule-api-v1",
    "desc": "Mule API v1 - load balanced",
    "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    "upstream_id": "1",
    "plugins": {
      "cors": {
        "allow_origins": "**",
        "allow_methods": "**",
        "allow_headers": "**"
      },
      "prometheus": {
        "prefer_name": true
      }
    }
  }'

curl -s -X PUT "${APISIX_ADMIN_URL}/routes/mule-api-all" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/api/*",
    "name": "mule-api-all",
    "desc": "Mule API all versions - load balanced",
    "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    "upstream_id": "1",
    "plugins": {
      "cors": {
        "allow_origins": "**",
        "allow_methods": "**",
        "allow_headers": "**"
      },
      "prometheus": {
        "prefer_name": true
      }
    }
  }'

#
# 6. Create ActiveMQ Web Console Route
#
echo "Creating ActiveMQ routes..."
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/activemq-console" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/activemq/*",
    "name": "activemq-console",
    "desc": "ActiveMQ web console",
    "methods": ["GET", "POST", "PUT", "DELETE"],
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
  }'

#
# 6a. Create Prometheus Routes
#
echo "Creating Prometheus routes..."

# Redirect /prometheus to /prometheus/
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/prometheus-redirect" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/prometheus",
    "name": "prometheus-redirect",
    "desc": "Redirect /prometheus to /prometheus/",
    "priority": 10,
    "plugins": {
      "redirect": {
        "uri": "/prometheus/",
        "ret_code": 301
      }
    }
  }'

# Main Prometheus route
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/prometheus-proxy" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/prometheus/*",
    "name": "prometheus-proxy",
    "desc": "Prometheus metrics and query UI",
    "methods": ["GET", "POST"],
    "upstream": {
      "nodes": {
        "prometheus:9090": 1
      },
      "type": "roundrobin",
      "timeout": {
        "connect": 60,
        "send": 60,
        "read": 60
      }
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/prometheus(.*)", "$1"]
      }
    }
  }'

#
# 6b. Create Grafana Routes
#
echo "Creating Grafana routes..."

# Redirect /grafana to /grafana/
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/grafana-redirect" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/grafana",
    "name": "grafana-redirect",
    "desc": "Redirect /grafana to /grafana/",
    "priority": 10,
    "plugins": {
      "redirect": {
        "uri": "/grafana/",
        "ret_code": 301
      }
    }
  }'

# Main Grafana route
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/grafana-proxy" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/grafana/*",
    "name": "grafana-proxy",
    "desc": "Grafana metrics visualization dashboards",
    "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    "upstream": {
      "nodes": {
        "grafana:3000": 1
      },
      "type": "roundrobin",
      "timeout": {
        "connect": 60,
        "send": 60,
        "read": 60
      }
    },
    "plugins": {
      "cors": {
        "allow_origins": "**",
        "allow_methods": "**",
        "allow_headers": "**"
      },
      "response-rewrite": {
        "headers": {
          "remove": ["X-Frame-Options"]
        }
      }
    }
  }'

#
# 7. Create APISIX Dashboard Route at Root Path
#
echo "Creating APISIX Dashboard route at root..."

# Dashboard at root path - no subpath issues since assets load from /
curl -s -X PUT "${APISIX_ADMIN_URL}/routes/apisix-dashboard-root" \
  -H "X-API-KEY: ${ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/*",
    "name": "apisix-dashboard-root",
    "desc": "APISIX Dashboard web UI at root path",
    "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    "priority": 1,
    "upstream": {
      "nodes": {
        "apisix-dashboard:9000": 1
      },
      "type": "roundrobin",
      "timeout": {
        "connect": 60,
        "send": 60,
        "read": 60
      }
    }
  }'

echo ""
echo "APISIX configuration completed successfully!"
echo ""
echo "Available endpoints:"
echo "  - APISIX Dashboard: http://your-server:9080/ (root path)"
echo "  - Grafana:          http://your-server:9080/grafana"
echo "  - Prometheus:       http://your-server:9080/prometheus"
echo "  - Kibana:           http://your-server:9080/kibana"
echo "  - ElasticSearch:    http://your-server:9080/elasticsearch"
echo "  - Logstash API:     http://your-server:9080/logstash"
echo "  - APM Server:       http://your-server:9080/apm-server"
echo "  - Mule API:         http://your-server:9080/api/v1/status"
echo "  - ActiveMQ:         http://your-server:9080/activemq"
echo ""
echo "Admin API: http://your-server:9180/apisix/admin"
echo ""
