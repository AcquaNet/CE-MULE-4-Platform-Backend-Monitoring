# ELK Stack Configuration

This chapter covers ElasticSearch, Logstash, and Kibana configuration and usage.

## Overview

The ELK stack provides centralized logging and analytics for all platform services.

## ElasticSearch

### Access

- **Via APISIX**: http://localhost:9080/elasticsearch
- **Direct (internal)**: http://elasticsearch:9200

### Common Operations

#### Cluster Health
```bash
curl http://localhost:9080/elasticsearch/_cluster/health?pretty
```

#### View All Indices
```bash
curl http://localhost:9080/elasticsearch/_cat/indices?v
```

#### Search Logs
```bash
# All Mule logs
curl http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty

# Errors only
curl -X POST http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty \
  -H 'Content-Type: application/json' -d '
{
  "query": {
    "match": { "level": "ERROR" }
  }
}'
```

#### Delete Old Indices
```bash
curl -X DELETE "http://localhost:9080/elasticsearch/mule-logs-2024.12.01"
```

### Configuration

Location: `docker-compose.yml`

```yaml
elasticsearch:
  environment:
    - ES_JAVA_OPTS=-Xms512m -Xmx512m  # Heap size
    - xpack.security.enabled=false     # Security (enable in prod!)
```

## Logstash

### Access

All Logstash services are routed through APISIX for load balancing and centralized management:

- **Monitoring API** (via APISIX): http://localhost:9080/logstash (load balanced, health checked)
- **Beats Input** (optional): localhost:5044 (internal by default, uncomment ports in docker-compose.yml for external access)
- **TCP/UDP Input** (optional): localhost:5000 (internal by default, uncomment ports in docker-compose.yml for external access)

**Note**: For production deployments with multiple Logstash instances, use an external TCP load balancer (HAProxy/nginx) for TCP/UDP inputs. HTTP monitoring API is automatically load balanced via APISIX.

### Pipeline Configuration

Location: `logstash/pipeline/logstash.conf`

#### Inputs
```
input {
  beats { port => 5044 }
  tcp { port => 5000 codec => json_lines }
  udp { port => 5000 codec => json_lines }
}
```

#### Filters
```
filter {
  # Detect Mule logs
  if [log_type] == "mule" or [application] {
    mutate { add_tag => ["mule"] }
    mutate { add_field => { "[@metadata][target_index]" => "mule-logs" } }
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

#### Outputs
```
output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "%{[@metadata][target_index]:-logstash}-%{+YYYY.MM.dd}"
  }
}
```

### Monitoring API

Check Logstash health and status via APISIX:
```bash
# Get Logstash status (via APISIX - load balanced)
curl http://localhost:9080/logstash/

# Get pipeline stats
curl http://localhost:9080/logstash/_node/stats/pipelines?pretty

# Get plugin stats
curl http://localhost:9080/logstash/_node/stats/plugins?pretty
```

Example response:
```json
{
  "host": "118e7b367542",
  "version": "8.11.3",
  "status": "green",
  "pipeline": {
    "workers": 32,
    "batch_size": 125,
    "batch_delay": 50
  }
}
```

### Testing

#### Test Monitoring API (Always Available)
```bash
curl http://localhost:9080/logstash/
```

#### Test TCP Input (Requires Uncommented Ports)

**Note**: TCP/UDP ports are internal-only by default. To test, uncomment ports in `docker-compose.yml`:
```yaml
ports:
  - "5000:5000/tcp"
  - "5000:5000/udp"
```

Then send test log:
```bash
echo '{"application":"test-app","level":"INFO","message":"Test log"}' | nc localhost 5000
```

Check if received:
```bash
docker-compose logs logstash | tail -20
```

### Scaling Logstash

To add multiple Logstash instances for high availability:

1. **Update docker-compose.yml** to add logstash-2:
```yaml
logstash-2:
  image: docker.elastic.co/logstash/logstash:8.11.3
  container_name: logstash-2
  environment:
    - "LS_JAVA_OPTS=-Xms256m -Xmx256m"
    - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
  volumes:
    - ./logstash/config/logstash.yml:/usr/share/logstash/config/logstash.yml:ro
    - ./logstash/pipeline:/usr/share/logstash/pipeline:ro
  expose:
    - "5000"
    - "5044"
    - "9600"
  networks:
    ce-base-micronet:
      ipv4_address: 172.42.0.14
    ce-base-network:
