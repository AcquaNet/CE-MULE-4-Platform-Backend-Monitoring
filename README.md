# CE Mule Platform

A self-hosted, CloudHub-style platform for Mule 4 CE apps, run with Docker Compose. It includes:

- **Apache APISIX** gateway (standalone mode): HTTPS, Keycloak token checks, rate limits, load balancing
- **Runtime Manager**: runtime pools (Mule version, Java, heap, workers), deployments from Maven or a jar
  upload, per-app properties and routes, an overview per app. Worker nodes on other servers are optional.
- **Logs**: Fluent Bit sends them to OpenSearch, and you view them in OpenSearch Dashboards. Document-Level
  Security keeps each tenant's logs separate.
- **Traces**: an OpenTelemetry Mule 4 agent sends them to Jaeger, which stores them in OpenSearch
- **Optional**: Keycloak, MySQL, ActiveMQ, Prometheus/Grafana/Alertmanager

The detailed reference for every part is [CLAUDE.md](CLAUDE.md).

## Architecture

```
               public                          host only (127.0.0.1)
      9443 HTTPS       9100 TCP logs           9080 HTTP, 9091 metrics, MySQL, ActiveMQ
           |                |
+----------v----------------v---------------------------------------------+
| APISIX    routes: config/apisix/apisix.yaml    TLS: certs/apisix          |
+----+-----------+------------+-------------+--------------+-------------+--+
     | /api/*    | /runtime-  | /auth       | /dashboards  | /jaeger     | stream 9100
     | per-app   |  manager   |             | /opensearch  | /otlp       |
     v           v            v             v              v             v
+---------+ +---------+ +----------+ +------------+ +--------+ +------------+
| Mule    |<+ Runtime | | Keycloak | | Dashboards | | Jaeger | | Fluent Bit |
| workers | | Manager | | Postgres | +-----+------+ +---+----+ +-----+------+
+---------+ +---------+ +----------+       |            |            |
                                           v            v            v
                                     +------------------------------------+
                                     | OpenSearch                         |
                                     | mule-logs-*, logstash-*, jaeger-*  |
                                     +------------------------------------+
```

The Mule workers (`mule-<pool>-<n>`) are not compose services. The Runtime Manager creates them through the
Docker API as runtime pools, and APISIX's `/api/*` upstream follows the default app's workers. Workers send logs
to Fluent Bit (`log-ingest:5000`) and traces to Jaeger (`jaeger:4317`), and both store them in OpenSearch.

## Install

Requirements: Docker with Compose v2, about 5 GB of free RAM for the default profiles (measured at ~4.6 GB), and
internet access on the first run (images, Mule CE download).

```bash
./install.sh
```

On a fresh clone `install.sh` creates `.env` from `.env.example` with generated secrets
(`config/scripts/setup/generate-secrets.sh`). It then builds and starts everything, waits until it is healthy and
prints the URLs. It is safe to run again. Day to day:

```bash
docker compose up -d                                        # start
docker compose down                                         # stop (data kept)
docker compose --profile "*" down -v --remove-orphans       # full reset, deletes all data
```

There is one `.env` at the root, and every secret comes from it (no built-in defaults). The root compose file
`include:`s `mule/docker-compose.yml`. HTTPS on 9443 works out of the box: on its first start APISIX creates a
local CA (`certs/ca`) and a gateway certificate. To drop the browser warning, trust `certs/ca/ca.crt`, or use
`curl --cacert certs/ca/ca.crt`.

## Profiles

APISIX and the Runtime Manager (with its Mule workers) always run. Everything else is a profile, chosen with
`COMPOSE_PROFILES` in `.env`. The default is `db,mq,logging,tracing,monitoring,auth`.

