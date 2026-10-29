# Troubleshooting

Start with:

```bash
docker compose ps                         # what is not healthy?
docker compose logs --tail 100 <service>
```

## OpenSearch does not start

| Symptom | Fix |
|---------|-----|
| `max virtual memory areas vm.max_map_count [65530] is too low` | Linux: `sudo sysctl -w vm.max_map_count=262144` (persist it in `/etc/sysctl.d/`). Docker Desktop/WSL: `wsl -d docker-desktop sysctl -w vm.max_map_count=262144` |
| Unhealthy with 401 in its healthcheck after `OPENSEARCH_ADMIN_PASSWORD` was changed in `.env` | The password applies only when the security index is first created. Put the old value back, or wipe the volume (deletes logs and traces): `docker compose down`, then `docker volume rm dockerelasticsearch_opensearch-data` |
| Password rejected on first start | OpenSearch refuses weak passwords; use the generated one (`config/scripts/setup/generate-secrets.sh`) |
| Out of memory / killed | Raise the Docker memory limit, or lower `OPENSEARCH_JAVA_OPTS` (see [06](06-configuration.md#memory)) |

Fluent Bit, Jaeger, Dashboards and the exporter wait for OpenSearch to be healthy, so they stay down with it.

## Mule workers / Runtime Manager

```bash
docker ps --filter label=rm.pool                                  # workers and their health
docker compose logs ce-base-runtime-manager | grep -i "pool\|seed\|error"
docker logs mule-default-1                                        # a worker's console
docker exec mule-default-1 tail -n 200 /opt/mule/mule-standalone/logs/mule.log
```

| Symptom | Cause / fix |
|---------|-------------|
| No workers, pool in `error` | The runtime image build failed (MuleSoft download unreachable, or a Mule/Java mismatch: 4.4 -> 8/11, 4.5-4.8 -> 8/11/17, 4.9+ -> 17). The pool card shows the error; fix it and use Retry |
| App `FAILED` | See the app's Logs tab. Check that the app supports the pool's Java, and that its HTTP port does not clash with another app on the same pool |
| Default app never deploys | Maven: wrong `MULEAPP_*` coordinates, missing `ARTIFACTORY_USER`/`ARTIFACTORY_PASSWORD`, or an `http://` repository (the Runtime Manager only uses https). Workaround: upload the jar |
| Workers restart when the Runtime Manager restarts | Expected: it removes its local workers on stop and recreates them on start |
| `docker compose down` cannot remove the networks | Workers left behind (the Runtime Manager was killed): `docker rm -f $(docker ps -aq --filter label=rm.pool)`, then run `down` again |
| `network ... incorrect label` on `up` | A network created by hand by an older setup: after `docker compose down`, run `docker network rm ce-base-micronet ce-base-network` |
| A node's workers are unreachable | See [node/README.md](../../node/README.md) (firewall 18000-18999, `GATEWAY_HOSTNAMES`) |

## 401 / 403 on /api

| Response | Meaning |
|----------|---------|
| 401 `bearer token required` or 401 from openid-connect | No token, an expired token (lifetime 3600 s), or a token that is not from realm `mule` |
| 403 `token must be issued to mule-api-gateway ...` | The token was issued to another client (e.g. `admin-cli`, `dashboards`), or the user lacks the client role `api-access` of `mule-api-gateway` |
| Every call fails, even with a good token | `GATEWAY_AUTH=on` without the `auth` profile (Keycloak not running), or Keycloak still starting: production mode builds its config on first start and takes a few minutes. Check `docker compose ps keycloak` |
| 429 / 503 | Rate limit (100/min per IP) or connection limit (20 + burst 10 per IP) |
| Token request refused although the password is right | Brute-force protection of realm `mule`: after 10 failures the user is locked for 60 s, growing up to 15 min. Wait, or clear it in the realm admin console (`/auth/admin/mule/console/`, user > Details) |

How to get a valid token: see [JWT_AUTHENTICATION_GUIDE.md](../JWT_AUTHENTICATION_GUIDE.md). Changes to
`config/keycloak/realms/mule-realm.json` are imported only into an empty Keycloak database.

`/jaeger`, `/prometheus` and `/activemq` redirect (302) to the Keycloak sign-in without a session, and answer 403 to
users without realm role `admin`. That is expected (with `GATEWAY_AUTH=off`: 401 without basic auth `ops`).
SSO works on `https://localhost:9443` (the redirect URIs are registered for localhost; Keycloak's URL is pinned
with `KC_HOSTNAME`). New realm clients need a re-import or the admin console on an existing install.

## APISIX

```bash
docker compose logs apisix | grep -i "rendered\|error\|warn"
```

| Symptom | Cause / fix |
|---------|-------------|
| An edit to `apisix.yaml` has no effect, or an error appears in the logs | YAML error (usually indentation). Fix the file and save again |
| 404 | No route matches the path (routes are prefix patterns like `/api/*`) |
| 502 / 503 on a UI path | The backend's profile is not active, or the backend is not healthy yet |
| A `config.yaml` change ignored | Only `apisix.yaml` hot-reloads: run `docker compose restart apisix` |
| Upstream health | Control API, see [03](03-apisix-gateway.md#control-api) |

## Certificates

| Symptom | Fix |
|---------|-----|
| Browser warning, or curl `unable to get local issuer certificate` | Trust `certs/ca/ca.crt` (local CA from the first start), or `curl --cacert certs/ca/ca.crt` |
| Windows curl `CRYPT_E_NO_REVOCATION_CHECK` | add `--ssl-no-revoke` |
| `ERR_SSL_KEY_USAGE_INCOMPATIBLE` (Chrome) | The certificate lacks `keyUsage digitalSignature`. Reissue it: `config/scripts/setup/generate-certs.sh --force` (see [SSL_TLS_SETUP.md](../SSL_TLS_SETUP.md)) |
| HTTPS stops after a certificate was replaced | APISIX runs as non-root: `chmod 644 certs/apisix/apisix.key` |
| Nodes or remote clients get a name mismatch | Add the address to `GATEWAY_HOSTNAMES` and run `./install.sh` again (re-issues a generated certificate) |

## Logs not arriving

See [08-logging-integration.md](08-logging-integration.md#troubleshooting).
