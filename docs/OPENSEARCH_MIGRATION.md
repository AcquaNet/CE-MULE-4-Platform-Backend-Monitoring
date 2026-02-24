# OpenSearch Migration Guide

This document describes the migration from ELK Stack (ElasticSearch, Logstash, Kibana) to OpenSearch Stack (OpenSearch, Logstash, OpenSearch Dashboards, Jaeger).

## Why Migrate to OpenSearch?

### Key Benefits

| Feature | ELK Stack | OpenSearch Stack |
|---------|-----------|------------------|
| **Document-Level Security** | Paid (X-Pack Platinum) | **FREE** |
| **Licensing** | Elastic License 2.0 | Apache 2.0 |
| **Multi-Tenancy** | Requires paid license | Built-in, free |
| **APM/Tracing** | Elastic APM (proprietary) | Jaeger (CNCF, open source) |
| **Instrumentation** | Elastic APM agents | OpenTelemetry (vendor neutral) |

### Document-Level Security (DLS)

The primary driver for this migration was **Document-Level Security (DLS)** for multi-tenancy:

- **ELK Stack**: DLS requires X-Pack Platinum license ($$$)
- **OpenSearch**: DLS is **completely free** and built into OpenSearch Security

With DLS, each tenant can only see logs with their `tenant_id`, enforced at the database level.

---

## Component Mapping

| ELK Component | OpenSearch Replacement | Version |
|---------------|----------------------|---------|
| ElasticSearch 8.11.3 | OpenSearch 2.11.1 | API compatible |
| Kibana 8.11.3 | OpenSearch Dashboards 2.11.1 | UI compatible |
| APM Server 8.10.4 | Jaeger 1.52.0 | OTLP protocol |
| Elastic APM Agent | OpenTelemetry Mule 4 Agent 0.1.0 | Custom agent |
| X-Pack Security | OpenSearch Security | Built-in, free |

---

## Configuration Changes

### Docker Compose

#### Before (ELK)

```yaml
elasticsearch:
  image: docker.elastic.co/elasticsearch/elasticsearch:8.11.3
  environment:
    - xpack.security.enabled=true
    - ELASTIC_PASSWORD=${ELASTIC_PASSWORD}

kibana:
  image: docker.elastic.co/kibana/kibana:8.11.3
  environment:
    - ELASTICSEARCH_HOSTS=http://elasticsearch:9200

apm-server:
  image: docker.elastic.co/apm/apm-server:8.10.4
  command: >
    -E apm-server.host=0.0.0.0:8200
    -E output.elasticsearch.hosts=["http://elasticsearch:9200"]
```

#### After (OpenSearch)

```yaml
opensearch:
  image: opensearchproject/opensearch:2.11.1
  environment:
    - cluster.name=opensearch-cluster
    - discovery.type=single-node
    - plugins.security.disabled=false
    - OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m

opensearch-dashboards:
  image: opensearchproject/opensearch-dashboards:2.11.1
  environment:
    - OPENSEARCH_HOSTS=["https://opensearch:9200"]

jaeger:
  image: jaegertracing/all-in-one:1.52
  environment:
    - SPAN_STORAGE_TYPE=opensearch
    - ES_SERVER_URLS=https://opensearch:9200
    - ES_USERNAME=admin
    - ES_PASSWORD=admin
    - COLLECTOR_OTLP_ENABLED=true
```

### Logstash Pipeline

#### Before (ElasticSearch output)

```ruby
output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    user => "elastic"
    password => "${ELASTIC_PASSWORD}"
    index => "mule-logs-%{+YYYY.MM.dd}"
  }
}
```

#### After (OpenSearch output)

```ruby
output {
  opensearch {
    hosts => ["https://opensearch:9200"]
    user => "admin"
    password => "${OPENSEARCH_PASSWORD:-admin}"
    ssl => true
    ssl_certificate_verification => false
    index => "mule-logs-%{+YYYY.MM.dd}"
  }
}
```

### Mule APM Configuration

