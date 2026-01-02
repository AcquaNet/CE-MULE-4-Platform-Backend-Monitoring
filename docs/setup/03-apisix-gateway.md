# APISIX Gateway Configuration

This chapter covers Apache APISIX gateway configuration, route management, and load balancing.

## Overview

Apache APISIX is a high-performance API gateway that provides:
- Reverse proxy and load balancing
- Dynamic routing
- Active health checks
- Prometheus metrics
- Plugin system for authentication, rate limiting, etc.

## APISIX Components

### 1. APISIX Gateway

**Access Points:**
- HTTP Gateway: `http://localhost:9080`
- HTTPS Gateway: `https://localhost:9443`
- Admin API: `http://localhost:9180`
- Prometheus Metrics: `http://localhost:9091/apisix/prometheus/metrics`

### 2. etcd Configuration Store

**Purpose:** Stores APISIX configuration (routes, upstreams, plugins)

**Access:** `http://localhost:2379`

**Note:** All APISIX configuration changes are stored in etcd and applied dynamically (no restart required)

### 3. APISIX Dashboard

**Access:** `http://localhost:9000`

**Credentials:** admin / admin

**Features:**
- Visual route management
- Upstream configuration
- Plugin management
- Real-time monitoring
- API testing

## Current Route Configuration

### Mule API Route

**Route ID:** `mule-api`

**Configuration:**
```json
{
  "uri": "/api/*",
  "name": "mule-api-loadbalanced",
  "upstream": {
    "nodes": {
      "ce-base-mule-backend-1:8081": 100,
      "ce-base-mule-backend-2:8081": 100
    },
    "type": "roundrobin",
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
  },
  "plugins": {
    "cors": {
      "allow_origins": "**",
      "allow_methods": "**",
      "allow_headers": "**"
    }
  }
}
```

**Features:**
- Round-robin load balancing across 2 Mule workers
- Equal weight (100) for each worker
- Active health checks every 30 seconds
- Automatic failover if worker becomes unhealthy
- CORS enabled for browser clients

### Testing the Route

```bash
# Test the load-balanced Mule API
curl http://localhost:9080/api/v1/status

# Send multiple requests to see load distribution
for i in {1..10}; do
  echo "Request #$i:"
  curl -s http://localhost:9080/api/v1/status
  echo ""
done
```

## Managing Routes via Admin API

### View All Routes

```bash
curl http://localhost:9180/apisix/admin/routes \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

### View Specific Route

```bash
curl http://localhost:9180/apisix/admin/routes/mule-api \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

### Create New Route

```bash
curl -X PUT "http://localhost:9180/apisix/admin/routes/my-route" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/my-service/*",
    "name": "my-service-route",
    "upstream": {
      "nodes": {
        "backend-service:8080": 1
      },
      "type": "roundrobin"
    }
  }'
```

### Update Existing Route

```bash
curl -X PATCH "http://localhost:9180/apisix/admin/routes/mule-api" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "plugins": {
      "cors": {
        "allow_origins": "http://specific-domain.com"
      }
    }
  }'
```

### Delete Route

