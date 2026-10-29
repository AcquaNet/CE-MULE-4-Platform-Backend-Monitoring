# Setup Guide

## Quick start

```bash
./install.sh            # .env with generated secrets (first run), build, start, wait, print URLs
docker compose ps       # every service should be healthy
docker compose down     # stop (data kept); start again with docker compose up -d
```

For an overview, see [README.md](README.md). The full reference is [CLAUDE.md](CLAUDE.md).

## Guides

| Guide | Covers |
|-------|--------|
| [01 Quick start](docs/setup/01-quick-start.md) | first run, lite installs, memory per profile, first checks |
| [02 Architecture](docs/setup/02-architecture.md) | components, networks, request/log/trace flow |
| [03 APISIX gateway](docs/setup/03-apisix-gateway.md) | standalone routes, plugins, hot reload, Control API |
| [04 OpenSearch](docs/setup/04-opensearch.md) | OpenSearch, Dashboards, Fluent Bit, queries |
| [05 Mule backend](docs/setup/05-mule-backend.md) | runtime pools, deployments, ActiveMQ, MySQL |
| [06 Configuration](docs/setup/06-configuration.md) | profiles, `GATEWAY_AUTH`, `.env`, memory knobs |
| [07 Troubleshooting](docs/setup/07-troubleshooting.md) | common problems in this stack |
| [08 Logging integration](docs/setup/08-logging-integration.md) | Mule log4j appender, Docker and CloudHub |
| [09 Tracing](docs/setup/09-apm-integration.md) | OpenTelemetry Mule 4 agent and Jaeger |
| [Security](docs/SECURITY_SETUP.md) | exposure, auth model, secret rotation |
| [SSL/TLS](docs/SSL_TLS_SETUP.md) | gateway certificates, own domain, Let's Encrypt |
| [JWT authentication](docs/JWT_AUTHENTICATION_GUIDE.md) | Keycloak tokens for `/api/*`, rate limits |
| [Multi-tenancy](docs/MULTITENANCY_SETUP.md) | tenant_id, DLS roles, tenant users |
| [Multi-tenancy demo](DEMO_MULTITENANCY.md) | step-by-step DLS demo with two tenants |
| [Artifactory](docs/ARTIFACTORY_DEPLOYMENT.md) | publishing Mule apps, how the Runtime Manager fetches them |
| [Backup](docs/BACKUP_SETUP.md) | OpenSearch snapshots |
| [Retention](docs/RETENTION_POLICY_GUIDE.md) | log-archiver: 1 year or disk limit, gzip archive, optional S3 |
| [Monitoring](docs/MONITORING_SETUP.md) | Prometheus, Grafana, Alertmanager |
| [Offline images](docs/DOCKER_IMAGES_EXPORT.md) | export/import Docker images |
| [Mule platform](mule/README.md) | runtime pools, Runtime Manager API |
| [Worker nodes](node/README.md) | workers on other servers |
| [Testing](TESTING.md) | the automated test suite (`tests/run.sh`) |