#### Before (Elastic APM)

```yaml
environment:
  JAVA_OPTS: >-
    -Delastic.apm.server_urls=http://apm-server:8200
    -Delastic.apm.service_name=ce-mule-base-worker-1
    -Delastic.apm.secret_token=${APM_SECRET_TOKEN}
```

#### After (OpenTelemetry)

```yaml
environment:
  OTEL_SERVICE_NAME: ce-mule-base-worker-1
  OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
  OTEL_EXPORTER_OTLP_PROTOCOL: grpc
  OTEL_TRACES_EXPORTER: otlp
  OTEL_METRICS_EXPORTER: none
  OTEL_LOGS_EXPORTER: none
```

### tracer.xml

#### Before (Elastic APM classes)

```xml
<object name="_apmStarter" class="co.elastic.apm.mule4.agent.ApmStarter" />
<object name="_apmPipelineNotifications" class="co.elastic.apm.mule4.agent.ApmPipelineNotificationListener" />
```

#### After (OpenTelemetry classes)

```xml
<object name="_otelStarter" class="io.opentelemetry.mule4.agent.OtelStarter" />
<object name="_otelPipelineNotifications" class="io.opentelemetry.mule4.agent.OtelPipelineNotificationListener" />
<object name="_otelMessageProcessorNotifications" class="io.opentelemetry.mule4.agent.OtelMessageProcessorNotificationListener" />
<object name="_otelExceptionNotifications" class="io.opentelemetry.mule4.agent.OtelExceptionNotificationListener" />
```

---

## API Compatibility

### OpenSearch vs ElasticSearch API

OpenSearch is API-compatible with ElasticSearch 7.x. Most queries work unchanged.

#### Index Management

```bash
# ElasticSearch ILM
PUT _ilm/policy/mule-logs-policy

# OpenSearch ISM
PUT _plugins/_ism/policies/mule-logs-policy
```

#### Security API

```bash
# ElasticSearch X-Pack
GET _security/user

# OpenSearch Security
GET _plugins/_security/api/internalusers
```

#### Document-Level Security

```bash
# OpenSearch - Create role with DLS
PUT _plugins/_security/api/roles/tenant_acme-corp
{
  "index_permissions": [{
    "index_patterns": ["mule-logs-*"],
    "dls": "{\"term\": {\"tenant_id\": \"acme-corp\"}}",
    "allowed_actions": ["read", "search"]
  }]
}
```

---

## Access URLs

| Service | ELK URL | OpenSearch URL |
|---------|---------|----------------|
| Search Engine | http://localhost:9200 | https://localhost:9200 |
| Web UI | http://localhost:9080/kibana | http://localhost:9080/dashboards |
| APM/Traces | http://localhost:9080/kibana/app/apm | http://localhost:16686/jaeger/ |
| API Docs | /_cat/indices | /_cat/indices |

---

## Index Patterns

### Logs

| Type | Index Pattern | Time Field |
|------|---------------|------------|
| Mule Logs | `mule-logs-*` | `@timestamp` |
| General Logs | `logstash-*` | `@timestamp` |

### Traces

| Type | Index Pattern | Time Field |
|------|---------------|------------|
| Jaeger Spans | `jaeger-span-*` | `startTimeMillis` |
| Jaeger Services | `jaeger-service-*` | N/A |

---

## Authentication

### Default Credentials

| Service | ELK | OpenSearch |
|---------|-----|------------|
| Admin User | elastic | admin |
| Default Password | From .env | admin |
| API Access | Bearer token or basic auth | Basic auth with `-k` for SSL |

### Example API Calls

```bash
# ELK
curl -u elastic:$ELASTIC_PASSWORD http://localhost:9200/_cat/indices

# OpenSearch
curl -k -u admin:admin https://localhost:9200/_cat/indices

# Or via container
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/_cat/indices"
```

---

## Multi-Tenancy Setup

### Creating Tenant Role with DLS

