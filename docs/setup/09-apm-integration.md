# Tracing (OpenTelemetry Mule 4 agent + Jaeger)

Mule apps are traced by the custom OpenTelemetry Mule 4 agent. It sends spans to Jaeger v2 (2.22, config
`config/jaeger/config.yaml`), which stores
them in OpenSearch (`jaeger-span-*`, `jaeger-service-*`). Tracing needs the `tracing` profile, which also
starts OpenSearch.

```
Mule app (otel-mule4-agent)
  | docker workers: OTLP/gRPC jaeger:4317 (inside the network)
  | CloudHub / nodes: OTLP/HTTP https://<gateway>:9443/otlp  (header x-otlp-token)
  v
Jaeger --> OpenSearch
  ^
  UI/API: https://localhost:9443/jaeger/  (Keycloak sign-in, realm role admin)
```

Jaeger's ports (16686, 4317, 4318) are not published.

## The agent

Source: `otel-mule4-agent`. Version 0.4.1 (OpenTelemetry SDK 1.67.0).

```bash
cd otel-mule4-agent
mvn clean install -DskipTests          # installs io.opentelemetry.mule4:otel-mule4-agent:0.4.1 into ~/.m2
```

The app needs two things. First, the Maven dependency in `pom.xml`:

```xml
<dependency>
    <groupId>io.opentelemetry.mule4</groupId>
    <artifactId>otel-mule4-agent</artifactId>
    <version>0.3.0</version>
</dependency>
```

Second, `src/main/resources/tracer.xml`, which defines `OtelStarter` and the three notification listeners:

```xml
<object name="_otelStarter" class="io.opentelemetry.mule4.agent.OtelStarter">
    <property key="serviceName" value="${app.name}" />
    <property key="serviceVersion" value="${ce.version}" />
</object>
<object name="_otelPipelineNotifications" class="io.opentelemetry.mule4.agent.OtelPipelineNotificationListener" />
<object name="_otelMessageProcessorNotifications" class="io.opentelemetry.mule4.agent.OtelMessageProcessorNotificationListener" />
<object name="_otelExceptionNotifications" class="io.opentelemetry.mule4.agent.OtelExceptionNotificationListener" />
<notifications>
    <notification event="PIPELINE-MESSAGE" />
    <notification event="MESSAGE-PROCESSOR" />
    <notification event="EXCEPTION" />
    <notification-listener ref="_otelMessageProcessorNotifications" />
    <notification-listener ref="_otelPipelineNotifications" />
    <notification-listener ref="_otelExceptionNotifications" />
</notifications>
```

What you get:
- A span per flow and per processor, with correlation ID propagation.
- The service name is the app name, so apps that share a worker appear as separate services. The worker is in
  the `worker.id` resource attribute.
- Root spans carry `http.method`, `http.target`, `http.route`, `http.status_code` (taken from `vars.httpStatus`;
  otherwise 500 on error and 200 on success) and `tenant.id` (from `X-Tenant-ID`, which APISIX sets from the token).
  The Runtime Manager's app overview reads these.
- One SDK per app, closed on undeploy.

See the Mule app (`git/CE-MULE-4-Platform-Backend-Mule`) for a working example.

## Workers on the platform

You don't configure anything per app. The Runtime Manager passes these to every pool worker (`WORKER_<NAME>` in
`mule/docker-compose.yml`) and adds `worker.id=<container>,rm.pool=<pool>`:

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=${mule_env}
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=none
OTEL_LOGS_EXPORTER=none
```

Workers on other servers (nodes) send to `https://<gateway>:9443/otlp` with `OTLP_INGEST_TOKEN` and trust the
platform CA ([node/README.md](../../node/README.md)).

## CloudHub

Set these in CloudHub's application Properties (they become system properties; from
`src/main/resources/config/cloudhub.properties.example` in the Mule app):

```properties
otel.exporter.otlp.endpoint=https://<gateway>:9443/otlp
otel.exporter.otlp.protocol=http/protobuf
otel.exporter.otlp.headers=x-otlp-token=<OTLP_INGEST_TOKEN>
otel.traces.exporter=otlp
otel.metrics.exporter=none
otel.logs.exporter=none
otel.resource.attributes=deployment.environment=cloudhub,worker.id=cloudhub
otel.traces.sampler=parentbased_traceidratio
# 10% of requests; 1.0 = all
otel.traces.sampler.arg=0.1
```

You also need a gateway certificate that CloudHub trusts (e.g. Let's Encrypt, see
[SSL_TLS_SETUP.md](../SSL_TLS_SETUP.md)), and CloudHub's egress IPs allowed on 9443. The logs side is in
[08-logging-integration.md](08-logging-integration.md#cloudhub-deployment).

## Viewing traces

Open `https://localhost:9443/jaeger/` (Keycloak sign-in, realm role `admin`) and pick a service, e.g. `ce-mule-base`.
The API takes a bearer token of an admin user:

```bash
set -a; . ./.env; set +a
TOKEN=$(curl -sk https://localhost:9443/auth/realms/mule/protocol/openid-connect/token -d grant_type=password \
  -d client_id=mule-api-gateway -d client_secret="$MULE_GATEWAY_CLIENT_SECRET" -d username=admin \
  -d password="$KEYCLOAK_REALM_ADMIN_PASSWORD" | sed 's/.*"access_token":"\([^"]*\)".*/\1/')
curl -sk -H "Authorization: Bearer $TOKEN" https://localhost:9443/jaeger/api/v3/services
curl -sk -H "Authorization: Bearer $TOKEN" "https://localhost:9443/jaeger/api/v3/traces?query.service_name=ce-mule-base&query.start_time_min=$(date -u -d -1hour +%FT%TZ)&query.start_time_max=$(date -u +%FT%TZ)&query.num_traces=10"
```

You can also look at spans in OpenSearch Dashboards: create an index pattern `jaeger-span-*` with time field
`startTimeMillis`.

## Problems

| Symptom | Check |
|---------|-------|
| No service in Jaeger | Is the `tracing` profile on? Run `docker compose ps jaeger`. Is the app built with the dependency and `tracer.xml`? |
| `ClassNotFoundException` for `io.opentelemetry.mule4...` | The agent isn't installed in `~/.m2` when the app was built (`mvn clean install` above) |
| External traces rejected (401) | `x-otlp-token` must equal `OTLP_INGEST_TOKEN` |
| External traces fail TLS | The client doesn't trust the gateway certificate (the local CA, or a missing `GATEWAY_HOSTNAMES` entry) |
