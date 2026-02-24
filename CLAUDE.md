# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Complete Mule 4 development platform with integrated logging, tracing, and API gateway:
- **Apache APISIX Gateway**: API gateway and load balancer (port 9080/9443)
- **OpenSearch Stack**: OpenSearch, Logstash, OpenSearch Dashboards for centralized logging
- **Jaeger**: Distributed tracing with OpenSearch backend
- **OpenTelemetry Mule 4 Agent**: Custom tracing agent for Mule applications
- **Mule Application**: Mule 4.4.0 backend with RESTful APIs
- **Docker Infrastructure**: Load-balanced Mule workers with supporting services
- **Multi-Tenancy**: Document-Level Security (DLS) for tenant isolation (FREE with OpenSearch)

## Repository Structure

```
Docker ElasticSearch/
├── docker-compose.yml              # OpenSearch + APISIX orchestration (HTTP)
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
│   ├── ca/, apisix/, opensearch/   # Active certificates
│   └── extra/                      # Optional end-to-end encryption
├── config/                         # All configuration
│   ├── apisix/                     # APISIX config and routes
│   │   ├── config.yaml             # Main APISIX config
│   │   └── apisix-opensearch.yaml  # OpenSearch routes configuration
│   ├── logstash/                   # Pipeline configuration
│   ├── prometheus/, alertmanager/, grafana/
│   └── scripts/                    # setup/, backup/, monitoring/, ilm/, tenants/
├── git/
│   ├── CE-MULE-4-Platform-Backend-Mule/    # Mule 4 source
│   ├── CE-MULE-4-Platform-Backend-Docker/  # Docker deployment
│   └── elastic-apm-mule4-agent/            # OpenTelemetry Mule 4 Agent
│       └── otel-mule4-agent/               # Custom OTEL agent source
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
| OpenSearch | 172.42.0.10 | 9200 | Via APISIX: `/opensearch` |
| Logstash | 172.42.0.11 | 5000 (TCP/UDP), 9600 | Via APISIX: `/logstash` |
| OpenSearch Dashboards | 172.42.0.12 | 5601 | Via APISIX: `/dashboards` |
| Jaeger | 172.42.0.13 | 16686 (UI), 4317 (OTLP gRPC), 4318 (OTLP HTTP) | Via APISIX: `/jaeger` |
| Mule Worker 1 | 172.42.0.2 | 8081 | Via APISIX: `/api/*` |
| Mule Worker 2 | 172.42.0.30 | 8081 | Via APISIX: `/api/*` |
| MySQL | 172.42.0.3 | 3306 | Direct |
| ActiveMQ | 172.42.0.5 | 8161, 61616 | Via APISIX: `/activemq` |

**APISIX Routes:**
- `/dashboards` → OpenSearch Dashboards UI
- `/opensearch/*` → OpenSearch API
- `/logstash/*` → Logstash API (load balanced)
- `/jaeger/*` → Jaeger UI and API
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
# OpenSearch Dashboards
curl http://localhost:9080/dashboards

# OpenSearch API (requires auth)
curl -k -u admin:admin https://localhost:9200/_cluster/health?pretty

# Jaeger UI
curl http://localhost:16686/jaeger/

# Mule API (load balanced)
curl http://localhost:9080/api/v1/status
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

### OpenSearch Queries
```bash
# List indices
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/_cat/indices?v"

# Query Mule logs
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/mule-logs-*/_search?pretty" \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match": {"level": "ERROR"}}}'
```

### Jaeger Tracing
```bash
# List services
curl -s "http://localhost:16686/jaeger/api/services"