```

2. **Update APISIX upstream** to include both instances:
```bash
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

3. **For TCP/UDP load balancing**, use external load balancer:
   - HAProxy with TCP mode
   - nginx stream module
   - Cloud provider TCP load balancer

## Kibana

### Access

**Via APISIX**: http://localhost:9080/kibana

### Initial Setup

1. Open Kibana in browser
2. Navigate to Management → Stack Management → Index Patterns
3. Create index patterns:
   - `mule-logs-*` for Mule application logs
   - `logstash-*` for general logs

### Viewing Logs

1. Go to Analytics → Discover
2. Select index pattern (`mule-logs-*`)
3. Add filters:
   - `application: "ce-mule-base"`
   - `level: "ERROR"`
   - `correlationId: "your-correlation-id"`

### Creating Dashboards

1. Navigate to Analytics → Dashboard
2. Click "Create dashboard"
3. Add visualizations:
   - **Line Chart**: Log volume over time
   - **Pie Chart**: Log levels distribution
   - **Data Table**: Recent error messages

## Mule Application Integration

### Log4j2 Configuration

Location: `git/CE-MULE-4-Platform-Backend-Mule/src/main/resources/log4j2.xml`

```xml
<Socket name="LOGSTASH" host="logstash" port="5000" protocol="TCP">
  <JsonTemplateLayout eventTemplateUri="classpath:EcsLayout.json">
    <EventTemplateAdditionalField key="application" value="ce-mule-base"/>
    <EventTemplateAdditionalField key="environment" value="${sys:mule.env}"/>
    <EventTemplateAdditionalField key="log_type" value="mule"/>
  </JsonTemplateLayout>
</Socket>
```

### Log Fields

| Field | Description | Example |
|-------|-------------|---------|
| application | Application name | ce-mule-base |
| environment | Deployment env | local-docker |
| level | Log level | INFO, ERROR, DEBUG |
| message | Log message | Request processed |
| correlationId | Request correlation ID | uuid-1234 |
| @timestamp | Log timestamp | 2025-12-26T01:42:00Z |

### Querying Mule Logs

```bash
# Find all logs for specific application
curl -X POST http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty \
  -H 'Content-Type: application/json' -d '
{
  "query": {
    "bool": {
      "must": [
        { "match": { "application": "ce-mule-base" } },
        { "range": { "@timestamp": { "gte": "now-1h" } } }
      ]
    }
  },
  "sort": [{ "@timestamp": "desc" }],
  "size": 10
}'
```

## Data Retention

### Current Settings

- Indices created daily: `mule-logs-YYYY.MM.DD`
- No automatic deletion
- Data persists in Docker volume

### Manual Cleanup

```bash
# Delete indices older than 30 days
curl -X DELETE "http://localhost:9080/elasticsearch/mule-logs-$(date -d '30 days ago' +%Y.%m.%d)"
```

### Automatic Cleanup (ILM Policy)

Create Index Lifecycle Management policy:

```bash
curl -X PUT "http://localhost:9080/elasticsearch/_ilm/policy/mule-logs-policy" \
  -H 'Content-Type: application/json' -d '
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {}
      },
      "delete": {
        "min_age": "30d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'
```

## Performance Tuning

### ElasticSearch

```yaml
# Increase heap for production
ES_JAVA_OPTS=-Xms2g -Xmx2g

# Adjust shard count
index.number_of_shards: 1
index.number_of_replicas: 0
```

### Logstash

```yaml
# Increase heap
LS_JAVA_OPTS=-Xms512m -Xmx512m

# Worker threads
pipeline.workers: 2
pipeline.batch.size: 125
```

## Troubleshooting

### No Logs Appearing

1. Check Logstash connectivity:
```bash
nc -zv localhost 5000
```

2. Test direct send:
```bash
echo '{"message":"test"}' | nc localhost 5000
```

3. Check Logstash logs:
```bash
docker-compose logs logstash | grep ERROR
```

### ElasticSearch Disk Space

Check disk usage:
```bash
curl http://localhost:9080/elasticsearch/_cat/allocation?v
```

Free space:
```bash
# Delete old indices
curl -X DELETE "http://localhost:9080/elasticsearch/mule-logs-*" -d '
{
  "query": {
    "range": {
      "@timestamp": {
        "lt": "now-30d"
      }
    }
  }
}'
```

## Next Chapter

Continue to [Chapter 5: Mule Backend](05-mule-backend.md) for Mule application deployment and configuration.
