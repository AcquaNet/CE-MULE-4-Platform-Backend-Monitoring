# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Complete Mule 4 development platform with integrated logging, tracing, and API gateway:
- **Apache APISIX Gateway**: API gateway and load balancer (port 9080/9443)
- **OpenSearch Stack**: OpenSearch, Fluent Bit (log ingestion), OpenSearch Dashboards for centralized logging
- **Jaeger**: Distributed tracing with OpenSearch backend
- **OpenTelemetry Mule 4 Agent**: Custom tracing agent for Mule applications
- **Mule Application**: Mule 4.12 (CE, Java 17) backend with RESTful APIs
- **Docker Infrastructure**: Load-balanced Mule workers with supporting services
- **Multi-Tenancy**: Document-Level Security (DLS) for tenant isolation (FREE with OpenSearch)

## Repository Structure

```
Docker ElasticSearch/
├── docker-compose.yml              # Whole platform; include:s the Mule compose (one `up` starts all)
├── .env.example                    # Environment template
├── docs/                           # Detailed documentation
│   ├── setup/                      # Setup guides 01-09 (SETUP.md is the index)
│   ├── SECURITY_SETUP.md
│   ├── SSL_TLS_SETUP.md
│   ├── BACKUP_SETUP.md
│   ├── RETENTION_POLICY_GUIDE.md
│   ├── MONITORING_SETUP.md
│   ├── MULTITENANCY_SETUP.md       # Multi-tenant DLS guide
│   ├── ARTIFACTORY_DEPLOYMENT.md
│   └── DOCKER_IMAGES_EXPORT.md
├── certs/                          # git-ignored: ca/ (local CA) + apisix/ (gateway cert), made by APISIX start.sh
├── tests/                          # test suite: run.sh (unit, stack, api, ui, home), see TESTING.md
├── scripts/                        # diag.sh (troubleshooting dump), opensearch-start.sh (OpenSearch entrypoint: own cert, admin user),
│                                   # setup-opensearch.sh (templates + DLS roles), docker-images/ (offline export)
├── config/                         # All configuration
│   ├── apisix/                     # APISIX (standalone mode)
│   │   ├── apisix.yaml             # THE route source (routes, upstreams, plugin_configs)
│   │   ├── start.sh                # Entrypoint: renders apisix.yaml + certs, hot-reloads on change
│   │   └── config/config.yaml      # APISIX server config (listeners, plugins)
│   ├── fluent-bit/                 # Log ingestion: fluent-bit.conf + pipeline.lua (+ Dockerfile)
│   ├── jaeger/config.yaml          # Jaeger v2 (OTLP in, OpenSearch storage, /jaeger base path)
│   ├── keycloak/realms/            # realm mule (imported into an empty DB only)
│   ├── opensearch-dashboards/      # dashboards-on.yml (Keycloak) / dashboards-off.yml, picked by GATEWAY_AUTH
│   ├── prometheus/, alertmanager/, grafana/
│   └── scripts/                    # setup/, backup/, monitoring/, tenants/
├── mule/                           # Mule platform (included by docker-compose.yml)
│   ├── docker-compose.yml          # Runtime Manager, ActiveMQ, MySQL (workers are RM pools)
│   ├── docker_mulesoft/            # Mule runtime image build context (the RM builds ce-mule-runtime:<mule>-java<java>-<hash>)
│   ├── runtime-manager/            # CloudHub-style pools, deploys, properties, overview (app.py, pools.py)
│   ├── maven-settings.xml          # repos/credentials the Runtime Manager uses
│   └── volumes/                    # runtime data (git-ignored)
├── log-archiver/                   # retention + archiving service (UI /log-archiver/): rules, per-app, filters, disk/S3
├── node/                           # node agent for other servers (install-node.sh): pool capacity
├── otel-mule4-agent/               # OpenTelemetry Mule 4 agent source (Maven, 0.4.1)
├── git/                            # separate repo, only to BUILD the app (git-ignored)
│   └── CE-MULE-4-Platform-Backend-Mule/    # Mule 4 app source
└── CE-Platform/_sota/              # Offline installers
```

## Network Architecture

**Networks:**
- `ce-base-micronet` (172.42.0.0/16): Internal with static IPs
- `ce-base-network`: External connectivity

**IP Assignments:**

| Service | IP | Ports | Access |
|---------|-----|-------|--------|
| APISIX Gateway | 172.42.0.20 | 9080 (HTTP, 127.0.0.1 only), 9443 (HTTPS), 9091 (metrics, 127.0.0.1 only), 9100 (TCP stream, public), 9092 (Control API, inside the container only) | External entry point |
| Runtime Manager | 172.42.0.7 | 8080 (not published) | Via APISIX: `/runtime-manager/` |
| OpenSearch | 172.42.0.10 | 9200 | Via APISIX: `/opensearch` (port 9080 only, i.e. host loopback) |
| Fluent Bit (`log-ingest`) | 172.42.0.11 | 5000 (TCP/UDP), 2020 (health/metrics) | Via APISIX stream: TCP 9100 |
| OpenSearch Dashboards | 172.42.0.12 | 5601 | Via APISIX: `/dashboards` |
| Jaeger | 172.42.0.13 | 16686 (UI, API `/api/v3`), 4317/4318 (OTLP), 8888 (metrics), 13133 (health); none published | Via APISIX: `/jaeger` (SSO, realm role admin), intake `/otlp` |
| Keycloak | 172.42.0.27 | 8080, 9000 (health, management); not published | Via APISIX: `/auth` |
| Log archiver | dynamic | 8080 (not published) | Via APISIX: `/log-archiver/` (SSO, realm role admin) |
| Mule workers `mule-<pool>-<n>` | dynamic | 8081 | Via APISIX: `/api/*` (app `ce-mule-base`), per-app routes |
| MySQL | 172.42.0.3 | 3306 (127.0.0.1 only, `MYSQL_EXTERNAL_PORT`) | Direct |
| ActiveMQ | 172.42.0.5 | 8161, 61616, 5672 (all 127.0.0.1 only) | Via APISIX: `/activemq` |

