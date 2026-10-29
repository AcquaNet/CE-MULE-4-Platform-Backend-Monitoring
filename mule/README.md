# Mule platform

Runtime Manager (which runs the Mule workers), ActiveMQ and MySQL. The root
`docker-compose.yml` `include:`s this folder's compose file, so everything is started from the
repository root with one command, and all settings live in the root `.env` ("Mule platform" section):

```sh
docker compose up -d --build     # from the repository root, not from this folder
```

## Layout

| Path | What |
|------|------|
| `docker-compose.yml` | Runtime Manager, ActiveMQ, MySQL (Mule workers are runtime pools, see below) |
| `docker_mulesoft/` | Build context of the Mule runtime image `ce-mule-runtime:<mule>-java<java>-<hash of this folder>` (e.g. `ce-mule-runtime:4.12.0-java17-acc0763048`), built by the Runtime Manager |
| `docker_mulesoft/images/wrapper-platform.conf` | Default heap, appended to the stock wrapper.conf at build; a pool's heap/JVM options arrive as `MULE_ARGS` (`-M` args in `entypoints/mule-start.sh`) |
| `runtime-manager/` | Runtime Manager (`app.py`, `pools.py`; Python stdlib + `cryptography`) + `test_app.py` self-check |
| `maven-settings.xml` | Maven repos, `<servers>` credentials and mirrors used by the Runtime Manager |
| `docker-apache/` | ActiveMQ image |
| `volumes/` | Runtime Manager state (`volumes/runtime-manager`: pools, artifacts, tokens), git-ignored |

## Profiles

MySQL is profile `db`, ActiveMQ `mq`; see [Profiles](../README.md#profiles) in the root README.

## Runtime pools (the Mule workers)

A runtime pool is a named Mule runtime: Mule version, Java version, heap, JVM options and a number of
workers. The Runtime Manager runs each pool as containers `mule-<pool>-<n>` through the Docker API
(`/var/run/docker.sock` is mounted into it) and builds the image `ce-mule-runtime:<mule>-java<java>-<hash>` from
`docker_mulesoft/` the first time a Mule/Java combination is used (editing that folder changes the hash: new image, rolled workers) (Mule CE is downloaded from MuleSoft's
public repository, sha1-verified). Apps on a pool share its workers; an app that needs another Mule
version, more memory or isolation gets its own pool.

- **default pool**: created on first start from the root `.env`, then edited in the UI/API:

  | Variable | Default | |
  |----------|---------|---|
  | `MULE_VERSION` | `4.12.0` | Mule CE version |
  | `MULE_JAVA_VERSION` | `17` | must match the runtime (table below) |
  | `RM_DEFAULT_POOL_HEAP_MB` | `1024` | heap per worker |
  | `RM_DEFAULT_POOL_REPLICAS` | `2` | workers (`mule-default-1`, `mule-default-2`) |

  | Mule CE | Java |
  |---------|------|
  | 4.4 | 8 or 11 |
  | 4.5 - 4.8 | 8, 11 or 17 |
  | 4.9+ | 17 |

- **Changing a pool** (UI "Runtime pools" or `PUT /api/pools/<pool>`) replaces its workers one at a time
  and redeploys their apps; the app must support the pool's Java version.
- APISIX's `/api/*` upstream follows the workers of the default app `ce-mule-base` (the
  `# BEGIN runtime-manager app ce-mule-base` block in `config/apisix/apisix.yaml`).
- Workers get the Runtime Manager's `WORKER_<NAME>` environment as `<NAME>` (e.g. `mule_env`,
  `LOG_INGEST_TOKEN`, `OTEL_*`); `worker.id=<container>` is added to `OTEL_RESOURCE_ATTRIBUTES`.
- The Runtime Manager removes its workers when it stops (so `docker compose down` can remove the
  networks) and recreates them on start: restarting it restarts the workers (local ones only).
- **Other servers** (horizontal scaling): install the node agent there (`node/install-node.sh`), register it
  under "Runtime pools > Nodes" (`PUT /api/nodes/<node>`), then give a pool workers per server
  (`"nodes": {"local": 2, "node-b": 2}` instead of `replicas`); workers there are `mule-<pool>-<node>-<n>`.
  See [node/README.md](../node/README.md) (network, security, outages).

