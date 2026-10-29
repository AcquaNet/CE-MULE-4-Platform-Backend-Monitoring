# APISIX Gateway

APISIX 3.19 runs in **standalone mode**. `config/apisix/apisix.yaml` is the only source of routes, upstreams,
plugin configs, consumers and stream routes. There is no etcd, no Admin API and no APISIX Dashboard.

| File | Role |
|------|------|
| `config/apisix/apisix.yaml` | routes etc. (edit this) |
| `config/apisix/start.sh` | entrypoint: creates the first certificate, renders the live config, re-renders on change |
| `config/apisix/config/config.yaml` | listeners (9080, 9443, stream 9100), Control API, plugin list (only the 15 in use), nginx settings |

## Edit workflow

1. Edit `config/apisix/apisix.yaml` and save.
2. Within about 2 s, `start.sh` re-renders it into `/usr/local/apisix/conf/apisix.yaml` (atomically) and APISIX
   hot-reloads it. The same happens for `git pull`, Runtime Manager deployments and certificate changes.
3. Check the result:

```bash
docker compose logs apisix | grep -i "rendered\|error\|warn"
```

At render time, `start.sh`:
- replaces `${MULE_GATEWAY_CLIENT_SECRET}`, `${OTLP_INGEST_TOKEN}`, `${GATEWAY_OPS_PASSWORD}`,
  `${GATEWAY_SSO_CLIENT_SECRET}`, `${GATEWAY_SESSION_SECRET}` and `${ACTIVEMQ_BASIC_AUTH}` (base64
  `admin:ACTIVEMQ_ADMIN_PASSWORD`) with the values from `.env` (a random value if one is unset, so the route stays closed);
- with `GATEWAY_AUTH=off`, removes every `openid-connect` and `serverless-post-function` block (no auth on
  `/api/*`, public home page) and points the `sso-admin` routes at plugin_config `ops-basic`;
- appends `ssls:` with `certs/apisix/apisix.crt` + `apisix.key` (certificates are never stored in `apisix.yaml`).

A change to `config.yaml` needs `docker compose restart apisix`. `install.sh` does that restart for you when it
sees the file has changed.

