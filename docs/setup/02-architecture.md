# Architecture

## Overview

```
 clients / CloudHub / worker nodes
        | 9443 HTTPS                     | 9100 TCP (log events)
+-------v--------------------------------v-------------------------+
| APISIX 172.42.0.20 (standalone: config/apisix/apisix.yaml)        |
+--+---------------+--------------+-------------+----------------+--+
   | /api/*        | /runtime-    | /auth       | /dashboards    | stream
   | per-app routes|  manager     |             | /opensearch    |
   |               |              |             | /jaeger /otlp  |
   v               v              v             v                v
 mule-<pool>-<n> <-- Runtime    Keycloak     Dashboards,       Fluent Bit
 (pool workers)     Manager     (+Postgres)  OpenSearch,       (log-ingest)
   |                (Docker API)             Jaeger                |
   | logs: log-ingest:5000 ----------------------------------------+
   | traces: jaeger:4317 --> Jaeger --+                            |
   |                                  v                            v
   |                           OpenSearch: jaeger-span-*,  mule-logs-*, logstash-*
   +--> MySQL, ActiveMQ (optional)
```

## Components

| Component | Container | IP (ce-base-micronet) | Notes |
|-----------|-----------|-----------------------|-------|
| APISIX | `apisix` | 172.42.0.20 | only entry point; see [03](03-apisix-gateway.md) |
| Runtime Manager | `ce-base-runtime-manager` | 172.42.0.7 | runs the pool workers via the Docker socket; UI/API at `/runtime-manager/` |
| Mule workers | `mule-<pool>-<n>` | dynamic | port 8081; heap = pool `heap_mb` (default pool 1024 MB) |
| OpenSearch | `opensearch` | 172.42.0.10 | 9200, not published; heap `OPENSEARCH_JAVA_OPTS` (default 512 MB) |
| Fluent Bit | `fluent-bit` (alias `log-ingest`) | 172.42.0.11 | 5000 TCP/UDP, 2020 health/metrics |
| OpenSearch Dashboards | `opensearch-dashboards` | 172.42.0.12 | `/dashboards` |
| Jaeger | `jaeger` | 172.42.0.13 | UI 16686, OTLP 4317/4318; stores in OpenSearch |
| Prometheus / Grafana / Alertmanager | `prometheus`, `grafana`, `alertmanager` | .23 / .24 / .25 | all three behind admin SSO (`/prometheus`, `/grafana`, `/alertmanager`) |
| OpenSearch exporter | `opensearch-exporter` | 172.42.0.26 | profile `opensearch-monitoring` |
| Keycloak / Postgres | `keycloak`, `keycloak-db` | .27 / .28 | Keycloak 26, production mode (`start`), realm `mule` |
| MySQL | `ce-base-db-backend` | 172.42.0.3 | 127.0.0.1:3306 |
| ActiveMQ | `ce-base-apachemq-backend` | 172.42.0.5 | 127.0.0.1: 8161 console, 5672 AMQP, 61616 OpenWire |

Compose creates both networks: `ce-base-micronet` (172.42.0.0/16, static IPs) and `ce-base-network`. For the
services in each profile, see the [README](../../README.md#profiles).

## Flows

**API request:** client → `https://<host>:9443/api/...` → APISIX checks the Keycloak token (`openid-connect`, then a
check that the token was issued to `mule-api-gateway` and carries the `api-access` role), sets `X-Tenant-ID` from
the token's `tenant_id` claim, applies the per-IP rate limit, and sends the request round-robin to a healthy worker.
Workers are health-checked on `/api/v1/status`. Per-app routes (`/<path>/*`) follow the same rules through the
plugin config `mule-api-auth`.

**Logs:** the log4j Socket appender sends JSON to `log-ingest:5000`. External senders (CloudHub, worker nodes) use
`<gateway>:9100`. Fluent Bit drops events without `auth_token` = `LOG_INGEST_TOKEN`, normalizes `tenant_id` and
writes to `mule-logs-YYYY.MM.DD` or `logstash-YYYY.MM.DD`. See [08](08-logging-integration.md).

**Traces:** the OpenTelemetry Mule 4 agent sends OTLP/gRPC to `jaeger:4317`. External senders use
`https://<gateway>:9443/otlp` with `x-otlp-token`. Jaeger writes to OpenSearch. See [09](09-apm-integration.md).

**Deployments:** the Runtime Manager fetches apps from Maven (or takes a jar upload) and copies them into the
workers through the Docker API. It rewrites the generated blocks in `config/apisix/apisix.yaml`, which APISIX
hot-reloads. See [05](05-mule-backend.md) and [mule/README.md](../../mule/README.md).

## Security model (short)

- Public: 9443 (HTTPS gateway) and 9100 (log intake, token-checked). Host only: 9080, 9091, MySQL, ActiveMQ.
  Everything else is unpublished. `/opensearch` and the Keycloak master realm answer on 9080 only (404 on 9443).
- `/api/*` and per-app routes need a `mule-api-gateway` token with `api-access`.
- One Keycloak sign-in (home page https://localhost:9443/) covers every UI: realm role `admin` gets all of them; other
  users get Dashboards with only their tenant's logs (DLS on the token's `tenant_id`). The OpenSearch API also takes
  its own users (`admin`, tenant users of manage-tenants.sh). With `GATEWAY_AUTH=off`, `/jaeger`, `/prometheus`,
  `/activemq` use basic auth `ops`.
- All secrets come from the root `.env`.

Details: [SECURITY_SETUP.md](../SECURITY_SETUP.md).

## Scaling

- **Mule:** change the pool's worker count or heap in the Runtime Manager. To add capacity on other servers, use
  worker nodes ([node/README.md](../../node/README.md)).
- **OpenSearch:** raise `OPENSEARCH_JAVA_OPTS` (2 GB or more for production). It runs as a single node.
- **APISIX / Fluent Bit:** single instances. A second Fluent Bit would be added as another node of the 9100
  stream route.
