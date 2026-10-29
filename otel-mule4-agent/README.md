# OpenTelemetry Mule 4 Agent

Tracing agent for Mule 4 apps: sends traces to Jaeger (OpenSearch storage). Based on michaelhyatt/elastic-apm-mule4-agent (Apache 2.0).

## Features

- Automatic span creation for Mule flows
- Span creation for each processor (Logger, Set Payload, HTTP Request, etc.)
- Correlation ID propagation
- Worker identification
- Environment and version tagging
- OpenTelemetry SDK 1.67.0 (shaded into the agent jar; the installed pom lists no OpenTelemetry dependencies)
- One SDK per app (service name/version from the app), closed on undeploy

## Installation

#### Build from Source

```bash
cd otel-mule4-agent   # from the repo root
mvn clean install -DskipTests
# installs io.opentelemetry.mule4:otel-mule4-agent:0.3.0 into ~/.m2
```

#### Add to the Mule application

```xml
<dependency>
  <groupId>io.opentelemetry.mule4</groupId>
  <artifactId>otel-mule4-agent</artifactId>
  <version>0.3.0</version>
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
OTEL_METRICS_EXPORTER: none
OTEL_LOGS_EXPORTER: none
OTEL_RESOURCE_ATTRIBUTES: deployment.environment=local-docker,worker.id=mule-default-1
```

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
