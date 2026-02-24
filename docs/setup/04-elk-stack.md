# OpenSearch Stack Configuration

This chapter covers OpenSearch, Logstash, and OpenSearch Dashboards configuration and usage.

> **Note**: This platform was migrated from ELK (ElasticSearch, Kibana) to OpenSearch stack for free Document-Level Security (DLS) support and open-source licensing.

## Overview

The OpenSearch stack provides centralized logging, analytics, and multi-tenant isolation for all platform services.

**Key Components:**
- **OpenSearch**: Search and analytics engine (ElasticSearch-compatible)
- **Logstash**: Log ingestion and processing
- **OpenSearch Dashboards**: Visualization UI (Kibana-compatible)
- **Jaeger**: Distributed tracing with OpenSearch backend

## OpenSearch

### Access

- **Via APISIX**: http://localhost:9080/opensearch
- **Direct (HTTPS)**: https://localhost:9200 (requires auth)
- **Container**: `docker exec opensearch curl ...`

### Authentication

OpenSearch Security is enabled by default:
- **Default credentials**: `admin` / `admin`
- **API calls require** `-u admin:admin` and `-k` (skip cert verification)

### Common Operations

#### Cluster Health
```bash
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/_cluster/health?pretty"
```

#### View All Indices
```bash
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/_cat/indices?v"
```

#### Search Logs
```bash
# All Mule logs
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/mule-logs-*/_search?pretty"

# Errors only
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/mule-logs-*/_search?pretty" \
  -H 'Content-Type: application/json' -d '
{
  "query": {
    "match": { "level": "ERROR" }
  }
}'
```

#### Filter by Tenant
```bash
# Logs for specific tenant
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/mule-logs-*/_search?pretty" \
  -H 'Content-Type: application/json' -d '
{
  "query": {
    "term": { "tenant_id": "acme-corp" }
  }
}'
```

#### Delete Old Indices
```bash
docker exec opensearch curl -s -k -u admin:admin -X DELETE "https://localhost:9200/mule-logs-2024.12.01"
```

### Configuration

Location: `docker-compose.yml`

```yaml
opensearch:
  image: opensearchproject/opensearch:2.11.1
  environment:
    - cluster.name=opensearch-cluster
    - discovery.type=single-node
    - bootstrap.memory_lock=true
    - "OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m"
    - plugins.security.disabled=false  # Security enabled
```

### Document-Level Security (DLS)

OpenSearch provides FREE DLS for multi-tenancy. Each tenant role filters documents by `tenant_id`:

```json
{
  "index_permissions": [{
    "index_patterns": ["mule-logs-*"],
    "dls": "{\"term\": {\"tenant_id\": \"acme-corp\"}}",
    "allowed_actions": ["read", "search"]
  }]
}
```

See [MULTITENANCY_SETUP.md](../MULTITENANCY_SETUP.md) for full setup.

## Logstash

### Access

All Logstash services are routed through APISIX for load balancing:

- **Monitoring API** (via APISIX): http://localhost:9080/logstash
- **TCP Input**: Internal port 5000 (via APISIX stream proxy at 9100)
- **Beats Input**: Internal port 5044 (via APISIX stream proxy at 9144)

### Pipeline Configuration

Location: `config/logstash/pipeline/logstash.conf`

#### Inputs
```ruby
input {
  beats { port => 5044 }
  tcp { port => 5000 codec => json_lines }
  udp { port => 5000 codec => json_lines }
}
```