**Generated blocks** (written by the Runtime Manager, don't edit by hand):
- `# BEGIN runtime-manager` ... `# END runtime-manager` at the top of `routes:`: per-app routes, each with a
  `# rm-route {json}` record line.
- `# BEGIN runtime-manager app <name>` / `pool <name>` inside an upstream's `nodes:`: the workers of that app or
  pool. Upstream `1` follows `app ce-mule-base`.

## Routes

| Route name(s) | URI | Upstream | Plugins |
|---------------|-----|----------|---------|
| `home` | `/`, `/sso/callback`, `/logout` | none (`mocking` serves the page) | `plugin_config_id: sso` (Keycloak sign-in, any user) |
| `mule-api-v1`, `mule-api-all` | `/api/v1/*`, `/api/*` | upstream `1` (mule-workers) | `openid-connect`, `serverless-post-function` (token check), `limit-count`, `limit-conn`, `cors`, `prometheus` |
| generated per app | `/<path>/*` | the app's workers | `plugin_config_id: mule-api-auth` (same checks + `limit-count`), `proxy-rewrite` strips the prefix |
| `runtime-manager-root`, `runtime-manager` | `/runtime-manager`, `/runtime-manager/*` | `ce-base-runtime-manager:8080` | `redirect`, `proxy-rewrite`, `client-control` (512 MB body); no gateway auth |
| `dashboards-root`, `dashboards-proxy` | `/dashboards`, `/dashboards/*` | `opensearch-dashboards:5601` | `proxy-rewrite` (root); Dashboards signs in with Keycloak itself |
| `opensearch-root`, `opensearch-api` | `/opensearch`, `/opensearch/*` | upstream `3` (`https://opensearch:9200`) | `serverless-pre-function` (404 unless port 9080), `proxy-rewrite`; OpenSearch does its own auth |
| `otlp-ingest` | `/otlp/*` (POST) | `jaeger:4318` | `key-auth` (header `x-otlp-token`, consumer `otlp_ingest`) |
| `jaeger-root`, `jaeger-proxy` | `/jaeger`, `/jaeger/*` | `jaeger:16686` | `plugin_config_id: sso-admin` (realm role `admin`) |
| `prometheus-root`, `prometheus-proxy` | `/prometheus`, `/prometheus/*` | `prometheus:9090` | `plugin_config_id: sso-admin` |
| `grafana-root`, `grafana-proxy` | `/grafana`, `/grafana/*` | `grafana:3000` | `proxy-rewrite` (root); Grafana signs in with Keycloak itself |
| `keycloak-root`, `keycloak-proxy` | `/auth`, `/auth/*` | `keycloak:8080` | `serverless-pre-function` (master realm: 404 unless port 9080), `proxy-rewrite` (X-Forwarded-* for `localhost:9443`) |
| `activemq-root`, `activemq-console` | `/activemq`, `/activemq/*` | `ce-base-apachemq-backend:8161` | `plugin_config_id: sso-admin`; `proxy-rewrite` sends the console login (`ACTIVEMQ_BASIC_AUTH`); `uri-blocker` refuses `/activemq/api/*` (Jolokia) |
| stream route `1` | TCP 9100 | `log-ingest:5000` | none; Fluent Bit checks the token |

**SSO (`sso`, `sso-admin`):** `openid-connect` with client `gateway-sso`, a session cookie (`GATEWAY_SESSION_SECRET`)
and `/logout`; a bearer token is accepted too. A `serverless-pre-function` drops client-sent `X-ID-Token`/`X-Userinfo`/
`X-Access-Token` and refuses a cross-site `/logout`; `response-rewrite` adds `X-Frame-Options: DENY` and
`frame-ancestors 'none'`. `sso-admin` returns 403 unless the token's `azp` is `gateway-sso` or `mule-api-gateway` and
it carries realm role `admin`.

**Token check (`serverless-post-function`):** runs after `openid-connect` has verified the token. It returns 401
when there is no bearer token. It returns 403 unless `azp` is `mule-api-gateway` and
`resource_access.mule-api-gateway.roles` contains `api-access`. It drops any client `X-Tenant-ID`, `X-ID-Token`,
`X-Userinfo` and `X-Access-Token`, and sets `X-Tenant-ID` from the token's `tenant_id` claim. See [JWT_AUTHENTICATION_GUIDE.md](../JWT_AUTHENTICATION_GUIDE.md).

**Limits:** 100 requests per 60 s per client IP (`limit-count`, 429). `/api/*` also allows at most 20 concurrent
connections per IP plus a burst of 10 (`limit-conn`, 503).

**Mule upstream `1`:** round-robin. Active health checks run every 30 s on `/api/v1/status`: healthy after 2
successes, unhealthy after 3 HTTP failures or timeouts. Passive checks also apply.

## Adding a route

Add an entry under `routes:` in `config/apisix/apisix.yaml`, for example:

```yaml
  - uri: /my-service/*
    name: my-service
    upstream:
      type: roundrobin
      nodes:
        "my-service:8080": 1
    plugins:
      proxy-rewrite:
        regex_uri: ["^/my-service/(.*)", "/$1"]
```

For a Mule app, set its route in the Runtime Manager instead (app Settings, or `route` in `PUT /api/apps/<app>`).

## Control API

The Control API listens on `127.0.0.1:9092` inside the container only: it has no auth and dumps the rendered
config, secrets included. The image has no curl, so run one in its network namespace:

```bash
docker run --rm --network container:apisix curlimages/curl:8.10.1 -s http://127.0.0.1:9092/v1/routes
```

`/v1/healthcheck` shows each upstream node as healthy or unhealthy; `/v1/routes` and `/v1/upstreams` dump what
is loaded. Stock APISIX (3.7, still in 3.13) answers those dumps with 500 "excessive nesting" once a hostname
node was resolved or health-checked (back-references to the parent object); `config/apisix/lua/apisix/control/v1.lua`
(loaded through `extra_lua_path` in config.yaml) wraps the stock module and removes them.

## Metrics and logs

- Prometheus metrics: `http://127.0.0.1:9091/apisix/prometheus/metrics` (host only; scraped by Prometheus).
- HTTP access and error logs go to the container output: `docker compose logs -f apisix`.
- Stream (TCP 9100) access log: the file `/usr/local/apisix/logs/stream-access.log` inside the container
  (`docker exec apisix tail -f /usr/local/apisix/logs/stream-access.log`).

## TLS

HTTPS on 9443 is always on. If `certs/apisix/apisix.{crt,key}` is missing, `start.sh` creates a local CA and a
certificate for `localhost`, `apisix`, `127.0.0.1` and `GATEWAY_HOSTNAMES`. Replacing the files (own domain,
Let's Encrypt) is picked up within about 2 s. See [SSL_TLS_SETUP.md](../SSL_TLS_SETUP.md).
