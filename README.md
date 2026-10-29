# CE Mule Platform

A self-hosted, CloudHub-style platform for Mule 4 CE apps, run with Docker Compose. It includes:

- **Apache APISIX** gateway (standalone mode): HTTPS, Keycloak token checks, rate limits, load balancing
- **Runtime Manager**: runtime pools (Mule version, Java, heap, workers), deployments from Maven or a jar
  upload, per-app properties and routes, an overview per app. Worker nodes on other servers are optional.
- **Logs**: Fluent Bit sends them to OpenSearch, and you view them in OpenSearch Dashboards. Document-Level
  Security keeps each tenant's logs separate.
- **Traces**: an OpenTelemetry Mule 4 agent sends them to Jaeger, which stores them in OpenSearch
- **JVM metrics**: the same agent pushes each worker's heap, GC, threads and CPU to Prometheus; Grafana dashboard "Mule JVM",
  and per app in the Runtime Manager's Overview (Workers table)
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
| `logging` | OpenSearch 2.19, OpenSearch Dashboards, Fluent Bit 5, log-archiver |
| `tracing` | Jaeger 2.22 (+ OpenSearch, log-archiver) |
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
| `/otlp/v1/metrics` | OTLP/HTTP metrics intake (Prometheus, monitoring profile) | same token |

Sign in once at `https://localhost:9443/` (realm `mule`, e.g. `admin` / `KEYCLOAK_REALM_ADMIN_PASSWORD`); tools the
user may not use are hidden, tools not running or not enabled (profile off) are greyed out and not clickable. Realm role `admin` opens every tool; other users get
the home page, Dashboards (their tenant only) and Keycloak "My account". Every tool page gets a "← Home" link (bottom left) back to
the home page, inserted by the gateway (global rule `home-link` in `config/apisix/apisix.yaml`). With `GATEWAY_AUTH=off`, `/jaeger`,
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

## Logs and traces from apps outside the platform

Apps run by the Runtime Manager need nothing: their workers already get `log-ingest:5000`, `LOG_INGEST_TOKEN` and
`jaeger:4317`. An app in Studio, a local runtime or CloudHub can't resolve those Docker names; give it system
properties (Studio: Run Configurations > Arguments > VM arguments; CloudHub: Properties tab):

```
-Dlogs.host=127.0.0.1 -Dlogs.port=9100 -Dlogs.token=<LOG_INGEST_TOKEN>
-Dotel.exporter.otlp.endpoint=http://127.0.0.1:9080/otlp -Dotel.exporter.otlp.protocol=http/protobuf
-Dotel.exporter.otlp.headers=x-otlp-token=<OTLP_INGEST_TOKEN>
```

`127.0.0.1` and `9080` only work on the platform's own PC; from elsewhere use the gateway's host, `9100` and
`https://<host>:9443/otlp` (the JVM must trust the certificate: [otel-mule4-agent/README.md](otel-mule4-agent/README.md)).
log4j's `${sys:logs.host}` reads **system properties**: putting `logs.host` in the app's `common.properties` does
nothing (log4j starts before Mule reads that file). Tokens come from the platform's `.env`; every install has its own.

Logs land in `mule-logs-YYYY.MM.DD`. Dashboards' index patterns `mule-logs-*` (the default in Discover), `logstash-*`
and `jaeger-span-*` are created in the Global tenant on every Dashboards start when missing
(`config/opensearch-dashboards/start.sh`; edited ones are kept): pick the **Global** tenant to see them.

## Retention

The `log-archiver` service keeps logs 365 days, or less when OpenSearch's disk passes 80%, and saves every deleted
log index to `volumes/log-archive/<index>.ndjson.gz` first (optionally to S3). Traces: 30 days. See
[docs/RETENTION_POLICY_GUIDE.md](docs/RETENTION_POLICY_GUIDE.md).

## Troubleshooting

Collect everything (container states, logs, the log pipeline, indices; no secrets) into one file:

```bash
bash scripts/diag.sh [out-file]     # default ./diag.txt; run it from the project, it finds the root itself
```

| Symptom | Cause / fix |
|---|---|
| Containers stuck in `Created`, half the stack down | `install.sh`/`docker compose up` was interrupted or hit an error: `docker compose up -d` again (it resumes; the error it prints names the service) |
| Home page `https://localhost:9443/` gives 500 | Keycloak isn't running (the home page signs in through it): see the line above, or `docker compose logs keycloak` |
| `/dashboards` sign-in gives 502, APISIX log `upstream sent too big header` | Dashboards' login cookies outgrow nginx's header buffer; `config/apisix/config/config.yaml` sets 32k buffers: `docker compose up -d --force-recreate apisix` |
| An edited config file isn't picked up | single files are bind-mounted: a copied/pulled file is a new file, so `docker compose up -d --force-recreate <service>` (restart isn't enough); `apisix.yaml` alone hot-reloads |
| A tool's link gives 503 | its profile is off or the container never started; the home page should grey it out |
| Index pattern gone in Dashboards | restart Dashboards (`docker compose restart opensearch-dashboards`) to recreate the standard ones; check the tenant (Global vs Private); `docker compose logs opensearch-dashboards \| grep "index pattern"` |
| Removing a profile from `COMPOSE_PROFILES` leaves its containers | Compose still knows them (not orphans): `docker compose rm -sf <service>` |
| Seed app fails: `HTTP Error 401: Unauthorized` | `ARTIFACTORY_USER` / `ARTIFACTORY_PASSWORD` in `.env`, then `docker compose up -d ce-base-runtime-manager` |
| Don't want Mule workers | `RM_DEFAULT_POOL_REPLICAS=0` before the first start, later the pool's replicas 0 (UI or `PUT /api/pools/default`) |
| No logs from an app, no error anywhere | wrong/missing `logs.token` (events are dropped silently) or wrong host/port: `diag.sh` shows connections on 9100, Fluent Bit's counters (input vs `drop_records`) and the indices |
| `docker exec ... /usr/...` in Git Bash: `C:/Program Files/Git/usr/...: no such file` | Git Bash rewrites paths: `export MSYS_NO_PATHCONV=1` |
| Studio: `Invalid multibyte sequence` at start | a pasted non-ASCII character (smart dash/quotes) in the VM arguments: retype them; else add `-Dfile.encoding=UTF-8` |
| Studio: `PKIX path building failed` / `Failed to export spans` / `ce.version` | see the agent's troubleshooting: [otel-mule4-agent/README.md](otel-mule4-agent/README.md#troubleshooting) |

## Documentation

All guides are indexed in [SETUP.md](SETUP.md); the full reference is [CLAUDE.md](CLAUDE.md).
