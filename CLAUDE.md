# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Complete Mule 4 development platform with integrated logging and API gateway:
- **Apache APISIX Gateway**: API gateway and load balancer (port 9080/9443)
- **ELK Stack**: ElasticSearch, Logstash, Kibana for centralized logging
- **Mule Application**: Mule 4.4.0 backend with RESTful APIs
- **Docker Infrastructure**: Load-balanced Mule workers with supporting services
- **SOTA Components**: Offline installers for air-gapped environments

## Repository Structure

```
Docker ElasticSearch/
├── docker-compose.yml              # ELK + APISIX orchestration (HTTP)
├── docker-compose.ssl.yml          # SSL/TLS override for HTTPS
├── .env.example                    # Environment template
├── docs/                           # Detailed documentation
│   ├── setup/                      # Modular setup guides (01-09)
│   ├── SECURITY_SETUP.md
│   ├── SSL_TLS_SETUP.md
│   ├── BACKUP_SETUP.md
│   ├── RETENTION_POLICY_GUIDE.md
│   ├── MONITORING_SETUP.md
│   ├── MULTITENANCY_SETUP.md       # Multi-tenant DLS guide
│   ├── ARTIFACTORY_DEPLOYMENT.md
│   └── DOCKER_IMAGES_EXPORT.md
├── certs/                          # SSL/TLS certificates (git-ignored)
│   ├── ca/, apisix/, apm-server/   # Active certificates
│   └── extra/                      # Optional end-to-end encryption
├── config/                         # All configuration
│   ├── apisix/                     # APISIX config and routes
│   ├── logstash/                   # Pipeline configuration
│   ├── prometheus/, alertmanager/, grafana/
│   └── scripts/                    # setup/, backup/, monitoring/, ilm/, tenants/
├── git/
│   ├── CE-MULE-4-Platform-Backend-Mule/    # Mule 4 source
│   └── CE-MULE-4-Platform-Backend-Docker/  # Docker deployment
└── CE-Platform/_sota/              # Offline installers
```

## Network Architecture

**Networks:**
- `ce-base-micronet` (172.42.0.0/16): Internal with static IPs
- `ce-base-network`: External connectivity

**IP Assignments:**

| Service | IP | Ports | Access |
|---------|-----|-------|--------|
| APISIX Gateway | 172.42.0.20 | 9080 (HTTP), 9443 (HTTPS), 9180 (Admin) | External entry point |
| etcd | 172.42.0.21 | 2379 | Internal |
| APISIX Dashboard | 172.42.0.22 | 9000 | http://localhost:9000 |
| ElasticSearch | 172.42.0.10 | 9200 | Via APISIX: `/elasticsearch` |
| Logstash | 172.42.0.11 | 5000 (TCP/UDP), 9600 | Via APISIX: `/logstash` |
| Kibana | 172.42.0.12 | 5601 | Via APISIX: `/kibana` |
| APM Server | 172.42.0.13 | 8200 | Direct + `/apm-server` |
| Mule Worker 1 | 172.42.0.2 | 8081 | Via APISIX: `/api/*` |
| Mule Worker 2 | 172.42.0.30 | 8081 | Via APISIX: `/api/*` |
| MySQL | 172.42.0.3 | 3306 | Direct |
| ActiveMQ | 172.42.0.5 | 8161, 61616 | Via APISIX: `/activemq` |

**APISIX Routes:**
- `/kibana` → Kibana UI
- `/elasticsearch/*` → ElasticSearch API
- `/logstash/*` → Logstash API (load balanced)
- `/apm-server/*` → APM Server
- `/api/*` → Mule workers (round-robin, health checks on `/api/v1/status`)
- `/activemq/*` → ActiveMQ console

## Common Commands

### Start/Stop Services
```bash
docker-compose up -d                    # Start all
docker-compose down                     # Stop all
docker-compose down -v                  # Stop + remove data
docker-compose logs -f [service]        # View logs
```

### Access Services (via APISIX)
```bash
curl http://localhost:9080/kibana
curl http://localhost:9080/elasticsearch/_cluster/health?pretty
curl http://localhost:9080/api/v1/status    # Mule API (load balanced)
```

### APISIX Admin
```bash
# Dashboard: http://localhost:9000 (admin/admin)
curl http://localhost:9180/apisix/admin/routes -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

### Mule Build/Deploy
```bash
cd "git/CE-MULE-4-Platform-Backend-Mule"
./01-build-and-deploy.sh    # Auto-increment, build, deploy to Artifactory
```

### Mule Docker Platform
```bash
cd "git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice"
docker-compose up -d
docker-compose logs -f ce-base-mule-backend-1
```

### ElasticSearch Queries
```bash
curl http://localhost:9080/elasticsearch/_cat/indices?v
curl http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match": {"level": "ERROR"}}}'
```

### Test Logstash
```bash
echo '{"application":"test","log_type":"mule","level":"INFO","message":"Test"}' | nc localhost 5000
```

## Mule Application

**Location:** `git/CE-MULE-4-Platform-Backend-Mule`

**Key Files:**
- `pom.xml`: Maven config (Mule 4.4.0-20250919)
- `src/main/mule/`: Flow definitions
- `src/main/resources/api/ce-backend.raml`: API spec
- `src/main/resources/log4j2.xml`: ELK logging config
- `01-build-and-deploy.sh`: Build script

**API Endpoint:** `GET /api/v1/status` - Health check

**Build Process:** Script reads version from `common.properties`, auto-increments, commits, builds, deploys to JFrog Artifactory.

## Logstash Pipeline

**Config:** `config/logstash/pipeline/logstash.conf`

**Inputs:** Beats (5044), TCP/UDP (5000)

**Index Routing:**
- Mule logs (detected via `log_type` or `application` field) → `mule-logs-YYYY.MM.dd`
- Others → `logstash-YYYY.MM.dd`

**Mule Log Fields:** `tenant_id`, `application`, `environment`, `worker_id`, `level`, `loggerName`, `message`, `correlationId`, `@timestamp`

## SSL/TLS

**Default:** SSL termination at APISIX gateway (port 9443)

**Generate Certs:**
```bash
./config/scripts/setup/generate-certs.sh
./config/scripts/setup/generate-certs.sh --domain mydomain.local
```

**Enable SSL:**
```bash
# In .env: SSL_ENABLED=true
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d
```

**Let's Encrypt:**
```bash
./config/scripts/setup/setup-letsencrypt.sh --domain yourdomain.com --email admin@yourdomain.com
```

For complete SSL setup, see [SSL_TLS_SETUP.md](docs/SSL_TLS_SETUP.md).

## Log Retention (ILM)

**Defaults:** 2 years retention, 1GB rollover

```bash
./config/scripts/setup/setup-retention-policy.sh

