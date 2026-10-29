# Quick Start

## Prerequisites

- Docker with Compose v2 (`docker compose`; `include:` needs it)
- Internet access on the first run: images, plus the Mule CE download when the Runtime Manager builds the runtime image
- Free host ports: 9443 and 9100 (public); 9080, 9091, 3306, 8161, 5672 and 61616 (bound to 127.0.0.1)

## Start

```bash
./install.sh
```

On a fresh clone `install.sh` creates `.env` with generated secrets. It then builds and starts the profiles in
`COMPOSE_PROFILES` and waits until everything is healthy, including the Runtime Manager's pool workers and the
default app. Finally it prints the URLs. It is safe to run again.

On the first start, APISIX creates a local CA (`certs/ca`) and the gateway certificate (`certs/apisix`). Trust
`certs/ca/ca.crt` in your OS or browser, or pass `--cacert certs/ca/ca.crt` to curl (Windows curl also needs
`--ssl-no-revoke`). The Runtime Manager builds `ce-mule-runtime:<mule>-java<java>-<hash>` (e.g.
`ce-mule-runtime:4.12.0-java17-acc0763048`) and starts the default pool
(`mule-default-1`, `mule-default-2`).

Day to day:

```bash
docker compose up -d                                       # start
docker compose down                                        # stop; the Runtime Manager removes its workers
docker compose --profile "*" down -v --remove-orphans      # full reset, deletes all data
```

## Lite installs

Profiles: see the [README](../../README.md#profiles). Gateway plus Mule only:

```env
COMPOSE_PROFILES=
GATEWAY_AUTH=off   # required without `auth`: /api/* then has NO authentication
```

## Memory

Measured with `docker stats`: the default profiles use about **4.6 GB**. Set the Docker memory limit (Docker
Desktop: Settings > Resources) at least 1 GB above that.

| Part | Approx. memory |
|------|----------------|
| APISIX + Runtime Manager (always) | ~0.1 GB |
| Mule workers (always) | ~0.6 GB each when idle (default pool: 2 workers, heap capped at pool `heap_mb` = 1024 MB) |
| `logging` | ~1.66 GB (OpenSearch ~1.43, Dashboards ~0.22, Fluent Bit ~0.01) |
| `tracing` | ~0.02 GB (+ OpenSearch if `logging` is off) |
| `auth` | ~0.67 GB |
| `mq` | ~0.24 GB |
| `db` | ~0.19 GB |
| `monitoring` | ~0.13 GB |
| Worker node (other server) | ~0.02 GB agent + ~0.6 GB per worker |

The settings that change these numbers are listed in [06-configuration.md](06-configuration.md#memory).

## First checks

```bash
set -a; . ./.env; set +a
docker compose ps                                                     # all healthy
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:9443/api/v1/status   # 401: a token is required
```

Get a token and call the Mule API:

```bash
TOKEN=$(curl -sk https://localhost:9443/auth/realms/mule/protocol/openid-connect/token \
  -d grant_type=password -d client_id=mule-api-gateway -d "client_secret=$MULE_GATEWAY_CLIENT_SECRET" \
  -d username=admin -d "password=$KEYCLOAK_REALM_ADMIN_PASSWORD" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
curl -sk -H "Authorization: Bearer $TOKEN" https://localhost:9443/api/v1/status
```

Send a test log event and find it:

```bash
echo '{"auth_token":"'"$LOG_INGEST_TOKEN"'","message":"hello","level":"INFO"}' | nc -w 2 localhost 9100
sleep 6
curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "http://localhost:9080/opensearch/logstash-*/_search?q=message:hello&pretty"
```

| UI | URL | Login |
|----|-----|-------|
| Home page (links to every tool) | https://localhost:9443/ | Keycloak `admin` / `KEYCLOAK_REALM_ADMIN_PASSWORD`, once for all tools |
| Runtime Manager | https://localhost:9443/runtime-manager/ | same Keycloak session |
| Dashboards | https://localhost:9443/dashboards/ | same (non-admins see only their tenant's logs) |
| Jaeger, Prometheus, ActiveMQ | https://localhost:9443/jaeger/ etc. | same (realm role `admin`) |
| Grafana | https://localhost:9443/grafana/ | same (realm role `admin`) |

Every URL and port is listed in the [README](../../README.md#urls-and-ports). For problems, see
[07-troubleshooting.md](07-troubleshooting.md).

## Next

[02 Architecture](02-architecture.md) · [03 APISIX](03-apisix-gateway.md) · [04 OpenSearch](04-opensearch.md) ·
[05 Mule backend](05-mule-backend.md)
