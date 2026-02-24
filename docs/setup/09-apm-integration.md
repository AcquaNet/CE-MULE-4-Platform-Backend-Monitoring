# Application Performance Monitoring (APM) with Jaeger

Complete guide for setting up and using Jaeger with the OpenTelemetry Mule 4 Agent to monitor Mule 4 applications in both Docker and CloudHub deployments.

> **Note**: This platform was migrated from Elastic APM to Jaeger with OpenTelemetry for open-source tracing and vendor-neutral instrumentation.

## Overview

Jaeger receives traces from Mule applications instrumented with the `otel-mule4-agent` (OpenTelemetry Mule 4 Agent) and stores them in OpenSearch for visualization.

**Version Compatibility:**
- Jaeger: 1.52.0
- OpenTelemetry Mule 4 Agent: 0.1.0 (uses OpenTelemetry SDK 1.32.0)
- OpenSearch: 2.11.1
- OpenSearch Dashboards: 2.11.1

## Architecture

```
Mule Application (with OTEL agent)
  ↓ OTLP gRPC to port 4317
Jaeger (172.42.0.13)
  ↓ Stores traces
OpenSearch (172.42.0.10:9200)
  ↓ Indexed in jaeger-* indices
Jaeger UI (http://localhost:16686/jaeger)
```

**Components:**
- **OpenTelemetry Mule 4 Agent**: Custom agent that instruments Mule flows and processors
- **Jaeger Collector**: Receives OTLP traces and writes to OpenSearch
- **Jaeger Query**: Serves the Jaeger UI and API
- **OpenSearch**: Stores trace data in `jaeger-span-*` and `jaeger-service-*` indices

---

## Jaeger Setup

Jaeger is already included in the OpenSearch stack `docker-compose.yml` and starts automatically.

### Configuration

Jaeger is configured via environment variables in `docker-compose.yml`:

```yaml
jaeger:
  image: jaegertracing/all-in-one:1.52
  environment:
    - SPAN_STORAGE_TYPE=opensearch
    - ES_SERVER_URLS=https://opensearch:9200
    - ES_TLS_SKIP_HOST_VERIFY=true
    - ES_USERNAME=admin
    - ES_PASSWORD=admin
    - COLLECTOR_OTLP_ENABLED=true
```

### Network Access

| Port | Protocol | Description |
|------|----------|-------------|
| 4317 | gRPC | OTLP trace receiver (recommended) |
| 4318 | HTTP | OTLP HTTP receiver |
| 16686 | HTTP | Jaeger UI |
| 14268 | HTTP | Jaeger HTTP collector (legacy) |
| 14250 | gRPC | Jaeger gRPC collector (legacy) |

**Access URLs:**
- **Jaeger UI**: http://localhost:16686/jaeger/ or http://localhost:9080/jaeger/
- **Internal (Docker)**: `http://jaeger:4317` (OTLP gRPC)
- **IP Address**: 172.42.0.13 (on ce-base-micronet)

### Viewing Traces

Access the Jaeger UI at: **http://localhost:16686/jaeger/**

1. Select a service (e.g., `ce-mule-base-worker-1`)
2. Set time range
3. Click "Find Traces"
4. Click on a trace to see span details

### Jaeger API

```bash
# List services
curl -s "http://localhost:16686/jaeger/api/services"

# Query traces for a service
curl -s "http://localhost:16686/jaeger/api/traces?service=ce-mule-base-worker-1&limit=10"

# Get specific trace
curl -s "http://localhost:16686/jaeger/api/traces/<traceID>"
```

---

## OpenTelemetry Mule 4 Agent

### Overview

The `otel-mule4-agent` is a custom OpenTelemetry agent that instruments Mule 4 applications, providing:

- Automatic span creation for Mule flows
- Span creation for each processor (Logger, Set Payload, HTTP Request, etc.)
- Correlation ID propagation
- Worker identification
- Environment and version tagging

### Source Location

`git/elastic-apm-mule4-agent/otel-mule4-agent/`

### Building the Agent

```bash
cd git/elastic-apm-mule4-agent/otel-mule4-agent
mvn clean package -DskipTests
# Output: target/otel-mule4-agent-0.1.0.jar
```

### Agent Components

| Class | Description |
|-------|-------------|
| `OtelStarter` | Initializes OpenTelemetry SDK |
| `OtelPipelineNotificationListener` | Creates spans for flow executions |
| `OtelMessageProcessorNotificationListener` | Creates spans for processors |
| `OtelExceptionNotificationListener` | Records exceptions |

### Configuration via tracer.xml