```bash
curl -X DELETE "http://localhost:9180/apisix/admin/routes/my-route" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

## Configuring Additional Routes

### Kibana Route

```bash
curl -X PUT "http://localhost:9180/apisix/admin/routes/kibana" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/kibana/*",
    "name": "kibana-proxy",
    "upstream": {
      "nodes": {"kibana:5601": 1},
      "type": "roundrobin"
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/kibana(.*)", "$1"]
      }
    }
  }'
```

### ElasticSearch Route

```bash
curl -X PUT "http://localhost:9180/apisix/admin/routes/elasticsearch" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/elasticsearch/*",
    "name": "elasticsearch-api",
    "upstream": {
      "nodes": {"elasticsearch:9200": 1},
      "type": "roundrobin"
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/elasticsearch(.*)", "$1"]
      }
    }
  }'
```

### Logstash Monitoring API Route

The Logstash route uses an upstream for load balancing support across multiple Logstash instances.

**Step 1: Create Logstash Upstream**
```bash
curl -X PUT "http://localhost:9180/apisix/admin/upstreams/2" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
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
```

**Step 2: Create Logstash Route**
```bash
curl -X PUT "http://localhost:9180/apisix/admin/routes/logstash-api" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
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
```

**Testing:**
```bash
# Get Logstash status
curl http://localhost:9080/logstash/

# Get pipeline stats
curl http://localhost:9080/logstash/_node/stats/pipelines?pretty
```

**Adding Multiple Logstash Instances:**
```bash
# Update upstream to include logstash-2
curl -X PATCH "http://localhost:9180/apisix/admin/upstreams/2" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "nodes": {
      "logstash:9600": 100,
      "logstash-2:9600": 100
    }
  }'
```

**Note on TCP/UDP Log Ingestion:**
- Logstash TCP/UDP ports (5000, 5044) are internal-only by default
- For direct access, uncomment ports in `docker-compose.yml`
- For multiple Logstash instances with TCP/UDP load balancing, use external load balancer (HAProxy/nginx)

### ActiveMQ Console Route

```bash
curl -X PUT "http://localhost:9180/apisix/admin/routes/activemq" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "/activemq/*",
    "name": "activemq-console",
    "upstream": {
      "nodes": {"ce-base-apachemq-backend:8161": 1},
      "type": "roundrobin"
    },
    "plugins": {
      "proxy-rewrite": {
        "regex_uri": ["^/activemq(.*)", "$1"]
      }
    }
  }'
```

## Load Balancing Configuration

### Load Balancing Algorithms

APISIX supports multiple load balancing algorithms:

**1. Round Robin (Current)**
```json
{
  "type": "roundrobin",
  "nodes": {
    "worker1:8081": 100,
    "worker2:8081": 100
  }
}
```
Distributes requests evenly across all workers.

**2. Weighted Round Robin**
```json
{
  "type": "roundrobin",
  "nodes": {
    "worker1:8081": 200,
    "worker2:8081": 100
  }
}
```
Worker 1 receives 2x more traffic than Worker 2.

**3. Consistent Hash**
```json
{
  "type": "chash",
  "hash_on": "header",
  "key": "user-id",
  "nodes": {
    "worker1:8081": 1,
    "worker2:8081": 1
  }
}
```
Routes requests based on hash of specified key (sticky sessions).

**4. Least Connections**
```json
{
  "type": "least_conn",
  "nodes": {
    "worker1:8081": 1,
    "worker2:8081": 1
  }
}
```
Routes to worker with fewest active connections.

### Health Check Configuration

#### Active Health Checks (Current)

Periodically polls upstream services:

```json
{
  "checks": {
    "active": {
      "type": "http",
      "http_path": "/api/v1/status",
      "timeout": 1,
      "concurrency": 10,
      "healthy": {
        "interval": 30,
        "http_statuses": [200, 201, 204],
        "successes": 2
      },
      "unhealthy": {
        "interval": 30,
        "http_statuses": [429, 500, 502, 503, 504],
        "http_failures": 3,
        "tcp_failures": 2,
        "timeouts": 3
      }
    }
  }
}
```

**Parameters:**
- `interval`: Seconds between health checks
- `http_statuses`: Status codes considered healthy/unhealthy
- `successes`: Consecutive successes to mark healthy
- `http_failures`: Consecutive failures to mark unhealthy

#### Passive Health Checks

Monitor actual request traffic to detect failures:

```json
{
  "checks": {
    "passive": {
      "type": "http",
      "healthy": {
        "http_statuses": [200, 201, 202, 203, 204, 205, 206, 207, 208, 226, 300, 301, 302, 303, 304, 305, 306, 307, 308],
        "successes": 5
      },
      "unhealthy": {
        "http_statuses": [429, 500, 502, 503, 504],
        "http_failures": 3,
        "tcp_failures": 2
      }
    }
  }
}
```

### Viewing Upstream Health Status

```bash
# View all upstreams
curl http://localhost:9180/apisix/admin/upstreams \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"

# Check health status in APISIX Dashboard
# Navigate to: http://localhost:9000 → Upstream → View Details
```

## Plugins

### CORS Plugin (Enabled)

Allows cross-origin requests from browsers:

```json
{
  "cors": {
    "allow_origins": "**",
    "allow_methods": "**",
    "allow_headers": "**",
    "max_age": 5,
    "expose_headers": "*"
  }
}
```

### Rate Limiting Plugin

Limit requests per IP address:

```json
{
  "limit-count": {
    "count": 100,
    "time_window": 60,
    "key": "remote_addr",
    "rejected_code": 429
  }
}
```

### JWT Authentication Plugin

Require JWT token for access:

```json
{
  "jwt-auth": {
    "key": "user-key",
    "secret": "my-secret-key",
    "algorithm": "HS256"
  }
}
```

### IP Restriction Plugin

Whitelist/blacklist IP addresses:

```json
{
  "ip-restriction": {
    "whitelist": ["192.168.1.0/24", "10.0.0.0/8"]
  }
}
```

## Monitoring and Metrics

### Prometheus Metrics

```bash
curl http://localhost:9091/apisix/prometheus/metrics
```

**Key Metrics:**
- `apisix_http_status`: HTTP status code counts
- `apisix_http_latency`: Request latency histogram
- `apisix_bandwidth`: Bandwidth usage
- `apisix_upstream_status`: Upstream health status

### APISIX Logs

```bash
# View APISIX error logs
docker logs apisix 2>&1 | grep ERROR

# View APISIX access logs
docker logs apisix 2>&1 | grep "GET\|POST\|PUT\|DELETE"

# Follow live logs
docker logs -f apisix
```

### Dashboard Monitoring

Access http://localhost:9000 for:
- Real-time request metrics
- Route performance
- Upstream health status
- Error rate tracking

## Security Best Practices

### Production Checklist

- [ ] Change APISIX admin API key from default
- [ ] Enable HTTPS with valid SSL/TLS certificates
- [ ] Restrict Admin API to internal network only
- [ ] Enable authentication on public routes (JWT, API Key, OAuth)
- [ ] Implement rate limiting to prevent abuse
- [ ] Add IP whitelisting for sensitive endpoints
- [ ] Enable request/response size limits
- [ ] Configure CORS with specific allowed origins
- [ ] Monitor and alert on unusual traffic patterns
- [ ] Regularly rotate credentials and keys

### Changing Admin API Key

1. Edit `apisix-config/config/config.yaml`:
```yaml
deployment:
  admin:
    admin_key:
      - name: "admin"
        key: "your-new-secure-key-here"  # Change this!
```

2. Restart APISIX:
```bash
docker-compose restart apisix
```

3. Use new key in API calls:
```bash
curl http://localhost:9180/apisix/admin/routes \
  -H "X-API-KEY: your-new-secure-key-here"
```

## Troubleshooting

### Route Not Working

1. Verify route exists:
```bash
curl http://localhost:9180/apisix/admin/routes/mule-api \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

2. Check APISIX logs:
```bash
docker logs apisix | tail -50
```

3. Test upstream directly:
```bash
docker exec ce-base-mule-backend-1 curl http://localhost:8081/api/v1/status
```

### 502 Bad Gateway

**Causes:**
- Upstream service not running
- Health check failing
- Network connectivity issue

**Debug:**
```bash
# Check if upstream is healthy
docker ps | grep mule-backend

# Test direct connection
docker exec apisix curl http://ce-base-mule-backend-1:8081/api/v1/status

# Check route configuration
curl http://localhost:9180/apisix/admin/routes/mule-api \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

### Health Checks Failing

1. Check health check endpoint:
```bash
docker exec ce-base-mule-backend-1 curl http://localhost:8081/api/v1/status
```

2. Review health check configuration:
- Ensure `http_path` is correct
- Verify `http_statuses` includes actual response codes
- Check `interval` is reasonable (not too frequent)

3. Temporarily disable health checks for testing:
```bash
curl -X PATCH "http://localhost:9180/apisix/admin/routes/mule-api" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "upstream": {
      "checks": null
    }
  }'
```

## Next Chapter

Continue to [Chapter 4: ELK Stack](04-elk-stack.md) to learn about ElasticSearch, Logstash, and Kibana configuration.