#### Filters
```ruby
filter {
  # Validate auth token
  if [auth_token] != "${LOGSTASH_AUTH_TOKEN}" {
    drop { }
  }

  # Detect and tag Mule logs
  if [log_type] == "mule" or [application] {
    mutate { add_tag => ["mule"] }
    mutate { add_field => { "[@metadata][target_index]" => "mule-logs" } }
  }

  # Validate tenant_id
  if [tenant_id] {
    if [tenant_id] !~ /^[a-zA-Z0-9\-]{3,50}$/ {
      mutate { add_tag => ["invalid_tenant_id"] }
    }
    mutate { lowercase => ["tenant_id"] }
  } else {
    mutate {
      add_field => { "tenant_id" => "unknown" }
      add_tag => ["missing_tenant_id"]
    }
  }

  # Parse timestamp
  if [timeMillis] {
    date {
      match => ["timeMillis", "UNIX_MS"]
      target => "@timestamp"
    }
  }
}
```

#### Outputs (OpenSearch)
```ruby
output {
  opensearch {
    hosts => ["https://opensearch:9200"]
    user => "admin"
    password => "${OPENSEARCH_PASSWORD:admin}"
    ssl => true
    ssl_certificate_verification => false
    index => "%{[@metadata][target_index]:-logstash}-%{+YYYY.MM.dd}"
  }
}
```

### Monitoring API

Check Logstash health via APISIX:
```bash
# Get Logstash status
curl http://localhost:9080/logstash/

# Get pipeline stats
curl http://localhost:9080/logstash/_node/stats/pipelines?pretty
```

### Testing

#### Test Monitoring API
```bash
curl http://localhost:9080/logstash/
```

#### Test TCP Input with Auth
```bash
echo '{"application":"test","log_type":"mule","level":"INFO","message":"Test","tenant_id":"acme-corp","auth_token":"YOUR_AUTH_TOKEN"}' | nc localhost 5000
```

Check if received:
```bash
docker-compose logs logstash | tail -20
```

## OpenSearch Dashboards

### Access

**Via APISIX**: http://localhost:9080/dashboards

**Credentials**: `admin` / `admin`

### Initial Setup

1. Open OpenSearch Dashboards in browser
2. Navigate to **Stack Management** → **Index Patterns**
3. Create index patterns:
   - `mule-logs-*` (time field: `@timestamp`) - Mule application logs
   - `logstash-*` (time field: `@timestamp`) - General logs
   - `jaeger-span-*` (time field: `startTimeMillis`) - APM traces

### Viewing Logs

1. Go to **Discover**
2. Select index pattern (`mule-logs-*`)
3. Add filters:
   - `application: "ce-mule-base"`
   - `level: "ERROR"`
   - `tenant_id: "acme-corp"`
   - `correlationId: "your-correlation-id"`

### Creating Dashboards

1. Navigate to **Dashboards**
2. Click "Create dashboard"
3. Add visualizations:
   - **Line Chart**: Log volume over time
   - **Pie Chart**: Log levels distribution
   - **Data Table**: Recent error messages
   - **Metric**: Error count by tenant

### Multi-Tenant Views

With DLS enabled, tenant users automatically see only their data:

1. Login as tenant user (e.g., `acme_user`)
2. All queries automatically filtered by `tenant_id`
3. No additional filters needed

## Mule Application Integration

### Log4j2 Configuration

Location: `git/CE-MULE-4-Platform-Backend-Mule/src/main/resources/log4j2.xml`

```xml
<Socket name="LOGSTASH" host="logstash" port="5000" protocol="TCP">
  <JsonTemplateLayout eventTemplateUri="classpath:EcsLayout.json">
    <EventTemplateAdditionalField key="application" value="ce-mule-base"/>
    <EventTemplateAdditionalField key="environment" value="${sys:mule.env}"/>
    <EventTemplateAdditionalField key="worker_id" value="${sys:mule.worker.id:-worker-1}"/>
    <EventTemplateAdditionalField key="log_type" value="mule"/>
    <EventTemplateAdditionalField key="tenant_id" value="${ctx:tenant_id:-unknown}"/>
    <EventTemplateAdditionalField key="auth_token" value="${env:LOGSTASH_AUTH_TOKEN}"/>
  </JsonTemplateLayout>
</Socket>
```

### Log Fields

