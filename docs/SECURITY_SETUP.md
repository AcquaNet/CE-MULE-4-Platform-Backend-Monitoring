# Security

## Secrets: the root `.env`

`install.sh` (via `config/scripts/setup/generate-secrets.sh`) creates `.env` from `.env.example`, with random
values for every password, token and key. The file is git-ignored and has mode 600. Compose sets no default
passwords; some services refuse to start without theirs (`:?` checks). The `ops` password, the OTLP key, the
gateway client secrets, the session key and the ActiveMQ admin password become random values when unset, so those routes stay
closed. Keep every secret set, keep `.env` private, and never use `.env.example` values.

## What is reachable

| Exposure | Ports / paths |
|----------|---------------|
| Public (all interfaces) | 9443 HTTPS gateway; 9100 log intake (TCP, token in each event) |
| Host only (127.0.0.1) | 9080 HTTP gateway, 9091 APISIX metrics (no auth), MySQL 3306, ActiveMQ 8161/5672/61616 (clients sign in as `admin` / `ACTIVEMQ_ADMIN_PASSWORD`) |
| Not published | OpenSearch 9200, Dashboards, Jaeger, Keycloak, Runtime Manager, Prometheus, Grafana, APISIX Control API (9092, container-local) |

On a server, firewall 9443 and 9100 to the clients that need them (e.g. CloudHub's egress IPs). For worker
nodes, see [node/README.md](../node/README.md#network).

## Who can do what

| Path | Rule |
|------|------|
| `/api/*`, per-app routes | Keycloak token for `mule-api-gateway` with role `api-access`, `X-Tenant-ID` from the token, rate limits: [JWT_AUTHENTICATION_GUIDE.md](JWT_AUTHENTICATION_GUIDE.md) |
| `/` (home page) | Keycloak sign-in (any realm user); the gateway session is shared by `/jaeger`, `/prometheus`, `/activemq` |
| `/jaeger`, `/prometheus`, `/activemq` | Keycloak realm role `admin` in a token issued to `gateway-sso` (browser) or `mule-api-gateway` (scripts: bearer token); others get 403. `/activemq/api/*` (Jolokia, REST) is blocked |
| `/grafana` | Keycloak sign-in (client `grafana`), realm role `admin` only; local break-glass `GRAFANA_ADMIN_USER` |
| `/dashboards` | Keycloak sign-in (client `dashboards`): `admin` sees all, other users only their token's `tenant_id` (DLS) |
| `/opensearch` | Port 9080 only (404 on 9443). OpenSearch login: `admin` / `OPENSEARCH_ADMIN_PASSWORD`, or tenant users limited by DLS |
| `/runtime-manager` | Keycloak sign-in with realm role `RM_OIDC_ROLE` (default `admin`); Basic `RM_USER`/`RM_PASSWORD` and API tokens for scripts. Admin only: it holds the Docker socket |
| `/otlp` | header `x-otlp-token` = `OTLP_INGEST_TOKEN` |
| TCP 9100 | event field `auth_token` = `LOG_INGEST_TOKEN`, otherwise the event is dropped |
| `/auth` | Keycloak's own login. Realm `mule`: brute-force protection, `sslRequired` external. The master realm (server admin) answers on 9080 only (404 on 9443) |

`GATEWAY_AUTH=off` (lite installs without Keycloak) removes the token check: `/api/*` is then **open**. `/jaeger`,
`/prometheus`, `/activemq` fall back to basic auth `ops` / `GATEWAY_OPS_PASSWORD`, Grafana and Dashboards to their
local logins, and the home page is public.

**OpenSearch** has only the internal user `admin`. It uses its own per-install, self-signed node certificate
made on the first start, with no demo config, demo users or published demo certificates. Its REST API is
reachable only through the gateway on 9080 (host loopback). **Keycloak 26** runs in production mode (`start`) with
realm `mule`; `tenant_id` is declared in its user profile (users can see it, only admins edit it). Gateway SSO
responses carry `X-Frame-Options: DENY` / `frame-ancestors 'none'`, and a cross-site `/logout` is refused.
**HTTPS** on 9443 is on by default ([SSL_TLS_SETUP.md](SSL_TLS_SETUP.md)).

## Rotating secrets

Change the value in `.env`, then run `docker compose up -d`, which recreates the services whose environment
changed. Some secrets are written only on the first initialization of their data volume, and these need an extra
step:

| Secret | How |
|--------|-----|
| `GATEWAY_OPS_PASSWORD` (only with `GATEWAY_AUTH=off`), `OTLP_INGEST_TOKEN` | `.env` + `up -d` (APISIX re-renders). Update external OTLP senders; the Runtime Manager passes the new token to node workers |
| `LOG_INGEST_TOKEN` | `.env` + `up -d` (Fluent Bit, and the Runtime Manager, whose restart recreates its workers). Update CloudHub's `logs.token` |
| `RM_PASSWORD` | `.env` + `up -d` |
| `ACTIVEMQ_ADMIN_PASSWORD` | `.env` + `up -d` (applied on every start; APISIX re-renders the console sign-in) |
| `GATEWAY_SESSION_SECRET`, `DASHBOARDS_COOKIE_SECRET` | `.env` + `up -d`; signs everyone out of the gateway / Dashboards |
| `MULE_GATEWAY_CLIENT_SECRET`, `RM_OIDC_CLIENT_SECRET`, `DASHBOARDS_OIDC_CLIENT_SECRET`, `GATEWAY_SSO_CLIENT_SECRET`, `GRAFANA_OIDC_CLIENT_SECRET` | Regenerate in the Keycloak admin console (Clients > Credentials), copy the value to `.env`, then `up -d`. The realm file is imported only into an empty Keycloak DB |
| `KEYCLOAK_REALM_ADMIN_PASSWORD`, `KEYCLOAK_REALM_DEV_PASSWORD` | Realm import only: afterwards change them in the admin console |
| `KEYCLOAK_ADMIN_PASSWORD` | Used only when the Keycloak DB is created: afterwards change it in the master realm (9080 only: http://localhost:9080/auth/admin/master/console/) |
| `KEYCLOAK_DB_PASSWORD` | Postgres first init only: `ALTER USER keycloak PASSWORD '...'` in `keycloak-db`, then `.env` + `up -d` |
| `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` | MySQL first init only: `ALTER USER` in MySQL, then `.env` |
| `OPENSEARCH_ADMIN_PASSWORD` | Applied only when the security index is created: changing it means wiping the `opensearch-data` volume (logs and traces are lost; take a snapshot first, see [BACKUP_SETUP.md](BACKUP_SETUP.md)) |
| `GRAFANA_ADMIN_PASSWORD` | Used only on Grafana's first start: afterwards `docker exec grafana grafana cli admin reset-admin-password '<new>'` |
| `RM_SECRETS_KEY` | **Don't rotate casually.** It encrypts stored secure app properties and node tokens; with a new key they can't be read and must be re-entered (secure properties per app, tokens per node) |

To regenerate everything on a fresh install (no data yet), run
`config/scripts/setup/generate-secrets.sh --force`. On an existing install that breaks the first-init secrets
listed above.

## Further hardening

- Use a public certificate for remote clients, and a domain in `GATEWAY_HOSTNAMES` or your own cert
  ([SSL_TLS_SETUP.md](SSL_TLS_SETUP.md)).
- Put the platform and its worker nodes on a private network: APISIX reaches node workers over plain HTTP.
- 9100 is plain TCP. Restrict it by source IP, or use a VPN for untrusted networks.