The agent is loaded via `tracer.xml` in the Mule application:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<mule xmlns="http://www.mulesoft.org/schema/mule/core"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.mulesoft.org/schema/mule/core
        http://www.mulesoft.org/schema/mule/core/current/mule.xsd">

    <object name="_otelStarter"
        class="io.opentelemetry.mule4.agent.OtelStarter" />
    <object name="_otelPipelineNotifications"
        class="io.opentelemetry.mule4.agent.OtelPipelineNotificationListener" />
    <object name="_otelMessageProcessorNotifications"
        class="io.opentelemetry.mule4.agent.OtelMessageProcessorNotificationListener" />
    <object name="_otelExceptionNotifications"
        class="io.opentelemetry.mule4.agent.OtelExceptionNotificationListener" />

    <notifications>
        <notification event="PIPELINE-MESSAGE" />
        <notification event="MESSAGE-PROCESSOR" />
        <notification event="EXCEPTION" />
        <notification-listener ref="_otelMessageProcessorNotifications" />
        <notification-listener ref="_otelPipelineNotifications" />
        <notification-listener ref="_otelExceptionNotifications" />
    </notifications>
</mule>
```

---

## Mule Application Configuration

### Prerequisites

1. **Agent JAR** must be in the app's `lib/` folder or repository
2. **tracer.xml** imported in the main flow
3. **Environment variables** configured for OTEL

### Docker Deployment

For Mule applications running in Docker (`git/CE-MULE-4-Platform-Backend-Docker`):

**Configure via environment variables in `docker-compose.yml`:**

```yaml
ce-base-mule-backend-1:
  environment:
    # OpenTelemetry Configuration
    OTEL_SERVICE_NAME: ce-mule-base-worker-1
    OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
    OTEL_EXPORTER_OTLP_PROTOCOL: grpc
    OTEL_TRACES_EXPORTER: otlp
    OTEL_METRICS_EXPORTER: none
    OTEL_LOGS_EXPORTER: none
    OTEL_RESOURCE_ATTRIBUTES: >-
      service.version=${MULEAPP_VERSION},
      deployment.environment=${mule_env},
      worker.id=worker-1
```

**Configuration Options:**

| Variable | Description | Example |
|----------|-------------|---------|
| `OTEL_SERVICE_NAME` | Service name in Jaeger | `ce-mule-base-worker-1` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Jaeger OTLP endpoint | `http://jaeger:4317` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Protocol (grpc or http/protobuf) | `grpc` |
| `OTEL_TRACES_EXPORTER` | Trace exporter type | `otlp` |
| `OTEL_METRICS_EXPORTER` | Metrics exporter (none to disable) | `none` |
| `OTEL_LOGS_EXPORTER` | Logs exporter (none to disable) | `none` |
| `OTEL_RESOURCE_ATTRIBUTES` | Additional resource attributes | `service.version=1.0.0` |

### Deploying the Agent JAR

The agent JAR must be available to the Mule classloader:

**Option 1: App lib folder (recommended)**
```bash
# Copy to running container
docker cp otel-mule4-agent-0.1.0.jar ce-base-mule-backend-1:/opt/mule/mule-standalone-4.4.0/apps/ce-mule-base-*/lib/
```

**Option 2: Maven dependency**
Add to `pom.xml`:
```xml
<dependency>
  <groupId>io.opentelemetry.mule4</groupId>
  <artifactId>otel-mule4-agent</artifactId>
  <version>0.1.0</version>
</dependency>
```

### CloudHub Deployment

For Mule applications deployed to CloudHub:

#### Architecture

```
CloudHub Mule App (with OTEL agent)
      ↓ (HTTPS OTLP)
APISIX Gateway (Public IP/Domain)
      ↓ (Internal Network)
Jaeger (172.42.0.13:4317)
      ↓
OpenSearch → Jaeger UI
```

#### Prerequisites

1. APISIX Gateway must be accessible from the internet
2. OTLP HTTP endpoint exposed (port 4318)
3. Jaeger running and connected to OpenSearch

#### Step 1: Expose OTLP HTTP Endpoint

Add route to APISIX for OTLP HTTP:

```yaml
- uri: /otlp/*
  name: otlp-collector
  upstream:
    nodes:
      "jaeger:4318": 1
    type: roundrobin
  plugins:
    cors:
      allow_origins: "*"
```

#### Step 2: Configure CloudHub Properties

```properties
# OTEL Configuration for CloudHub
OTEL_SERVICE_NAME=ce-mule-base-cloudhub
OTEL_EXPORTER_OTLP_ENDPOINT=https://your-domain.com:9443/otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_TRACES_EXPORTER=otlp
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=cloudhub
```

#### Step 3: Verify in Jaeger

1. Open: http://localhost:16686/jaeger/
2. Look for service: **ce-mule-base-cloudhub**
3. Verify traces are appearing

---

## Trace Data in OpenSearch