| Field | Description | Example |
|-------|-------------|---------|
| application | Application name | ce-mule-base |
| environment | Deployment env | local-docker |
| worker_id | Mule worker ID | worker-1 |
| tenant_id | Tenant identifier | acme-corp |
| level | Log level | INFO, ERROR, DEBUG |
| message | Log message | Request processed |
| correlationId | Request correlation ID | uuid-1234 |
| @timestamp | Log timestamp | 2025-12-26T01:42:00Z |

### Querying Mule Logs

```bash
# Find all logs for specific tenant in last hour
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/mule-logs-*/_search?pretty" \
  -H 'Content-Type: application/json' -d '
{
  "query": {
    "bool": {
      "must": [
        { "term": { "tenant_id": "acme-corp" } },
        { "range": { "@timestamp": { "gte": "now-1h" } } }
      ]
    }
  },
  "sort": [{ "@timestamp": "desc" }],
  "size": 10
}'
```

## Data Retention (ISM)

OpenSearch uses Index State Management (ISM) instead of ElasticSearch ILM.

### Current Settings

- Indices created daily: `mule-logs-YYYY.MM.DD`
- Default retention: 2 years
- Data persists in Docker volume

### Manual Cleanup

```bash
# Delete specific index
docker exec opensearch curl -s -k -u admin:admin -X DELETE "https://localhost:9200/mule-logs-2024.12.01"
```

### Automatic Cleanup (ISM Policy)

Create Index State Management policy:

```bash
docker exec opensearch curl -s -k -u admin:admin -X PUT "https://localhost:9200/_plugins/_ism/policies/mule-logs-policy" \
  -H 'Content-Type: application/json' -d '
{
  "policy": {
    "description": "Mule logs retention policy",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": { "min_index_age": "730d" }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [{ "delete": {} }],
        "transitions": []
      }
    ],
    "ism_template": {
      "index_patterns": ["mule-logs-*"],
      "priority": 100
    }
  }
}'
```

## Performance Tuning

### OpenSearch

```yaml
# Increase heap for production (docker-compose.yml)
OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g

# Adjust shard count (index template)
index.number_of_shards: 1
index.number_of_replicas: 0
```

### Logstash

```yaml
# Increase heap
LS_JAVA_OPTS=-Xms512m -Xmx512m

# Worker threads (logstash.yml)
pipeline.workers: 2
pipeline.batch.size: 125
```

## Troubleshooting

### No Logs Appearing

1. Check Logstash connectivity:
```bash
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/_cat/indices?v" | grep mule
```

2. Check Logstash logs:
```bash
docker-compose logs logstash | grep -i error
```

3. Verify auth token:
```bash
echo $LOGSTASH_AUTH_TOKEN
```

### OpenSearch Disk Space

Check disk usage:
```bash
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/_cat/allocation?v"
```

### Security Plugin Issues

If security plugin fails:
```bash
# Check security plugin status
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/_plugins/_security/health"

# View security audit logs
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/security-auditlog-*/_search?pretty&size=10"
```

### DLS Not Working

Verify tenant role has DLS query:
```bash
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/_plugins/_security/api/roles/tenant_acme-corp" | jq
```

## Migration from ElasticSearch

If migrating from ElasticSearch:

| ElasticSearch | OpenSearch Equivalent |
|---------------|----------------------|
| `_ilm/policy` | `_plugins/_ism/policies` |
| X-Pack Security | OpenSearch Security (FREE) |
| `xpack.security.enabled` | `plugins.security.disabled=false` |
| Kibana | OpenSearch Dashboards |

**Key Benefits of OpenSearch:**
- Document-Level Security (DLS) is FREE
- No licensing restrictions
- API-compatible with ElasticSearch 7.x
- Active open-source development

## Next Chapter

Continue to [Chapter 5: Mule Backend](05-mule-backend.md) for Mule application deployment and configuration.