```bash
# Create role
curl -k -u admin:admin -X PUT "https://localhost:9200/_plugins/_security/api/roles/tenant_acme-corp" \
  -H "Content-Type: application/json" -d '{
  "cluster_permissions": [],
  "index_permissions": [{
    "index_patterns": ["mule-logs-*"],
    "dls": "{\"term\": {\"tenant_id\": \"acme-corp\"}}",
    "allowed_actions": ["read", "search"]
  }]
}'

# Create user
curl -k -u admin:admin -X PUT "https://localhost:9200/_plugins/_security/api/internalusers/acme_user" \
  -H "Content-Type: application/json" -d '{
  "password": "SecurePassword123!",
  "opendistro_security_roles": ["tenant_acme-corp"]
}'

# Map user to role
curl -k -u admin:admin -X PUT "https://localhost:9200/_plugins/_security/api/rolesmapping/tenant_acme-corp" \
  -H "Content-Type: application/json" -d '{
  "users": ["acme_user"]
}'
```

### Verify DLS

```bash
# Admin sees all logs
docker exec opensearch curl -s -k -u admin:admin \
  "https://localhost:9200/mule-logs-*/_search" | grep -o '"tenant_id":"[^"]*"' | sort | uniq -c

# Tenant user sees only their logs
docker exec opensearch curl -s -k -u acme_user:SecurePassword123! \
  "https://localhost:9200/mule-logs-*/_search" | grep -o '"tenant_id":"[^"]*"' | sort | uniq -c
```

---

## Migration Steps

### 1. Update Docker Compose

Replace ELK services with OpenSearch services in `docker-compose.yml`.

### 2. Update APISIX Routes

Use `apisix-opensearch.yaml` instead of `apisix.yaml` for route configuration.

### 3. Update Logstash Pipeline

Change output from `elasticsearch` to `opensearch` plugin.

### 4. Build OpenTelemetry Agent

```bash
cd git/elastic-apm-mule4-agent/otel-mule4-agent
mvn clean package -DskipTests
```

### 5. Deploy OTEL Agent to Mule Workers

Copy `otel-mule4-agent-0.1.0.jar` to each worker's `lib/` folder.

### 6. Update tracer.xml

Replace Elastic APM classes with OpenTelemetry classes.

### 7. Update Environment Variables

Change from `elastic.apm.*` to `OTEL_*` variables.

### 8. Create Index Patterns

Create index patterns in OpenSearch Dashboards:
- `mule-logs-*` (time field: `@timestamp`)
- `jaeger-span-*` (time field: `startTimeMillis`)

### 9. Set Up Multi-Tenancy

Run tenant setup scripts to create DLS roles.

---

## Rollback Plan

If issues occur, you can rollback by:

1. Stopping OpenSearch stack: `docker-compose down`
2. Switching to ELK docker-compose: Use original `docker-compose.yml`
3. Reverting Mule agent to Elastic APM
4. Restarting services

Data in OpenSearch volumes is separate from ELK volumes, so no data loss occurs.

---

## Troubleshooting

### OpenSearch Won't Start

```bash
# Check logs
docker logs opensearch

# Common fix: increase vm.max_map_count
sudo sysctl -w vm.max_map_count=262144
```

### Jaeger Not Receiving Traces

```bash
# Verify OTLP endpoint
docker exec ce-base-mule-backend-1 nc -zv jaeger 4317

# Check Jaeger logs
docker logs jaeger | grep -i error
```

### DLS Not Working

```bash
# Verify role exists
docker exec opensearch curl -s -k -u admin:admin \
  "https://localhost:9200/_plugins/_security/api/roles/tenant_acme-corp"

# Verify user mapping
docker exec opensearch curl -s -k -u admin:admin \
  "https://localhost:9200/_plugins/_security/api/rolesmapping/tenant_acme-corp"
```

---

## References

- [OpenSearch Documentation](https://opensearch.org/docs/latest/)
- [OpenSearch Security](https://opensearch.org/docs/latest/security/index/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [OpenTelemetry Java](https://opentelemetry.io/docs/languages/java/)