Jaeger stores traces in OpenSearch indices:

| Index Pattern | Description |
|---------------|-------------|
| `jaeger-span-YYYY-MM-DD` | Individual spans |
| `jaeger-service-YYYY-MM-DD` | Service metadata |

### Querying Traces in OpenSearch

```bash
# List Jaeger indices
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/_cat/indices?v" | grep jaeger

# Query recent spans
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/jaeger-span-*/_search?pretty" \
  -H 'Content-Type: application/json' -d '
{
  "size": 5,
  "sort": [{"startTimeMillis": "desc"}],
  "_source": ["operationName", "serviceName", "duration", "tags"]
}'
```

### Creating Index Pattern in OpenSearch Dashboards

1. Go to **Stack Management** → **Index Patterns**
2. Create pattern: `jaeger-span-*`
3. Time field: `startTimeMillis`

---

## Performance Tuning

### Sampling

Control how much trace data is collected:

```properties
# Development: Sample everything
OTEL_TRACES_SAMPLER=always_on

# Production: Sample 10%
OTEL_TRACES_SAMPLER=traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1

# Custom parent-based sampling
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1
```

### Batch Processing

Configure span batching:

```properties
# Max queue size
OTEL_BSP_MAX_QUEUE_SIZE=2048

# Max batch size
OTEL_BSP_MAX_EXPORT_BATCH_SIZE=512

# Export timeout
OTEL_BSP_EXPORT_TIMEOUT=30000

# Schedule delay
OTEL_BSP_SCHEDULE_DELAY=5000
```

---

## Troubleshooting

### Issue: No Traces in Jaeger

**Check 1: Verify Jaeger is running**
```bash
docker ps | grep jaeger
curl http://localhost:16686/jaeger/api/services
```

**Check 2: Verify OTEL configuration**
```bash
docker exec ce-base-mule-backend-1 env | grep OTEL
```

**Check 3: Check Mule logs for OTEL initialization**
```bash
docker logs ce-base-mule-backend-1 2>&1 | grep -i "otel\|opentelemetry"
```

**Check 4: Verify agent JAR is loaded**
```bash
docker exec ce-base-mule-backend-1 ls -la /opt/mule/mule-standalone-4.4.0/apps/ce-mule-base-*/lib/ | grep otel
```

**Check 5: Generate test traffic**
```bash
docker exec ce-base-mule-backend-1 curl -s http://localhost:8081/api/v1/status
```

### Issue: ClassNotFoundException

If you see `ClassNotFoundException: io.opentelemetry.mule4.agent.OtelStarter`:

1. Verify JAR is in app's `lib/` folder
2. Restart the Mule worker
3. Check container logs for classloader issues

### Issue: Connection Refused to Jaeger

**Check 1: Verify network connectivity**
```bash
docker exec ce-base-mule-backend-1 nc -zv jaeger 4317
```

**Check 2: Verify Jaeger OTLP is enabled**
```bash
docker logs jaeger 2>&1 | grep -i otlp
```

**Check 3: Check Jaeger collector health**
```bash
curl http://localhost:14269/health
```

### Issue: Traces Missing Spans

**Check 1: Verify notification listeners**
- Ensure `tracer.xml` has all notification listeners registered
- Check for XML syntax errors

**Check 2: Verify Mule app includes tracer.xml**
```xml
<import file="tracer.xml" doc:name="Import OTEL Tracer" />
```

---

## Migration from Elastic APM

If migrating from Elastic APM:

| Elastic APM | OpenTelemetry/Jaeger |
|-------------|---------------------|
| `elastic.apm.server_urls` | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| `elastic.apm.service_name` | `OTEL_SERVICE_NAME` |
| `elastic.apm.secret_token` | Not needed (internal network) |
| `elastic.apm.transaction_sample_rate` | `OTEL_TRACES_SAMPLER_ARG` |
| `elastic-apm-mule4-agent` | `otel-mule4-agent` |
| APM Server | Jaeger |
| Kibana APM UI | Jaeger UI |

**Key Benefits:**
- **Open Source**: No licensing concerns
- **Vendor Neutral**: OpenTelemetry is a CNCF standard
- **OpenSearch Integration**: Native Jaeger support
- **Simpler Setup**: No APM Server authentication needed

---

## Related Documentation

- [OpenSearch Stack Configuration](04-elk-stack.md) - OpenSearch setup
- [SECURITY_SETUP.md](../SECURITY_SETUP.md) - General security configuration
- [SSL_TLS_SETUP.md](../SSL_TLS_SETUP.md) - SSL/TLS setup for production
- [MONITORING_SETUP.md](../MONITORING_SETUP.md) - Prometheus and Grafana monitoring

---

**Last Updated**: 2026-01-20