| Profile | Services |
|---------|----------|
| `db` | MySQL |
| `mq` | ActiveMQ 5.19 |
| `logging` | OpenSearch 2.19, OpenSearch Dashboards, Fluent Bit 5 |
| `tracing` | Jaeger 2.22 (+ OpenSearch) |
| `monitoring` | Prometheus, Grafana |
| `alerting` | Alertmanager (+ Prometheus) |
| `opensearch-monitoring` | OpenSearch exporter (+ OpenSearch) |
| `auth` | Keycloak 26 (+ Postgres) |

Without `auth`, also set `GATEWAY_AUTH=off`. `/api/*` then has no authentication. See
[docs/setup/06-configuration.md](docs/setup/06-configuration.md).

## URLs and ports

All web UIs go through the gateway at `https://localhost:9443` (from other machines, `https://<host>:9443`).

| Path | What | Auth |
|------|------|------|
| `/` | Home page: links to every tool | Keycloak sign-in (realm `mule`), once for every tool; `/logout` signs out |
| `/runtime-manager/` | Runtime Manager UI/API | Keycloak sign-in (realm role `admin`); scripts: `RM_USER`/`RM_PASSWORD` or an API token |
| `/api/*`, per-app paths | Mule apps | Bearer token issued to client `mule-api-gateway` with client role `api-access` |
| `/dashboards/` | OpenSearch Dashboards | Keycloak sign-in: realm role `admin` sees all logs, other users only their tenant's |
| `/opensearch/` | OpenSearch REST API, on `http://localhost:9080` only (404 on 9443) | `admin` / `OPENSEARCH_ADMIN_PASSWORD`, or a tenant user |
| `/jaeger/` | Jaeger UI/API | Keycloak sign-in, realm role `admin`; scripts: bearer token of an admin user |
| `/prometheus/` | Prometheus | same as Jaeger |
| `/grafana/` | Grafana | Keycloak sign-in, realm role `admin`; local `GRAFANA_ADMIN_USER` at `/grafana/login?disableAutoLogin=true` |
| `/auth/realms/master` | Keycloak server admin (master realm): 9080 only (404 on 9443); console http://localhost:9080/auth/admin/master/console/ | `KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD` |
| `/auth/admin/mule/console/` | Keycloak admin console of realm `mule` | realm user `admin` |
| `/activemq/` | ActiveMQ console (`/activemq/api/*` blocked) | same as Jaeger (the gateway signs in to the console) |
| `/otlp/v1/traces` | OTLP/HTTP trace intake | header `x-otlp-token: OTLP_INGEST_TOKEN` |

Sign in once at `https://localhost:9443/` (realm `mule`, e.g. `admin` / `KEYCLOAK_REALM_ADMIN_PASSWORD`); tools the
user may not use are hidden, tools not running or not enabled (profile off) are greyed out and not clickable. Realm role `admin` opens every tool; other users get
the home page, Dashboards (their tenant only) and Keycloak "My account". With `GATEWAY_AUTH=off`, `/jaeger`,
`/prometheus` and `/activemq` use basic auth `ops` / `GATEWAY_OPS_PASSWORD`.

| Port | Bound to | What |
|------|----------|------|
| 9443 | all interfaces | HTTPS gateway |
| 9100 | all interfaces | log intake (JSON over TCP to Fluent Bit; events need `auth_token` = `LOG_INGEST_TOKEN`) |
| 9080 | 127.0.0.1 | HTTP gateway (same routes, plus `/opensearch` and the Keycloak master realm) |
| 9091 | 127.0.0.1 | APISIX Prometheus metrics |
| 3306 | 127.0.0.1 | MySQL |
| 8161, 5672, 61616 | 127.0.0.1 | ActiveMQ console, AMQP, OpenWire (user `admin` / `ACTIVEMQ_ADMIN_PASSWORD`) |

OpenSearch (9200), Jaeger (16686, 4317/4318), Keycloak, the Runtime Manager and APISIX's Control API (9092) are
not published.

## Documentation

All guides are indexed in [SETUP.md](SETUP.md); the full reference is [CLAUDE.md](CLAUDE.md).
