# OpenTelemetry Mule 4 Agent

Tracing agent for Mule 4 apps: sends traces to Jaeger (OpenSearch storage). Based on michaelhyatt/elastic-apm-mule4-agent (Apache 2.0).

## Features

- Automatic span creation for Mule flows
- Span creation for each processor (Logger, Set Payload, HTTP Request, etc.)
- Correlation ID on every root span (attribute `correlationId`; search it in Jaeger's Tags field)
- Trace context across apps: incoming `traceparent` is honoured, outgoing calls carry it via `TraceContext.headers`
- Worker identification
- Environment and version tagging
- OpenTelemetry SDK 1.67.0 (shaded into the agent jar; the installed pom lists no OpenTelemetry dependencies)
- One SDK per app (service name/version from the app), closed on undeploy
- JVM metrics (heap, GC, threads, CPU, classes; OpenTelemetry runtime-telemetry 2.33), exported only where a
  metrics exporter is configured: the platform's workers push them to Prometheus (Grafana dashboard "Mule JVM")

## Installation

#### Build from Source

```bash
cd otel-mule4-agent   # from the repo root
mvn clean install -DskipTests
# installs io.opentelemetry.mule4:otel-mule4-agent:0.4.0 into ~/.m2
```

#### Add to the Mule application

```xml
<dependency>
  <groupId>io.opentelemetry.mule4</groupId>
  <artifactId>otel-mule4-agent</artifactId>
  <version>0.4.0</version>
</dependency>
```

## Configuration

#### 1. Add tracer.xml to your Mule app

Create `src/main/resources/tracer.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<mule xmlns="http://www.mulesoft.org/schema/mule/core"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.mulesoft.org/schema/mule/core
        http://www.mulesoft.org/schema/mule/core/current/mule.xsd">

    <object name="_otelStarter" class="io.opentelemetry.mule4.agent.OtelStarter">
        <property key="serviceName" value="${app.name}" />
        <property key="serviceVersion" value="${ce.version}" />
    </object>
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

#### 2. Import tracer.xml in your main flow

```xml
<import file="tracer.xml" doc:name="Import OTEL Tracer" />
```

#### 3. Configure environment variables

`service.name` / `service.version` come from `serviceName` / `serviceVersion` above (they override `OTEL_SERVICE_NAME`);
everything else is the standard `OTEL_*` environment. The platform's Runtime Manager sets these on every worker:

```yaml
OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
OTEL_EXPORTER_OTLP_PROTOCOL: grpc
OTEL_TRACES_EXPORTER: otlp
OTEL_METRICS_EXPORTER: otlp       # JVM metrics; none when the platform runs no Prometheus
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT: http://prometheus:9090/api/v1/otlp/v1/metrics
OTEL_EXPORTER_OTLP_METRICS_PROTOCOL: http/protobuf
OTEL_METRIC_EXPORT_INTERVAL: 15000
OTEL_LOGS_EXPORTER: none
OTEL_RESOURCE_ATTRIBUTES: deployment.environment=local-docker,worker.id=mule-default-1
```

#### Outside Docker (Studio, a local runtime, CloudHub)

`jaeger:4317` only resolves inside the platform's Docker network, and Jaeger's ports aren't published. Send
OTLP/HTTP to the gateway instead (system properties, e.g. Studio's VM arguments):

```
-Dotel.exporter.otlp.endpoint=http://127.0.0.1:9080/otlp        # same PC as the platform: plain HTTP, no certificate
-Dotel.exporter.otlp.protocol=http/protobuf
-Dotel.exporter.otlp.headers=x-otlp-token=<OTLP_INGEST_TOKEN from the platform's .env>
```

Metrics and logs export are off by default in the agent; an `otel.metrics.exporter` / `OTEL_METRICS_EXPORTER` you set
yourself wins. For JVM metrics from outside the platform add `-Dotel.metrics.exporter=otlp`: with the base endpoint
above they go to `/otlp/v1/metrics` (Prometheus, monitoring profile), same token.

From another machine use `https://<gateway>:9443/otlp`, and the JVM must trust the gateway certificate: a public one
(Let's Encrypt) or the platform CA imported into a copy of the JDK's `cacerts`:

```bash
cp "$JAVA_HOME/jre/lib/security/cacerts" platform-truststore.jks          # Java 8; Java 11+: $JAVA_HOME/lib/security/cacerts
keytool -importcert -noprompt -alias ce-platform-ca -file certs/ca/ca.crt -keystore platform-truststore.jks -storepass changeit
# VM arguments: -Djavax.net.ssl.trustStore=<path>/platform-truststore.jks -Djavax.net.ssl.trustStorePassword=changeit
```

A copy, not an empty store: `javax.net.ssl.trustStore` replaces the JDK's list for the whole JVM.

In `-Dotel.exporter.otlp.headers=x-otlp-token=...` the first `=` belongs to `-D`, the rest is the value
(`name=value` pairs, comma-separated for several headers).

#### 4. Traces across apps (optional)

To see app A -> app B -> app C as one trace, pass the trace context on each outgoing HTTP call. A notification
listener can't add headers to a request, so the app does it, in one expression:

```xml
<http:request method="GET" config-ref="App_B" path="/orders">
    <http:headers>#[java!io::opentelemetry::mule4::agent::TraceContext::headers(correlationId)]</http:headers>
</http:request>
```

With other headers: `#[{ 'x-foo': 'bar' } ++ java!io::opentelemetry::mule4::agent::TraceContext::headers(correlationId)]`.

`headers` returns `traceparent` (and `tracestate`) for the `http:request` span in progress, else the flow's root span;
an empty map when tracing is off, so the call works the same without it. The called app (with this agent) reads
`traceparent` and makes its flow a child of that span, so in Jaeger B's flow sits **inside** A's `http:request` span:
each span keeps its own start and end, nothing is counted twice; the parent's "self time" excludes its children.

Limits: one outgoing span per flow at a time, so parallel requests (scatter-gather) may nest under a sibling request
(still the same trace). Mule also sends `X-Correlation-ID` by default, so all apps of a chain share one
`correlationId`; in Dashboards, `jaeger-span-*` filtered on that tag shows every service of the chain.

## Viewing Traces

Traces are visible in:
- **Jaeger UI**: https://localhost:9443/jaeger/ (through APISIX; Jaeger's own ports are not published)
- **OpenSearch Dashboards**: Create index pattern `jaeger-span-*`

## Agent Components

| Class | Description |
|-------|-------------|
| `OtelStarter` | Initializes OpenTelemetry SDK via auto-configuration |
| `OtelPipelineNotificationListener` | Creates root spans for flow executions |
| `OtelMessageProcessorNotificationListener` | Creates child spans for processors |
| `OtelExceptionNotificationListener` | Records exceptions on spans |
| `TraceContext` | `headers(correlationId)`: W3C trace context for outgoing calls (step 4) |

## Tests

```bash
mvn -o test     # TraceContextTest: headers carry the request/root span, the receiving side joins the same trace,
                # metrics/logs export off by default; RuntimeMetricsTest: the JVM metrics the dashboard uses
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Configuration property ... ce.version` / `Couldn't find configuration property value` at deploy | `tracer.xml` uses `${ce.version}` (defined in ce-mule-base's `common.properties`): define it in your app or put a fixed `serviceVersion` |
| `PKIXPath building failed ... unable to find valid certification path` | the JVM doesn't trust the gateway certificate: truststore above, or `http://127.0.0.1:9080/otlp` on the same PC |
| `Failed to export N metrics` (404 from `/otlp`) | old agent (metrics on by default, posted to Jaeger): rebuild the app with the current agent; with metrics on, a 404/503 from `/otlp/v1/metrics` means the platform runs no Prometheus (monitoring profile) |
| App jar holds two agent versions (`repository/io/opentelemetry/mule4/otel-mule4-agent/0.3.0/` and `0.4.0/`) | `mvn package` without `clean` keeps the old one in `target/`: build with `mvn clean package` (`01-build-and-deploy.sh` does) |
| Jaeger's span scope shows an older agent version | the app was built against the old agent: bump the dependency version and rebuild (the stack test compares it to `otel-mule4-agent/pom.xml`) |
| `NoClassDefFoundError: io/opentelemetry/semconv/JvmAttributes` | an older `opentelemetry-semconv` won the dependency resolution: the agent pins 1.44.0 |
| No data in Grafana "Mule JVM" | app built with an older agent, monitoring profile off, or (outside the platform) no `-Dotel.metrics.exporter=otlp` |
| no traces, no error, from Studio | the endpoint still points at `jaeger:4317` (only inside Docker): set the properties above |
| `401` from `/otlp` | wrong or missing `x-otlp-token`; an empty `OTLP_INGEST_TOKEN` in `.env` means APISIX picked a random one: set it and `docker compose up -d apisix` |
| all-zero trace IDs (`00000000...`) | `otel.traces.exporter=none`: the SDK then creates no real spans |
| called app's flow is a separate trace | the caller doesn't send `TraceContext.headers(...)` (step 4), or the called app has no agent |

---

## Support for Mule Domains

Add the dependency to the domain `pom.xml` and declare as `sharedLibrary`:

```xml
<build>
  <plugins>
    <plugin>
      <groupId>org.mule.tools.maven</groupId>
      <artifactId>mule-maven-plugin</artifactId>
      <configuration>
        <sharedLibraries>
          <sharedLibrary>
            <groupId>io.opentelemetry.mule4</groupId>
            <artifactId>otel-mule4-agent</artifactId>
          </sharedLibrary>
        </sharedLibraries>
      </configuration>
    </plugin>
  </plugins>
</build>
```

Then import `tracer.xml` in each project that needs tracing.