# Custom:
export MULE_LOGS_RETENTION_DAYS=365
./config/scripts/setup/setup-retention-policy.sh
```

See [RETENTION_POLICY_GUIDE.md](docs/RETENTION_POLICY_GUIDE.md).

## Backup

```bash
./config/scripts/backup/configure-backup.sh   # Initial setup
./config/scripts/backup/backup.sh             # Create backup
./config/scripts/backup/restore.sh snapshot   # Restore
```

See [BACKUP_SETUP.md](docs/BACKUP_SETUP.md).

## Monitoring

```bash
./config/scripts/monitoring/check-health.sh           # Basic check
./config/scripts/monitoring/check-health.sh --watch   # Continuous
```

**Dashboards:**
- Prometheus: http://localhost:9080/prometheus
- Grafana: http://localhost:9080/grafana
- Alertmanager: http://localhost:9080/alertmanager

See [MONITORING_SETUP.md](docs/MONITORING_SETUP.md).

## Docker Images Export (Offline)

```bash
# Export (machine with internet)
./config/scripts/docker-images/export-images.sh

# Import (target machine)
./import-images.sh
```

See [DOCKER_IMAGES_EXPORT.md](docs/DOCKER_IMAGES_EXPORT.md).

## Security

**Status:**
- ✅ X-Pack Security enabled (auth required)
- ⚠️ SSL disabled by default (enable for production)

**Quick Setup:**
```bash
./config/scripts/setup/generate-secrets.sh
docker-compose up -d
# Kibana: http://localhost:9080/kibana (elastic / ELASTIC_PASSWORD from .env)
```

**Production Checklist:**
- Enable TLS (see SSL_TLS_SETUP.md)
- Change APISIX admin password (admin/admin) and API key
- Change default passwords (ElasticSearch, Grafana, MySQL)
- Configure firewall rules

See [SECURITY_SETUP.md](docs/SECURITY_SETUP.md).

## Multi-Tenancy

**Status:** Document-Level Security (DLS) enabled for tenant isolation

Each tenant can only view logs containing their specific `tenant_id`. Tenants are extracted from:
1. `X-Tenant-ID` request header (highest priority)
2. JWT `tenant_id` claim (from Keycloak)
3. Default "unknown"

**Setup Multi-Tenancy:**
```bash
./config/scripts/tenants/setup-multitenancy.sh
```

**Tenant Management:**
```bash
# Create tenant
./config/scripts/tenants/manage-tenants.sh create acme-corp

# Create tenant with ES user
./config/scripts/tenants/manage-tenants.sh create acme-corp --user acme_user --password SecurePass

# List tenants
./config/scripts/tenants/manage-tenants.sh list

# Verify tenant
./config/scripts/tenants/manage-tenants.sh verify acme-corp

# Delete tenant
./config/scripts/tenants/manage-tenants.sh delete acme-corp
```

**Test with Tenant Header:**
```bash
curl -H "X-Tenant-ID: acme-corp" http://localhost:9080/api/v1/status
```

**Keycloak SSO (Optional):**
Set `KIBANA_OIDC_ENABLED=true` in `.env` for Keycloak OIDC authentication.

See [MULTITENANCY_SETUP.md](docs/MULTITENANCY_SETUP.md).

## Configuration Reference

**Memory Settings:**
- ElasticSearch: 512MB heap (production: 2GB+)
- Logstash: 256MB heap

**Environment Variables:**
- `MULEAPP_GROUP_ID`, `MULEAPP_ARTIFACT_ID`, `MULEAPP_VERSION`: Maven coordinates
- `ATINA_REPOSITORY_URL`: Artifactory URL
- `ELASTIC_PASSWORD`: ElasticSearch password
- `SSL_ENABLED`: Enable SSL/TLS

**Important Notes:**
1. ELK and Mule share networks (`ce-base-micronet`, `ce-base-network`)
2. Mule connects to Logstash via hostname `logstash:5000`
3. APISIX requires etcd to be healthy before starting
4. APISIX Admin API key: `edd1c9f034335f136f87ad84b625c8f1` (change in production!)
5. APM Server 8.10.4 compatible with elastic-apm-agent 1.17.0
