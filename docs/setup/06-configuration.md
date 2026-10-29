# Configuration

All settings live in one file: the root `.env`. `install.sh` creates it from `.env.example` with
`config/scripts/setup/generate-secrets.sh`. Every variable is described in [.env.example](../../.env.example), and
all secrets come from `.env` (compose has no default passwords). After editing `.env`, run `docker compose up -d`;
compose recreates the services whose environment changed.

## Profiles

`COMPOSE_PROFILES` in `.env` picks the optional parts; the profile table is in the
[README](../../README.md#profiles).

- `--profile x` on the command line **replaces** `COMPOSE_PROFILES`; it does not add to it. `--profile "*"`
  selects every profile.
- `docker compose build` only builds the active profiles; `scripts/docker-images/export-images.sh` exports all of them.
- When you add a service, give it a profile unless it is core. A dependency must share at least one profile
  with its dependents. Check every combination with `docker compose --profile <p> config -q`.

## GATEWAY_AUTH

| Value | Effect |
|-------|--------|
| `on` (default) | `/api/*` and per-app routes need a Keycloak token (needs the `auth` profile); the Runtime Manager uses Keycloak sign-in |
| `off` | `start.sh` strips `openid-connect` and the token check: **`/api/*` has no authentication**. The Runtime Manager uses Basic `RM_USER`/`RM_PASSWORD` |

Use `off` only for lite installs without `auth`. With `on` and no Keycloak, every `/api/*` call fails.

## Frequently changed variables

| Variable | Purpose |
|----------|---------|
| `MULE_VERSION`, `MULE_JAVA_VERSION` | default pool runtime (applied when the pool is first created; afterwards edit the pool) |
| `RM_DEFAULT_POOL_HEAP_MB`, `RM_DEFAULT_POOL_REPLICAS` | default pool heap (1024) and workers (2), first creation only (not in `.env.example`; add them to override) |
| `MULEAPP_GROUP_ID`, `MULEAPP_ARTIFACT_ID`, `MULEAPP_VERSION` | default app; changing the version redeploys it |
| `ATINA_REPOSITORY_URL`, `ARTIFACTORY_USER`, `ARTIFACTORY_PASSWORD` | Maven repository used by the Runtime Manager ([ARTIFACTORY_DEPLOYMENT.md](../ARTIFACTORY_DEPLOYMENT.md)) |
| `GATEWAY_HOSTNAMES` | extra names/IPs in the generated gateway certificate ([SSL_TLS_SETUP.md](../SSL_TLS_SETUP.md)) |
| `OPENSEARCH_JAVA_OPTS` | OpenSearch heap |
| `mule_env` | environment name given to the workers (`deployment.environment`, log field `environment`) |

Secrets and how to rotate them: [SECURITY_SETUP.md](../SECURITY_SETUP.md).

## Memory

Measured numbers per profile: [01-quick-start.md](01-quick-start.md#memory). These settings change them:

| Setting | Where | Default |
|---------|-------|---------|
| Mule worker heap | pool `heap_mb` in the Runtime Manager (env `MULE_INIT_HEAP_MB`/`MULE_MAX_HEAP_MB` -> `wrapper-platform.conf`) | default pool 1024 MB; start 256 MB |
| Workers per pool | pool `replicas` / `nodes` | 2 |
| OpenSearch heap | `OPENSEARCH_JAVA_OPTS` | 512 MB (production: 2 GB or more) |
| APISIX workers | `nginx_config.worker_processes` in `config/apisix/config/config.yaml` (needs `docker compose restart apisix`) | 2 |
| MySQL | `--performance-schema=OFF --innodb-buffer-pool-size=64M` in `mule/docker-compose.yml` | |

Don't set `-M-Xms`/`-M-Xmx` in a pool's JVM options: the Mule wrapper appends its own heap flags after them, so
they never take effect. Use `heap_mb`. Other JVM flags go into the pool's `jvm_options`.

## Other configuration files

| File | What |
|------|------|
| `config/apisix/apisix.yaml` | gateway routes ([03](03-apisix-gateway.md)) |
| `config/fluent-bit/` | log pipeline ([04](04-opensearch.md#fluent-bit)) |
| `config/jaeger/config.yaml` | Jaeger v2: OTLP receivers, OpenSearch storage, UI base path ([09](09-apm-integration.md)) |
| `config/opensearch-dashboards/dashboards-{on,off}.yml` | Dashboards sign-in (Keycloak or OpenSearch users), picked by `GATEWAY_AUTH` |
| `config/keycloak/realms/mule-realm.json` | realm `mule`, imported only into an empty Keycloak database |
| `config/prometheus/`, `config/grafana/`, `config/alertmanager/` | monitoring ([MONITORING_SETUP.md](../MONITORING_SETUP.md)) |
| `mule/maven-settings.xml` | Maven repos and credentials for the Runtime Manager |
| `mule/docker_mulesoft/` | Mule runtime image build context (editing it rolls the workers) |