# Query traces
curl -s "http://localhost:16686/jaeger/api/traces?service=ce-mule-base-worker-1&limit=10"
```

### Test Logstash
```bash
echo '{"application":"test","log_type":"mule","level":"INFO","message":"Test","tenant_id":"acme-corp"}' | nc localhost 5000
```

## Mule Application

**Location:** `git/CE-MULE-4-Platform-Backend-Mule`

**Key Files:**
- `pom.xml`: Maven config (Mule 4.4.0-20250919)
- `src/main/mule/`: Flow definitions
- `src/main/resources/api/ce-backend.raml`: API spec
- `src/main/resources/log4j2.xml`: Logging config with tenant_id support
- `01-build-and-deploy.sh`: Build script

**API Endpoint:** `GET /api/v1/status` - Health check

**Build Process:** Script reads version from `common.properties`, auto-increments, commits, builds, deploys to JFrog Artifactory.

## OpenTelemetry Mule 4 Agent

**Location:** `git/elastic-apm-mule4-agent/otel-mule4-agent`

Custom OpenTelemetry agent that instruments Mule 4 applications for distributed tracing with Jaeger.

**Features:**
- Automatic span creation for Mule flows and processors
- Correlation ID propagation
- Worker identification
- Environment and version tagging

**Build:**
```bash
cd git/elastic-apm-mule4-agent/otel-mule4-agent
mvn clean package -DskipTests
# Output: target/otel-mule4-agent-0.1.0.jar
```

**Deployment:**
The agent JAR is automatically loaded by Mule workers via:
1. Copy to app's `lib/` folder
2. Configure via `tracer.xml` in the Mule app
3. Set environment variables for OTEL configuration

**Environment Variables (Mule workers):**
```yaml
OTEL_SERVICE_NAME: ce-mule-base-worker-1
OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
OTEL_EXPORTER_OTLP_PROTOCOL: grpc
OTEL_TRACES_EXPORTER: otlp
OTEL_METRICS_EXPORTER: none
OTEL_LOGS_EXPORTER: none
```

## Logstash Pipeline

**Config:** `config/logstash/pipeline/logstash.conf`

**Inputs:** Beats (5044), TCP/UDP (5000)

**Index Routing:**
- Mule logs (detected via `log_type` or `application` field) → `mule-logs-YYYY.MM.dd`
- Others → `logstash-YYYY.MM.dd`

**Mule Log Fields:** `tenant_id`, `application`, `environment`, `worker_id`, `level`, `loggerName`, `message`, `correlationId`, `@timestamp`

**Output:** OpenSearch with authentication
```ruby
opensearch {
  hosts => ["https://opensearch:9200"]
  user => "admin"
  password => "admin"
  ssl => true
  ssl_certificate_verification => false
}
```

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

## Log Retention (ISM)

OpenSearch uses Index State Management (ISM) instead of ILM.

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
- Jaeger: http://localhost:16686/jaeger/

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
- ✅ OpenSearch Security enabled (auth required, default: admin/admin)
- ✅ Document-Level Security (DLS) enabled for multi-tenancy (FREE)
- ⚠️ SSL disabled by default (enable for production)

**Quick Setup:**
```bash
./config/scripts/setup/generate-secrets.sh
docker-compose up -d
# OpenSearch Dashboards: http://localhost:9080/dashboards (admin/admin)
```

**Production Checklist:**
- Enable TLS (see SSL_TLS_SETUP.md)
- Change APISIX admin password (admin/admin) and API key
- Change OpenSearch admin password
- Change default passwords (Grafana, MySQL)
- Configure firewall rules

See [SECURITY_SETUP.md](docs/SECURITY_SETUP.md).

## Multi-Tenancy

**Status:** Document-Level Security (DLS) enabled for tenant isolation - **FREE with OpenSearch!**

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

# Create tenant with OpenSearch user
./config/scripts/tenants/manage-tenants.sh create acme-corp --user acme_user --password SecurePass

# List tenants
./config/scripts/tenants/manage-tenants.sh list

# Verify tenant isolation
./config/scripts/tenants/manage-tenants.sh verify acme-corp

# Delete tenant
./config/scripts/tenants/manage-tenants.sh delete acme-corp
```

**Test with Tenant Header:**
```bash
curl -H "X-Tenant-ID: acme-corp" http://localhost:9080/api/v1/status
```

**Test DLS in OpenSearch:**
```bash
# Admin sees all documents
docker exec opensearch curl -s -k -u admin:admin "https://localhost:9200/mule-logs-*/_search" | grep tenant_id

# Tenant user only sees their documents
docker exec opensearch curl -s -k -u acme_user:AcmePass123! "https://localhost:9200/mule-logs-*/_search" | grep tenant_id
```

**Keycloak SSO (Optional):**
Set `KIBANA_OIDC_ENABLED=true` in `.env` for Keycloak OIDC authentication with OpenSearch Dashboards.

See [MULTITENANCY_SETUP.md](docs/MULTITENANCY_SETUP.md).

## APM Data Locations

Trace data is stored in Jaeger indices within OpenSearch:

| Index Pattern | Description |
|---------------|-------------|
| `jaeger-span-*` | Trace spans (flow executions, processors) |
| `jaeger-service-*` | Service metadata |

**View APM Data:**
1. **Jaeger UI** (recommended): http://localhost:16686/jaeger/
   - Select service: `ce-mule-base-worker-1` or `ce-mule-base-worker-2`
   - View traces with timing and span hierarchy

2. **OpenSearch Dashboards**: http://localhost:9080/dashboards
   - Create index pattern: `jaeger-span-*` (time field: `startTimeMillis`)
   - Use Discover to search spans

## Configuration Reference

**Memory Settings:**
- OpenSearch: 512MB heap (production: 2GB+)
- Logstash: 256MB heap

**Environment Variables:**
- `MULEAPP_GROUP_ID`, `MULEAPP_ARTIFACT_ID`, `MULEAPP_VERSION`: Maven coordinates
- `ATINA_REPOSITORY_URL`: Artifactory URL
- `OPENSEARCH_PASSWORD`: OpenSearch admin password (default: admin)
- `SSL_ENABLED`: Enable SSL/TLS
- `LOGSTASH_AUTH_TOKEN`: Token for Logstash authentication

**Important Notes:**
1. OpenSearch and Mule share networks (`ce-base-micronet`, `ce-base-network`)
2. Mule connects to Logstash via hostname `logstash:5000`
3. APISIX requires etcd to be healthy before starting
4. APISIX Admin API key: `edd1c9f034335f136f87ad84b625c8f1` (change in production!)
5. Jaeger uses OpenSearch as storage backend with OTLP protocol
6. OpenTelemetry Mule 4 Agent version: 0.1.0 (OpenTelemetry SDK 1.32.0)

## Migration from ELK Stack

This platform was migrated from ELK (ElasticSearch, Logstash, Kibana) to OpenSearch stack:

| ELK Component | OpenSearch Replacement | Reason |
|---------------|----------------------|--------|
| ElasticSearch | OpenSearch | Free DLS, open source |
| Kibana | OpenSearch Dashboards | Compatible UI |
| APM Server | Jaeger | Open source, OTLP support |
| Elastic APM Agent | OpenTelemetry Mule 4 Agent | Vendor-neutral tracing |

**Key Benefits:**
- **Document-Level Security (DLS)**: FREE with OpenSearch (was paid X-Pack feature)
- **Open Source**: No licensing concerns
- **OpenTelemetry**: Vendor-neutral observability standard
- **Jaeger**: Native OpenSearch integration for trace storage