```sh
docker ps --filter label=rm.pool                                     # workers
docker exec mule-default-1 cat /opt/mule/mule-version.txt            # installed Mule version
docker exec mule-default-1 tail -f /opt/mule/mule-standalone/logs/mule.log
```

## Runtime Manager

https://localhost:9443/runtime-manager/ (through APISIX; it has no published port): sign-in with Keycloak (realm role
`admin`) while `GATEWAY_AUTH=on`; `RM_USER` / `RM_PASSWORD` (Basic) or API tokens for scripts. API reference:
`/runtime-manager/api/docs` (OpenAPI spec at `/runtime-manager/api/openapi.json`; both linked from "API & settings").
The gateway certificate is self-signed: give curl `--cacert certs/ca/ca.crt` (Windows curl also `--ssl-no-revoke`; or `-k`).

- **Deploy**: jar upload or Maven coordinates, onto a pool. First start deploys
  `MULEAPP_GROUP_ID:MULEAPP_ARTIFACT_ID:MULEAPP_VERSION` to the default pool as app `<artifact-id>`;
  changing `MULEAPP_VERSION` redeploys it.
- **Workers** per app: all of the pool's workers (default), a number of them (the least busy, then kept; re-placed
  if the pool shrinks) or specific workers for fine tuning. The app's gateway route follows its workers.
- **Properties**: per app, injected on deploy (they override the app's own properties). Secure
  properties are encrypted at rest with `RM_SECRETS_KEY` (root `.env`) and never shown again. Saving
  restarts the app.
- **Updates** per Maven app: `Auto` (deploy new builds/releases; default for `x-SNAPSHOT`/`RELEASE`/`LATEST`),
  `Notify` (flag "update available"; default for pinned versions), `Off`. The check interval is set under
  "API & settings" (default `RM_MAVEN_POLL_SECONDS`, 0 = Check button only).
- **Gateway route** (optional) per app: `/<path>/*` → the app's pool workers, prefix stripped
  (`/orders/api/x` reaches the app as `/api/x`), Keycloak auth.
- **Overview**: requests, errors and latency from Jaeger, recent errors from OpenSearch.
- Logs: `docker compose logs ce-base-runtime-manager` (`pool ...`, `seeded ...`).

### Pipelines

Create a token under "API & settings" (shown once), then:

```sh
# Maven version + properties + secure properties in one call (the app restarts with them)
curl -fsS -X PUT https://localhost:9443/runtime-manager/api/apps/orders-api \
  -H "Authorization: Bearer $RM_TOKEN" -H "Content-Type: application/json" \
  -d '{"pool": "default", "group": "com.acqua", "artifact": "orders-api", "version": "1.4.2",
       "updates": "notify", "route": {"path": "/api/orders", "port": 8091},
       "properties": {"mule_env": "prod", "db.host": "mysql"},
       "secureProperties": {"db.password": "'"$DB_PASSWORD"'", "mule.key": "'"$MULE_KEY"'"}}'

# or upload the built jar
curl -fsS -X PUT "https://localhost:9443/runtime-manager/api/apps/orders-api?pool=default" \
  -H "Authorization: Bearer $RM_TOKEN" -H "Content-Type: application/java-archive" \
  --data-binary @target/orders-api-1.4.2-mule-application.jar

# properties only (null = keep the stored secure value)
curl -fsS -X PUT https://localhost:9443/runtime-manager/api/apps/orders-api/properties \
  -H "Authorization: Bearer $RM_TOKEN" -H "Content-Type: application/json" \
  -d '{"properties": {"mule_env": "prod"}, "secureProperties": {"db.password": null}}'

# a pool on another runtime
curl -fsS -X PUT https://localhost:9443/runtime-manager/api/pools/edge \
  -H "Authorization: Bearer $RM_TOKEN" -H "Content-Type: application/json" \
  -d '{"mule_version": "4.11.0", "java_version": "17", "heap_mb": 1024, "replicas": 2, "jvm_options": ["-XX:+UseG1GC"]}'
```

All endpoints: `/runtime-manager/api/docs`. Most used besides the above: `GET /api/apps`, `GET /api/pools`,
`POST /api/apps/<app>/restart`, `GET /api/apps/<app>/log`, `DELETE /api/apps/<app>`.
