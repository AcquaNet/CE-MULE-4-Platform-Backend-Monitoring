# Mule Backend Deployment

Runtime pools, deployments, properties, updates and the Runtime Manager API are documented in
[mule/README.md](../../mule/README.md). This chapter keeps the default app setup, checks, ActiveMQ and MySQL.

- **Runtime Manager**: https://localhost:9443/runtime-manager/ runs the Mule workers as runtime pools
- **default pool**: `mule-default-1`, `mule-default-2`; image `ce-mule-runtime:<mule>-java<java>-<hash of mule/docker_mulesoft>`
  (e.g. `ce-mule-runtime:4.12.0-java17-acc0763048`), built on first start (a few minutes)
- **ActiveMQ** (profile `mq`), **MySQL** (profile `db`)

## Default app from Maven

Root `.env`:
```bash
MULEAPP_GROUP_ID=com.acqua
MULEAPP_ARTIFACT_ID=ce-mule-base
MULEAPP_VERSION=RELEASE
ATINA_REPOSITORY_URL=https://jfrog.atina-connection.com/artifactory/libs-release   # https only: the RM skips plain-http repos
ARTIFACTORY_USER=...            # read by mule/maven-settings.xml as ${env.ARTIFACTORY_USER}
ARTIFACTORY_PASSWORD=...        # ${env.ARTIFACTORY_PASSWORD}; only in .env, never in the repo
```

On first start the Runtime Manager downloads it (repos from `mule/maven-settings.xml` plus `ATINA_REPOSITORY_URL`)
and deploys it on the default pool as `<artifact-id>`; changing `MULEAPP_VERSION` redeploys it.

A local build can be uploaded instead (UI, or):
```bash
cd git/CE-MULE-4-Platform-Backend-Mule && mvn clean package
curl -fsS -X PUT "https://localhost:9443/runtime-manager/api/apps/ce-mule-base?pool=default" \
  -H "Authorization: Bearer $RM_TOKEN" -H "Content-Type: application/java-archive" \
  --data-binary @target/ce-mule-base-<version>-mule-application.jar
```

## Checks

```bash
docker ps --filter label=rm.pool                                        # workers (healthy)
docker exec mule-default-1 tail -f /opt/mule/mule-standalone/logs/mule.log   # look for "Started app '<app>'"
docker exec mule-default-1 curl -s http://localhost:8081/api/v1/status  # one worker, bypassing APISIX
for i in {1..20}; do                                                    # through APISIX ($TOKEN: mule-api-gateway token)
  curl -sk -o /dev/null -w "#$i: %{http_code}\n" -H "Authorization: Bearer $TOKEN" https://localhost:9443/api/v1/status
done
```

The Runtime Manager UI shows the per-worker app state (`STARTED`, `DEPLOYING`, `FAILED`) and the logs.

## ActiveMQ

- Web console: https://localhost:9443/activemq/ (Keycloak SSO, realm role `admin`; the gateway signs in to the console),
  or http://127.0.0.1:8161/admin/ as `admin` / `ACTIVEMQ_ADMIN_PASSWORD` (console allows only loopback, APISIX and the host)
- OpenWire `localhost:61616`, AMQP `localhost:5672` (both bound to 127.0.0.1)
- Clients sign in as `admin` / `ACTIVEMQ_ADMIN_PASSWORD` (no anonymous access). `/activemq/api/*` (Jolokia, REST) is
  blocked at the gateway; use the console (`/admin`)
- Config: stock ActiveMQ 5.19 with the changes listed in `mule/docker-apache/Dockerfile` (baked into the image);
  data in a named volume

## MySQL

```bash
mysql -h 127.0.0.1 -P 3306 -u ce_user -p     # $MYSQL_PASSWORD from .env; port bound to 127.0.0.1
```

`.env`: `MYSQL_ROOT_PASSWORD`, `MYSQL_DATABASE=ce_backend_db`, `MYSQL_USER=ce_user`, `MYSQL_PASSWORD`. Data in a named volume.

## Troubleshooting

- **Image build failed**: the pool card shows the error (MuleSoft repository unreachable, Mule/Java mismatch); "Retry".
  `docker compose logs ce-base-runtime-manager | grep pool`
- **Default app not deployed**: `docker compose logs ce-base-runtime-manager` (`seeded ...` or `seed ... failed: ...`):
  repository unreachable or wrong coordinates in `.env`. Workaround: upload the jar.
- **Workers unhealthy in APISIX**: check `/api/v1/status` on the worker (above) and the Control API:
  `docker run --rm --network container:apisix curlimages/curl:8.10.1 -s http://127.0.0.1:9092/v1/healthcheck`

Next: [Chapter 6: Configuration](06-configuration.md).