**APISIX Routes:**
- `/dashboards` → OpenSearch Dashboards UI
- `/log-archiver/*` → log archiver UI/API (admin SSO; gateway adds `X-Gateway-Key`)
- `/opensearch/*` → OpenSearch API (9080 only: 404 on 9443, no password guessing from outside)
- `/auth/*` → Keycloak; the master realm (server admin) only on 9080 (404 on 9443; console http://localhost:9080/auth/admin/master/console/, the keycloak
  service sets its frontend URL to 9080, sslRequired none and brute-force protection at start); realm `mule` has brute-force protection
- `/alertmanager/*` → Alertmanager (alerting profile; admin SSO; it serves under /alertmanager itself)
- `/otlp/*` → Jaeger OTLP/HTTP intake (external apps e.g. CloudHub; key-auth header `x-otlp-token`); `/otlp/v1/metrics`
  (exact) → Prometheus OTLP intake, same token (JVM metrics of node workers / CloudHub)
- stream TCP 9100 → Fluent Bit :5000 (external log intake, e.g. CloudHub)
- `/jaeger/*` → Jaeger UI and API
- `/api/*` → workers of the default app `ce-mule-base` (`# BEGIN runtime-manager app ce-mule-base` block; round-robin, health checks on `/api/v1/status`; node list generated by the RM)
- `/<path>/*` → per-app routes set in the Runtime Manager (prefix stripped, app's pool workers)
- `/activemq/*` → ActiveMQ console (`/activemq/api/*`, i.e. Jolokia and REST, blocked by `uri-blocker`)
- global rule `home-link`: `<script src="/home-link.js">` inserted before `</body>` of tool pages (Runtime Manager, Dashboards,
  Jaeger, Prometheus, Grafana, Alertmanager, ActiveMQ, Keycloak admin/account; not sign-in pages, not `/`); page loads
  (`Accept: text/html`) go uncompressed so the body can be rewritten. The script (route `home-link-js`, mocking, public)
  adds the "← Home" link to `<html>`, not `<body>` (Dashboards empties `<body>` on start) and stops click handlers on it with
  a window capture listener (Grafana routes every link click itself). Same-origin script = allowed by the tools' CSP
  `'self'`; an inline link or script isn't. Checks: `config/apisix/test_home_link.py` (+ `.js` in node), browser `home_link()`
  in `tests/test_home_ui.py`.

## Common Commands

### Tests
```bash
tests/run.sh                            # every suite against the running stack (~30-40 min); `unit` = no stack needed
```
See TESTING.md (suites, coverage, test resources `t-*` and cleanup).

### Start/Stop Services
```bash
./install.sh                            # fresh clone or any time: .env (generated secrets) if missing, build, start, wait, print URLs
docker compose up -d --build           # Start everything (OpenSearch stack + Mule platform)
docker compose down                     # Stop all (the RM removes its Mule workers on stop)
docker compose --profile "*" down -v --remove-orphans   # Full reset incl. data (then rm -rf certs mule/volumes volumes for a fresh-clone state)
docker compose logs -f [service]        # View logs
```
Fresh-clone install is `./install.sh` and must stay zero-friction: APISIX's start.sh creates `certs/ca` + `certs/apisix`
(local CA, localhost/apisix cert) when missing; OpenSearch applies `scripts/setup-opensearch.sh` itself in the background
(idempotent, no setup container); every service has a healthcheck (`--wait`). No one-shot containers: nothing should sit
"Exited". `.gitattributes` pins LF for everything read inside containers (Windows clones use core.autocrlf=true).
One project, one command, one `.env`: the root compose `include:`s `mule/docker-compose.yml`
(with `env_file: .env`, so the Mule part reads the root `.env` too; there is no `mule/.env`).

**Profiles (lite installs):** apisix + the Runtime Manager (which runs the Mule workers) always run; everything else is a
profile picked by `COMPOSE_PROFILES` in the root `.env`: `db`, `mq`, `logging`, `tracing`,
`monitoring`, `alerting`, `opensearch-monitoring`, `auth`. Without `auth` (Keycloak) set
`GATEWAY_AUTH=off` (start.sh strips openid-connect and the token check after it; /api/* then has no auth).
With auth on, /api/* and per-app routes only accept Keycloak tokens issued to client `mule-api-gateway` (`azp`)
that carry its `api-access` client role; X-Tenant-ID is set from the token's `tenant_id` claim (users can't edit it).
Keycloak runs in production mode (`start`, `KC_CACHE=local`, public URL and issuer pinned by `KC_HOSTNAME`, internal callers
kept on keycloak:8080 by `KC_HOSTNAME_BACKCHANNEL_DYNAMIC`; `tenant_id` is declared in the realm user profile). `--profile x` on the CLI
replaces `COMPOSE_PROFILES`. New services must get a profile unless they're core, and a dependency
must share at least one profile with its dependents (`docker compose config` per combo catches it).
Compose creates the networks; never `docker network create` them by hand. Host paths are all
relative (`./volumes/...` inside the Mule folder); never put absolute paths in compose or `.env` (the one exception is
the Docker socket `/var/run/docker.sock` mounted into the Runtime Manager).

### Access Services (via APISIX)
**Single sign-on:** https://localhost:9443/ is the home page (links to every tool; a tool that is not running or whose profile
is off is greyed out and not clickable, one the user may not use is hidden); one Keycloak sign-in (realm `mule`)
covers all of them. Realm role `admin` = every tool; other users (`user`) = home, Dashboards (own tenant's logs only),
Keycloak "My account". How each tool signs in:
- Jaeger, Prometheus, ActiveMQ console: APISIX gateway SSO (client `gateway-sso`, plugin_configs `sso`/`sso-admin` in
  apisix.yaml; session cookie keyed by `GATEWAY_SESSION_SECRET`, holds only the ID token or it outgrows nginx's header
  limit; a serverless-pre-function drops client-sent `X-ID-Token`, the role check trusts it and needs `azp` gateway-sso or
  mule-api-gateway; responses get `X-Frame-Options: DENY`; a cross-site `/logout` is refused). The gateway signs in to the
  ActiveMQ console itself. Scripts use a bearer token of an admin user (below).
- Grafana: generic OAuth (client `grafana`), auto-login, realm role admin = Admin of the Grafana org (not server admin), others refused. Local break-glass user
  `GRAFANA_ADMIN_USER` (default `grafana-admin`: not `admin`, that login comes from Keycloak) at `/grafana/login?disableAutoLogin=true`.
- OpenSearch Dashboards: openid (client `dashboards`, `config/opensearch-dashboards/dashboards-on.yml`; https only); entrypoint
  `config/opensearch-dashboards/start.sh` creates index patterns `mule-logs-*` (default), `logstash-*`, `jaeger-span-*` in the
  Global tenant when missing (API as admin Basic, `securitytenant: global`; never overwrites);
  OpenSearch takes the ID token (openid domain first, basic second, written by setup-opensearch.sh): `roles` claim =
  backend roles, admin -> all_access, user -> `sso_tenant_logs` (DLS `${attr.jwt.tenant_id}`, Global tenant read-only)
  + kibana_user. Only tokens issued to client `dashboards` (`required_audience`).
- Runtime Manager and Keycloak admin console (`/auth/admin/mule/console/`, realm user admin has realm-admin): Keycloak.
`GATEWAY_AUTH=off`: start.sh points the SSO'd routes at `ops-basic` (user `ops` / `GATEWAY_OPS_PASSWORD`), Grafana
uses its local login, Dashboards mounts `dashboards-off.yml`, the home page is public. Sign out: `/logout`.
```bash
set -a; . ./.env; set +a                     # the examples below use .env variables
curl -k https://localhost:9443/dashboards/   # OpenSearch Dashboards (9200/16686 aren't published)
curl -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "http://localhost:9080/opensearch/_cluster/health?pretty"
# Mule API: token of client mule-api-gateway with role api-access (401 without, 403 with another client's)
TOKEN=$(curl -sk https://localhost:9443/auth/realms/mule/protocol/openid-connect/token -d grant_type=password \
  -d client_id=mule-api-gateway -d client_secret="$MULE_GATEWAY_CLIENT_SECRET" -d username=developer \
  -d password="$KEYCLOAK_REALM_DEV_PASSWORD" | sed 's/.*"access_token":"\([^"]*\)".*/\1/')
curl -k -H "Authorization: Bearer $TOKEN" https://localhost:9443/api/v1/status
# Jaeger/Prometheus from scripts: the same request with username=admin / KEYCLOAK_REALM_ADMIN_PASSWORD (realm role admin)
ADMIN_TOKEN=$(curl -sk https://localhost:9443/auth/realms/mule/protocol/openid-connect/token -d grant_type=password \
  -d client_id=mule-api-gateway -d client_secret="$MULE_GATEWAY_CLIENT_SECRET" -d username=admin \
  -d password="$KEYCLOAK_REALM_ADMIN_PASSWORD" | sed 's/.*"access_token":"\([^"]*\)".*/\1/')
curl -k -H "Authorization: Bearer $ADMIN_TOKEN" https://localhost:9443/jaeger/api/v3/services
```

### APISIX Routes
APISIX runs in **standalone mode**: `config/apisix/apisix.yaml` is the only route source.
There is no etcd, no Admin API and no APISIX Dashboard. Edit the file and save;
`config/apisix/start.sh` re-renders it inside the container within ~2s and APISIX hot-reloads.
```bash
docker run --rm --network container:apisix curlimages/curl:8.10.1 -s http://127.0.0.1:9092/v1/healthcheck   # Control API (container-local, shows secrets; no curl in the image; /v1/routes, /v1/upstreams also work: config/apisix/lua shadows the stock module, which 500s)
docker compose logs apisix | grep -i "error\|rendered"
```

### Mule Build/Deploy
```bash
cd "git/CE-MULE-4-Platform-Backend-Mule"
./01-build-and-deploy.sh    # Auto-increment, build, deploy to Artifactory
```

### Mule Docker Platform (runtime pools)
Workers are **runtime pools** run by the Runtime Manager, not compose services: a pool = Mule version, Java, heap,
JVM options, replicas; containers `mule-<pool>-<n>` (labels `rm.pool`, `rm.spec`) created through the Docker API
(socket mounted into the RM). The RM builds `ce-mule-runtime:<mule>-java<java>-<hash>` from `mule/docker_mulesoft`
(downloads Mule CE from MuleSoft's public repo, sha1-checked, eclipse-temurin base). Java must match
(4.4: 8/11, 4.5-4.8: 8/11/17, 4.9+: 17). Editing a pool replaces its workers one at a time and redeploys their apps.
The `default` pool is created on first start from `MULE_VERSION`/`MULE_JAVA_VERSION`/`RM_DEFAULT_POOL_*` (.env), then
edited in the UI/API. Workers get the RM's `WORKER_<NAME>` env as `<NAME>` + `MULE_ARGS` (heap/JVM options as `-M` args).
The RM removes its workers when it stops (so `docker compose down` can drop the networks) and recreates them on start:
restarting the RM restarts the workers. Runtime path is fixed: `/opt/mule/mule-standalone`. Heap defaults go in
`mule/docker_mulesoft/images/wrapper-platform.conf` (appended to the stock `wrapper.conf` at build); other JVM
flags are `-M<flag>` args in `entypoints/mule-start.sh`. Never use `conf/wrapper-additional.conf` (Mule regenerates
it on every start) or `wrapper.java.additional.N` lines (wrapper 3.2.x stops at the first index gap, stock indexes vary).

**Nodes (other servers):** `node/` = node agent only (`install-node.sh`; HTTPS :7443, bearer `NODE_TOKEN`, cert pinned by
SHA-256 fingerprint). It proxies an allowlist of Docker API calls, only for `mule-*` containers with `rm.pool` label and
`ce-mule-runtime:*` images (no binds/privileged/host network). Registered via `/api/nodes` (`data/nodes.json`, token
Fernet-encrypted); a pool spec `nodes: {"local": n, "<node>": m}` (or `replicas` = local only). Remote workers
`mule-<pool>-<node>-<n>` publish 8081-8090 on a 10-port block from 18000 (bridge network), send logs to
`<gateway>:9100` and traces to `https://<gateway>:9443/otlp`, trust the platform CA (`PLATFORM_CA_PEM`); the
gateway name must be in the cert: `GATEWAY_HOSTNAMES` in `.env`. A down node: 5 s timeout, skipped 30 s, its workers
left untouched, pool retried. Tests: `python node/agent/test_agent.py`. See `node/README.md`.
```bash
docker ps --filter label=rm.pool                 # pool workers
docker logs -f mule-default-1                    # a worker's console
docker exec mule-default-1 tail -f /opt/mule/mule-standalone/logs/mule.log
```

### OpenSearch Queries
```bash
# List indices
docker exec opensearch curl -s -k -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "https://localhost:9200/_cat/indices?v"

# Query Mule logs
docker exec opensearch curl -s -k -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "https://localhost:9200/mule-logs-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match": {"level": "ERROR"}}}'
```

### Jaeger Tracing
```bash
# List services
curl -sk -H "Authorization: Bearer $ADMIN_TOKEN" "https://localhost:9443/jaeger/api/v3/services"   # ADMIN_TOKEN: see Access Services

# Query traces
curl -sk -H "Authorization: Bearer $ADMIN_TOKEN" "https://localhost:9443/jaeger/api/v3/traces?query.service_name=ce-mule-base&query.start_time_min=$(date -u -d -1hour +%FT%TZ)&query.start_time_max=$(date -u +%FT%TZ)&query.num_traces=10"   # OTLP JSON; service = app name, resource attr worker.id = container
```

### Test log ingestion
```bash
# auth_token must be LOG_INGEST_TOKEN or the event is dropped; 9100 = APISIX stream proxy -> fluent-bit:5000
echo '{"auth_token":"<LOG_INGEST_TOKEN>","application":"test","log_type":"mule","level":"INFO","message":"Test","tenant_id":"acme-corp"}' | nc localhost 9100
```

## Mule Application

**Location:** `git/CE-MULE-4-Platform-Backend-Mule`

**Key Files:**
- `pom.xml`: Maven config (app.runtime 4.12.0, Java 17; `skipAST` because the plugin checks Java 25)
- `src/main/mule/`: Flow definitions
- `src/main/resources/api/ce-backend.raml`: API spec
- `src/main/resources/log4j2.xml`: Logging config with tenant_id support
- `01-build-and-deploy.sh`: Build script

**API Endpoint:** `GET /api/v1/status` - Health check

**Build Process:** Script reads version from `common.properties`, auto-increments, commits, builds, deploys to JFrog Artifactory.

## Runtime Manager (CloudHub-style deployments)

**Location:** `mule/runtime-manager` (`app.py` HTTP/apps/Maven/auth, `pools.py` Docker API; stdlib + `cryptography`)
**UI/API:** https://localhost:9443/runtime-manager/ through APISIX (routes `runtime-manager-root`/`runtime-manager` in
apisix.yaml: prefix stripped, 512 MB body limit via client-control, no gateway auth; no published port). All page URLs
are relative and server redirects follow the path of `RM_PUBLIC_URL`. The cert comes from a local CA: `curl --cacert certs/ca/ca.crt`
(Windows curl also `--ssl-no-revoke`; or `-k`). **API docs:** `/api/docs` (page) and `/api/openapi.json` (OpenAPI 3, public, servers relative) also linked
from API & settings; `test_app.py` fails if a route is undocumented or a documented one isn't routed. Browser sign-in is Keycloak (realm `mule`, client `runtime-manager`, needs realm role
`RM_OIDC_ROLE`, default `admin`; test user admin / `KEYCLOAK_REALM_ADMIN_PASSWORD`) while `GATEWAY_AUTH=on`; code flow + PKCE, the
browser goes to Keycloak via APISIX `https://localhost:9443/auth`, the code exchange goes straight to `keycloak:8080`.
Sessions are in memory (8 h; a restart signs everyone out). Basic `RM_USER`/`RM_PASSWORD` always works for scripts;
**API tokens** (`Authorization: Bearer rm_...`, created in UI "API & settings", SHA-256 stored, can't mint tokens) for pipelines.
New realm clients only appear after a realm re-import (Keycloak imports `config/keycloak/realms` on an empty DB).

- UI: **Applications** (per app: Overview, Properties, Logs (search over the last 2 MB: Mule-style words/"phrase"/OR/-word/
  `*`/`level:` `logger:` `thread:` `processor:` `event:`, or a JavaScript regex; priority filter), Settings; header has the Updates Auto/Notify/Off switch,
  Check, Update, Restart, Delete), **Runtime pools** (create/edit/delete, rollout progress, worker health),
  **API & settings** (tokens, update-check interval, pipeline curl examples). Overview data:
  `GET /api/apps/<app>/overview?minutes=` from Jaeger (root spans, newest 1500 per window; tracing profile) and
  OpenSearch `mule-logs-*` (logging profile), plus per worker heap used/limit, CPU, GC (`jvm`, Prometheus `RM_PROMETHEUS_URL`,
  monitoring profile; `app.JVM_QUERIES`, job = app name); a missing source greys out its panels/columns.
- Deploy = `PUT /api/apps/<app>`: JSON `{pool, workers, group, artifact, version, updates, properties,
  secureProperties, route}` (Maven) or a jar body (`Content-Type: application/java-archive`, `?pool=&workers=&path=&port=`).
  Only jar/source/pool/workers/properties changes redeploy; updates mode and route are just saved.
- **Workers per app** (`workers`): `all` (default), a count (least-loaded workers, then kept in `placed`; after a pool
  scale in/out the app is re-placed to keep the count) or a list of worker names (pinned; runs nowhere if they're gone).
  Placement, rolling updates, the app's route and `# BEGIN runtime-manager app <name>` node blocks use only those workers.
- **Properties** (CloudHub "properties"): written to `$MULE_HOME/.mule/<app>/deployment-properties/deployment.properties`
  before the jar, so Mule applies them on (re)deploy and they override the app's own. **Secure** ones are Fernet-
  encrypted at rest with `RM_SECRETS_KEY` (.env), write-only (API returns names only; `null` keeps a stored value).
  `PUT /api/apps/<app>/properties` replaces the sets and restarts the app (`?restart=0` to just save).
- Default app: `MULEAPP_GROUP_ID/ARTIFACT_ID/VERSION` (root `.env`) deployed as `<artifactId>` on the default pool at
  first start, redeployed when `MULEAPP_VERSION` changes. State: `seed` key in `/data/artifacts/<app>.json`.
- Maven uses `mule/maven-settings.xml` (active profiles' repos, `<servers>` credentials, mirrors, `${env.X}`), with
  `ATINA_REPOSITORY_URL` tried first. Version can be fixed, `RELEASE`, `LATEST` or `x-SNAPSHOT`.
- Updates per app: `auto` (deploy new builds/releases; default for SNAPSHOT/RELEASE/LATEST), `notify` (flag only;
  default for pinned), `off` (not checked; uploads are always off). Interval: UI setting (`/data/settings.json`,
  default `RM_MAVEN_POLL_SECONDS`/300 s; 0 = Check button only).
- Worker I/O through the Docker API only (archive upload + exec): jar copied as `.<app>.jar.part` then renamed;
  undeploy deletes `<app>.jar` + `<app>-anchor.txt`. Status: `STARTED` (anchor), `DEPLOYING` (jar), `FAILED` (dir, no anchor).
- APISIX: per-app routes in the `BEGIN runtime-manager` block (block YAML + a `# rm-route {json}` record line; APISIX's
  tinyyaml can't parse nested flow JSON), upstream = the app's pool workers, prefix stripped by proxy-rewrite,
  `plugin_config_id: mule-api-auth`. Any upstream's nodes may hold `# BEGIN runtime-manager pool <name>` ...
  `# END runtime-manager pool <name>`, rewritten with that pool's workers (`app <name>` = that app's workers; the `/api/*` upstream follows `app ce-mule-base`).
  Apps sharing a pool need distinct HTTP ports.

```bash
curl -H "Authorization: Bearer $RM_TOKEN" -X PUT -H "Content-Type: application/json" https://localhost:9443/runtime-manager/api/apps/orders-api \
  -d '{"pool":"default","group":"com.acqua","artifact":"orders-api","version":"1.4.2","properties":{"db.host":"mysql"},"secureProperties":{"db.password":"x"}}'
curl -H "Authorization: Bearer $RM_TOKEN" -X PUT -H "Content-Type: application/java-archive" --data-binary @app.jar \
  "https://localhost:9443/runtime-manager/api/apps/orders-api?pool=default&path=/orders&port=8091"
curl -u admin:$RM_PASSWORD -X PUT -H "Content-Type: application/json" https://localhost:9443/runtime-manager/api/pools/edge \
  -d '{"mule_version":"4.11.0","java_version":"17","heap_mb":1024,"replicas":2,"jvm_options":["-XX:+UseG1GC"]}'
curl -u admin:$RM_PASSWORD -X DELETE https://localhost:9443/runtime-manager/api/apps/orders-api
python mule/runtime-manager/test_app.py   # self-check
```

## OpenTelemetry Mule 4 Agent

**Location:** `otel-mule4-agent`

Custom OpenTelemetry agent that instruments Mule 4 applications for distributed tracing with Jaeger.

**Features:**
- Automatic span creation for Mule flows and processors
- Correlation ID propagation
- Worker identification
- Environment and version tagging

**Build:**
```bash
cd otel-mule4-agent
mvn clean install -DskipTests     # 0.4.1 into ~/.m2; the app depends on io.opentelemetry.mule4:otel-mule4-agent
```

**In the app:** Maven dependency + `src/main/resources/tracer.xml` (`<object>`s: `OtelStarter` with
`serviceName=${app.name}`, `serviceVersion=${ce.version}`, plus the three notification listeners). One SDK per app,
closed on undeploy (no leaked exporter threads). Cross-app traces: the app passes `#[java!io::opentelemetry::mule4::agent::TraceContext::headers(correlationId)]`
as `http:headers` (W3C traceparent of the `http:request` span in progress, else the root span); the called app's agent
extracts it, so its flow nests inside the call. Metrics/logs export default to `none` in the agent (`OtelStarter.DEFAULTS`,
lowest priority: OTEL_* env and otel.* system properties win). Requests with header `X-Untraced` aren't traced
(APISIX active health checks send it via `checks.active.req_headers`; the /api routes and plugin_config mule-api-auth clear a
client's own; `config/apisix/test_untraced.py`). Tests: `mvn -o test` (TraceContextTest, RuntimeMetricsTest, UntracedTest). Root spans carry `http.method/target/route/status_code` (status from
`vars.httpStatus`, else 500 on error / 200) and `tenant.id` (X-Tenant-ID); the Runtime Manager overview reads these.

**Environment Variables (Mule workers):** service name/version come from the app, not the worker:
```yaml
OTEL_RESOURCE_ATTRIBUTES: deployment.environment=local-docker,worker.id=mule-default-1   # worker.id = container
OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
OTEL_EXPORTER_OTLP_PROTOCOL: grpc
OTEL_TRACES_EXPORTER: otlp
OTEL_METRICS_EXPORTER: otlp                     # JVM metrics; none when no monitoring/alerting profile (pools.metrics_on)
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT: http://prometheus:9090/api/v1/otlp/v1/metrics
OTEL_EXPORTER_OTLP_METRICS_PROTOCOL: http/protobuf
OTEL_METRIC_EXPORT_INTERVAL: 15000
OTEL_LOGS_EXPORTER: none
```

## Log ingestion (Fluent Bit)

**Config:** `config/fluent-bit/` (built as `ce-fluent-bit`, <10 MB RAM; the image is distroless, a static busybox is
copied in only for the healthcheck). Service `fluent-bit`, network alias `log-ingest`, profile `logging`.

**Inputs:** JSON over TCP/UDP 5000 (no Beats). External: APISIX stream TCP 9100. Mule log4j appender "logs":
`${sys:logs.host:-log-ingest}`:`${sys:logs.port:-5000}`, token `${sys:logs.token:-${env:LOG_INGEST_TOKEN}}`.

**pipeline.lua:** drops events without `auth_token` = `LOG_INGEST_TOKEN` (then removes it); `tenant_id` cleaned
(`[A-Za-z0-9_-]`, lowercase, `unknown` if missing, original kept in `tenant_id_original`); event time from log4j
`instant`/`timeMillis`; `host` → `source_host`. A JSON object in `message` is merged first (parser filter).

**Index Routing:** Mule events (`log_type: mule` or an `application` field) → `mule-logs-YYYY.MM.DD`, others →
`logstash-YYYY.MM.DD` (name kept for the index templates, DLS roles and log-archiver).

**Mule Log Fields:** `tenant_id`, `application`, `environment`, `worker_id`, `level`, `loggerName`, `message`, `correlationId`, `@timestamp`

## Traces from outside (CloudHub)

Jaeger's OTLP ports aren't published. External apps send OTLP/HTTP to `https://<gateway>:9443/otlp/v1/traces` with
header `x-otlp-token: <OTLP_INGEST_TOKEN>` (APISIX key-auth consumer `otlp_ingest`; start.sh renders the key from the
env, a random one if unset). CloudHub sets, in its Properties tab (system properties): `logs.host/port/token` (logs via
9100) and `otel.exporter.otlp.endpoint=https://<gateway>:9443/otlp`, `otel.exporter.otlp.protocol=http/protobuf`,
`otel.exporter.otlp.headers=x-otlp-token=...` (see the app's `src/main/resources/config/cloudhub.properties.example`). Needs a cert CloudHub
trusts (Let's Encrypt) and its egress IPs allowed on 9443/9100.

## SSL/TLS

**Default:** SSL termination at APISIX gateway (port 9443). APISIX serves HTTPS whenever
`certs/apisix/apisix.crt` + `apisix.key` exist; `start.sh` injects them at render time (certs are
never stored in `apisix.yaml`) and picks up regenerated/renewed certs automatically.

**Certificates:** `start.sh` creates `certs/ca` (local CA, trust `certs/ca/ca.crt`) and `certs/apisix` (localhost, apisix,
127.0.0.1 + `GATEWAY_HOSTNAMES`) on first start and re-issues the gateway cert when a name is missing.
```bash
./config/scripts/setup/generate-certs.sh --domain mydomain.local   # add names to GATEWAY_HOSTNAMES, re-issue
./config/scripts/setup/generate-certs.sh --force [--new-ca]        # new gateway cert (and CA)
```
Server certs need `keyUsage = digitalSignature, keyEncipherment` (Chrome rejects RSA certs without
digitalSignature: `ERR_SSL_KEY_USAGE_INCOMPATIBLE`); the APISIX key is 644 because APISIX runs as non-root.

**Let's Encrypt:**
```bash
./config/scripts/setup/setup-letsencrypt.sh --domain yourdomain.com --email admin@yourdomain.com
```

For complete SSL setup, see [SSL_TLS_SETUP.md](docs/SSL_TLS_SETUP.md).

## Log Retention (log-archiver)

Service `log-archiver` (`log-archiver/`: `archiver.py` engine, `app.py` config + HTTP API + loop, `index.html` UI; image
`ce-log-archiver`, profiles logging, tracing) is the **only** thing that deletes logs/traces (no ISM; it deletes the old
`*-retention` ISM policies on start). UI at `/log-archiver/` (home card; sso-admin; the route sets `X-Gateway-Key` =
`LOG_ARCHIVER_TOKEN`, the service refuses requests without it, `/health` open). Config `/data/config.json` + state
(volume `log-archiver-data`); the `.env` LOGS_*/JAEGER_*/LOG_ARCHIVE_INTERVAL only seed the first start.
- Per pass, per log index (day) and per app (`application`; none = `(no application)`, global rules): older than the
  app's retention -> export the logs matching its archive filters to its destinations, then delete (whole index when
  every app is due, else `_delete_by_query` + expunge). Size caps: `logs.max_gb` (all logs), `apps.<app>.max_gb` (that app's
  share, estimated as its share of each index's logs x index size). Disk above `disk_max_percent`: oldest day first
  (archived), never today. Traces: delete after their days. Disk destinations trimmed to their days / GB, then all
  together to `archive.max_gb` / `archive.disk_max_percent` (the archive's own disk, not OpenSearch's).
- Archive filters: rules OR'ed, conditions inside a rule AND'ed (`level`, `message`, `tenant_id`, ... with is / is_not
  (comma list) / contains / starts_with); none = everything. Per app: retention, destinations, filters (null = global).
- Destinations: disk folder (under `./volumes/log-archive`, own retention + max GB) or S3 folder (connection + prefix);
  format raw `.ndjson` / gzip / zip; files `<folder>/<index>/<app>.<ext>`. S3 connections: bucket, region, endpoint
  (MinIO path-style), keys; secret Fernet-encrypted with `LOG_ARCHIVER_SECRETS_KEY`, write-only in the API; Test button.
- Usage tab / `GET api/usage`: both disks split (logs, traces, OpenSearch's own, other, free; archive files, other, free),
  per app and per day sizes, destinations (on disk now + sent so far, `state.json` `sent`), days until the limits.
- Safety: delete only after export count = matching count; per-destination done state, so a failed upload retries only
  what's missing. Self-check: `python log-archiver/test_archiver.py` (fake OpenSearch/S3).

```bash
docker compose logs -f log-archiver      # archived / deleted / cleaned lines
```

See [RETENTION_POLICY_GUIDE.md](docs/RETENTION_POLICY_GUIDE.md).

## Backup

```bash
./config/scripts/backup/configure-backup.sh   # register the snapshot repository (once)
./config/scripts/backup/backup.sh             # snapshot (BACKUP_INDICES, default today's indices)
./config/scripts/backup/restore.sh <snapshot> [pattern]   # closes matching indices, restores (never dot-indices)
./config/scripts/backup/backup-cleanup.sh [--dry-run]     # BACKUP_RETENTION_DAYS / BACKUP_MAX_COUNT
```
Snapshots (`fs`) live in `/usr/share/opensearch/data/snapshots` (`path.repo`), i.e. inside the `opensearch-data`
volume: they protect against deleted/corrupt indices, not against losing the volume (copy them off the host for that).

See [BACKUP_SETUP.md](docs/BACKUP_SETUP.md).

## Monitoring

```bash
./config/scripts/monitoring/check-health.sh [--watch]       # compose healthchecks, pool workers, cluster status
./config/scripts/monitoring/setup-monitoring.sh [--reload]  # render alertmanager.yml (alerting profile), restart Prometheus
```

**Mule JVM (live heap, GC, threads, CPU):** the agent (otel-mule4-agent) records JVM metrics; workers push them every
15 s over OTLP to Prometheus (`--web.enable-otlp-receiver`, `http://prometheus:9090/api/v1/otlp/v1/metrics`; node
workers and CloudHub via the gateway's `/otlp/v1/metrics`, same `x-otlp-token`). `job` = the app, labels `worker_id`,
`rm_pool`, `deployment_environment` (`otlp.promote_resource_attributes` in prometheus.yml). Grafana dashboard
**Mule JVM** (folder Platform; filters App = `job`, Worker): top row Shared workers / apps per worker / apps on them (a shared JVM
can't be split per app; one pool per app = CloudHub-style dedicated workers), then heap used/limit, non-heap, GC time, CPU, threads, classes per worker. Without the
`monitoring`/`alerting` profile in `COMPOSE_PROFILES` the Runtime Manager sets `OTEL_METRICS_EXPORTER=none` on workers.
Apps must be built with the agent that has it (rebuild after `mvn install` of otel-mule4-agent).

**Dashboards** (Keycloak single sign-on, realm role admin; see Access Services):
- Prometheus: https://localhost:9443/prometheus/
- Grafana: https://localhost:9443/grafana/
- Alertmanager: https://localhost:9443/alertmanager/ (alerting profile)
- Jaeger: https://localhost:9443/jaeger/

See [MONITORING_SETUP.md](docs/MONITORING_SETUP.md).

## Docker Images Export (Offline)

```bash
scripts/docker-images/export-images.sh [out.tar]   # internet: every compose image + ce-mule-runtime:* (pull/build first)
scripts/docker-images/import-images.sh [out.tar]   # offline server: docker load
NO_BUILD=1 ./install.sh                            # offline: use the loaded images, no rebuild
```

See [DOCKER_IMAGES_EXPORT.md](docs/DOCKER_IMAGES_EXPORT.md).

## Security

**Status:**
- ✅ OpenSearch Security enabled (auth required: admin / `OPENSEARCH_ADMIN_PASSWORD`, set on first start; OpenSearch 2.19)
- ✅ Document-Level Security (DLS) enabled for multi-tenancy (FREE)
- ✅ HTTPS on 9443 by default (local CA); plain HTTP 9080 only on 127.0.0.1

**Quick Setup:**
```bash
./install.sh   # fresh clone: .env with generated secrets, build, start, wait, print URLs
```

**Production Checklist:**
- Public certificate for 9443 (Let's Encrypt, see SSL_TLS_SETUP.md); keep 9080 loopback-only
- Keep `.env` secret (all passwords are generated there; no defaults)
- Rotate secrets by editing `.env` (OpenSearch admin password only applies on first start)
- Configure firewall rules

See [SECURITY_SETUP.md](docs/SECURITY_SETUP.md).

## Multi-Tenancy

**Status:** Document-Level Security (DLS) enabled for tenant isolation - **FREE with OpenSearch!**

Each tenant can only view logs containing their specific `tenant_id`. Tenants are extracted from:
1. `X-Tenant-ID` request header, which APISIX always sets itself from the verified token's `tenant_id` claim
   (a `serverless-post-function` after openid-connect on `/api*` and `mule-api-auth`; a client's own header is dropped,
   otherwise any caller could book its logs/traces to another tenant)
2. JWT `tenant_id` claim (from Keycloak)
3. Default "unknown"

**Setup Multi-Tenancy:** nothing to run: `scripts/setup-opensearch.sh` applies templates and DLS roles on every
OpenSearch start. No demo config: `scripts/opensearch-start.sh` (the entrypoint) makes a per-install node cert
(keytool, `data/.certs`) and `admin` (OPENSEARCH_ADMIN_PASSWORD) is the only user; there is no admin cert. Tenant users
only come from `manage-tenants.sh` (OpenSearch security API through `localhost:9080/opensearch`).

**Tenant Management:**
```bash
# Create tenant
./config/scripts/tenants/manage-tenants.sh create acme-corp

# Create tenant with OpenSearch user
./config/scripts/tenants/manage-tenants.sh create acme-corp --user acme_user --password SecurePass

# List tenants
./config/scripts/tenants/manage-tenants.sh list

# Verify tenant isolation
./config/scripts/tenants/manage-tenants.sh verify acme-corp

# Delete tenant
./config/scripts/tenants/manage-tenants.sh delete acme-corp
```

**Test with a tenant:** the tenant comes from the token (Keycloak user attribute `tenant_id`), not from a header:
```bash
curl -k -H "Authorization: Bearer $TOKEN" https://localhost:9443/api/v1/status
```

**Test DLS in OpenSearch:**
```bash
# Admin sees all documents
docker exec opensearch curl -s -k -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "https://localhost:9200/mule-logs-*/_search" | grep tenant_id

# Tenant user only sees their documents
docker exec opensearch curl -s -k -u acme_user:SecurePass "https://localhost:9200/mule-logs-*/_search" | grep tenant_id
```

See [MULTITENANCY_SETUP.md](docs/MULTITENANCY_SETUP.md).

## APM Data Locations

Trace data is stored in Jaeger indices within OpenSearch:

| Index Pattern | Description |
|---------------|-------------|
| `jaeger-span-*` | Trace spans (flow executions, processors) |
| `jaeger-service-*` | Service metadata |

**View APM Data:**
1. **Jaeger UI** (recommended): https://localhost:9443/jaeger/
   - Select service: the app name (e.g. `ce-mule-base`); tag `worker.id` = worker container
   - View traces with timing and span hierarchy

2. **OpenSearch Dashboards**: https://localhost:9443/dashboards/
   - Create index pattern: `jaeger-span-*` (time field: `startTimeMillis`)
   - Use Discover to search spans

## Configuration Reference

**Memory rules** (numbers per profile: docs/setup/01-quick-start.md; knobs: docs/setup/06-configuration.md):
- APISIX: `nginx_config.worker_processes: 2` (default = one ~36 MB worker per CPU core). config.yaml changes need
  `docker compose restart apisix` (only apisix.yaml hot-reloads).
- Mule pool workers: heap = pool `heap_mb` (default pool 1 GB) via `MULE_INIT_HEAP_MB`/`MULE_MAX_HEAP_MB` env ->
  `wrapper-platform.conf` `%VAR%`; start at 256 MB, `-XX:-AlwaysPreTouch`. Never `-M-Xms/-Xmx`: the wrapper appends its
  own initmemory/maxmemory after all -M args, so they always lose (verify with `jcmd <pid> VM.flags`, not the cmdline).
- Runtime image tag = `ce-mule-runtime:<mule>-java<java>-<hash of mule/docker_mulesoft>`: editing the build context
  builds a new image and rolls the workers; images no pool uses are pruned after each rollout.

**Environment Variables:**
- `MULEAPP_GROUP_ID`, `MULEAPP_ARTIFACT_ID`, `MULEAPP_VERSION`: Maven coordinates
- `ATINA_REPOSITORY_URL`: Artifactory URL
- `OPENSEARCH_ADMIN_PASSWORD`: OpenSearch admin password (generated into `.env`; no default)
- `LOG_INGEST_TOKEN`: token every log event must carry (Fluent Bit drops the rest)
- `OTLP_INGEST_TOKEN`: `x-otlp-token` for the `/otlp` trace intake

**Important Notes:**
1. OpenSearch and Mule share networks (`ce-base-micronet`, `ce-base-network`)
2. Mule sends logs to Fluent Bit via hostname `log-ingest:5000`
3. APISIX has no `depends_on`: upstreams resolve per request, so the gateway starts even if a backend is down
4. Jaeger uses OpenSearch as storage backend with OTLP protocol
5. OpenTelemetry Mule 4 Agent version: 0.4.1 (OpenTelemetry SDK 1.67.0, shaded; the installed pom lists no OTel deps)

