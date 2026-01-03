# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository is a complete Mule 4 development and deployment platform with integrated logging infrastructure and API gateway. It contains:
- **Apache APISIX Gateway** (root level): API gateway and load balancer for all services
- **ELK Stack** (root level): Centralized logging with ElasticSearch, Logstash, and Kibana
- **Mule Application Source**: Complete Mule 4 backend application with API definitions
- **Docker Infrastructure**: Production-ready containerized deployment environment with load-balanced Mule workers
- **SOTA Components**: Offline installers for air-gapped/restricted environments

## Repository Structure

```
Docker ElasticSearch/
├── docker-compose.yml              # ELK stack + APISIX gateway orchestration (HTTP)
├── docker-compose.ssl.yml          # SSL/TLS override for production HTTPS
├── .env.example                    # Environment configuration template
├── .gitignore                      # Security-enhanced git ignore rules
├── README.md                       # Project overview
├── SETUP.md                        # Main setup guide (Table of Contents)
├── CLAUDE.md                       # Detailed technical documentation for Claude Code
│
├── docs/                           # Detailed documentation
│   ├── setup/                      # Setup guides (modular)
│   │   ├── 01-quick-start.md
│   │   ├── 02-architecture.md
│   │   ├── 03-apisix-gateway.md
│   │   ├── 04-elk-stack.md
│   │   ├── 05-mule-backend.md
│   │   ├── 06-configuration.md
│   │   ├── 07-troubleshooting.md
│   │   ├── 08-logging-integration.md
│   │   └── 09-apm-integration.md
│   ├── SECURITY_SETUP.md           # Security credentials setup guide
│   ├── SSL_TLS_SETUP.md            # Complete SSL/TLS setup and configuration guide
│   ├── BACKUP_SETUP.md             # Complete backup and restore guide
│   ├── RETENTION_POLICY_GUIDE.md   # Log retention policy configuration
│   ├── MONITORING_SETUP.md         # Monitoring and alerting guide
│   ├── ARTIFACTORY_DEPLOYMENT.md   # JFrog Artifactory deployment guide
│   └── DOCKER_IMAGES_EXPORT.md     # Docker images export/import for offline deployment
│
├── certs/                          # SSL/TLS certificates (git-ignored)
│   ├── ca/                         # Certificate Authority files
│   ├── apisix/                     # APISIX Gateway certificates (ACTIVE)
│   ├── apm-server/                 # APM Server certificates (ACTIVE)
│   └── extra/                      # Optional end-to-end encryption certs
│       ├── elasticsearch/          # For HIPAA/PCI-DSS compliance
│       ├── kibana/                 # For zero-trust architecture
│       ├── logstash/               # Available if needed
│       ├── prometheus/             # Available if needed
│       ├── grafana/                # Available if needed
│       └── alertmanager/           # Available if needed
│
├── config/                         # All configuration files and scripts
│   ├── apisix/                     # Apache APISIX API Gateway configuration
│   │   ├── config/
│   │   │   ├── config.yaml         # APISIX main configuration
│   │   │   └── config-ssl.yaml     # APISIX SSL configuration
│   │   └── apisix.yaml             # Declarative route definitions
│   ├── apisix-dashboard/           # APISIX Dashboard configuration
│   │   └── conf.yaml
│   ├── apm-server/                 # APM Server configuration
│   │   └── apm-server.yml
│   ├── logstash/                   # Logstash configuration
│   │   ├── config/logstash.yml
│   │   └── pipeline/
│   │       ├── logstash.conf       # Input/filter/output pipeline
│   │       └── logstash-ssl.conf   # SSL pipeline configuration
│   ├── prometheus/                 # Prometheus monitoring configuration
│   │   ├── prometheus.yml          # Prometheus configuration
│   │   ├── web-config.yml          # SSL web config
│   │   └── rules/elk-alerts.yml    # Alert rules
│   ├── alertmanager/               # Alertmanager notification configuration
│   │   ├── alertmanager.yml        # Alertmanager configuration
│   │   ├── alertmanager.yml.template
│   │   └── config-ssl.yml          # SSL configuration
│   ├── grafana/                    # Grafana dashboards and datasources
│   │   └── provisioning/
│   │       ├── datasources/prometheus.yml
│   │       └── dashboards/
│   ├── mule/                       # Mule logging templates
│   │   ├── log4j2.xml              # Log4j2 config template for Mule apps
│   │   └── pom-dependencies.xml    # POM dependencies template
│   └── scripts/                    # All operational scripts
│       ├── setup/                  # Setup and maintenance scripts
│       │   ├── generate-secrets.sh
│       │   ├── generate-certs.sh
│       │   ├── setup-letsencrypt.sh
│       │   ├── renew-letsencrypt.sh
│       │   ├── copy-certs.sh
│       │   ├── setup-kibana.sh
│       │   ├── setup-apisix.sh
│       │   ├── configure-apisix-routes.sh
│       │   ├── setup-apm.sh
│       │   └── apisix-ssl-patch.sh
│       ├── backup/                 # Backup and restore scripts
│       │   ├── configure-backup.sh
│       │   ├── backup.sh
│       │   ├── restore.sh
│       │   ├── backup-cleanup.sh
│       │   └── setup-backup-cron.sh
│       ├── monitoring/             # Monitoring and alerting scripts
│       │   ├── setup-monitoring.sh
│       │   └── check-health.sh
│       ├── ilm/                    # Index Lifecycle Management scripts
│       │   └── setup-retention-policy.sh
│       └── docker-images/          # Docker image export/import for offline deployment
│           ├── export-images.sh    # Export all Docker images to tar files
│           ├── export-images.bat   # Windows version
│           ├── import-images.sh    # Import Docker images from tar files
│           ├── import-images.bat   # Windows version
│           └── README.md           # Docker images export/import guide
│
├── git/                            # Application source code
│   ├── CE-MULE-4-Platform-Backend-Mule/      # Mule 4 application source
│   └── CE-MULE-4-Platform-Backend-Docker/    # Docker deployment infrastructure
│
└── CE-Platform/_sota/              # Offline installers (ActiveMQ, Maven, Mule, JDK)
```

## Architecture

### Apache APISIX Gateway (Root Level)

Apache APISIX is a high-performance API gateway that provides centralized access control, load balancing, and routing for all services in the platform.

**Purpose:**
- Centralized entry point for all HTTP/HTTPS traffic
- Load balancing across multiple Mule worker instances
- Security: Hides internal service IPs and ports from direct external access
- Monitoring: Prometheus metrics and centralized logging
- Traffic management: Rate limiting, authentication, and request routing

**Services:**
- **APISIX Gateway** (172.42.0.20): Main reverse proxy and load balancer
  - Port 9080: HTTP Gateway (main entry point)
  - Port 9443: HTTPS Gateway (SSL/TLS termination)
  - Port 9180: Admin API for route configuration
  - Port 9091: Prometheus metrics endpoint
  - Port 9092: Control API
- **etcd** (172.42.0.21): Distributed configuration storage for APISIX
  - Port 2379: Client API
- **APISIX Dashboard** (172.42.0.22): Web UI for managing routes and upstreams
  - Port 9000: Dashboard web interface

**Routing Configuration:**
- **Kibana**: `/kibana` → Internal Kibana UI (no direct port 5601 exposure)
- **ElasticSearch**: `/elasticsearch/*` → Internal ElasticSearch API (no direct port 9200 exposure)
- **Logstash Monitoring**: `/logstash/*` → Internal Logstash API (load balanced, no direct port 9600 exposure)
- **APM Server**: `/apm-server/*` → APM Server API (direct port 8200 also available)
- **Mule APIs**: `/api/*` → Load balanced across Mule workers (round-robin)
- **ActiveMQ Console**: `/activemq/*` → ActiveMQ web console

**Load Balancing:**
- **Mule Workers**: Round-robin algorithm, health checks every 30s on `/api/v1/status`, automatic failover
- **Logstash Monitoring**: Round-robin algorithm, health checks every 30s, supports multiple instances
- **Note**: For TCP/UDP log ingestion load balancing, use external LB (HAProxy/nginx)

**Configuration Files:**
- `config/apisix/config/config.yaml`: Main APISIX configuration
- `config/apisix/apisix.yaml`: Declarative route and upstream definitions
- `config/scripts/setup/setup-apisix.sh`: Automated route configuration via Admin API

**Important Notes:**
- APISIX requires etcd to be healthy before starting
- All routes use declarative configuration for infrastructure-as-code
- Admin API key: `edd1c9f034335f136f87ad84b625c8f1` (change in production!)
- Logstash TCP/UDP ports (5000, 5044) remain externally accessible for CloudHub deployments

### ELK Stack (Root Level)

The root directory contains a complete logging infrastructure for capturing and analyzing Mule application logs.

**Services:**
- **ElasticSearch**: Full-text search and analytics engine (internal ports 9200, 9300)
  - External access via APISIX: `/elasticsearch`
- **Logstash**: Data processing pipeline that ingests, transforms, and sends data to ElasticSearch
  - Port 5044: Beats input - **Internal-only by default** (uncomment in docker-compose.yml for external)
  - Port 5000: TCP/UDP input for JSON data - **Internal-only by default** (uncomment in docker-compose.yml for external)
  - Port 9600: Monitoring API - **Routed via APISIX** at `/logstash`
- **Kibana**: Web interface for ElasticSearch management and visualization
  - External access via APISIX: `/kibana` (no direct port 5601 exposure)
- **APM Server**: Application Performance Monitoring for distributed tracing and metrics
  - Port 8200: APM data ingestion - **Externally accessible direct + via APISIX**
  - External access via APISIX: `/apm-server`
  - Kibana APM UI: `/kibana/app/apm`
- **kibana-setup**: One-time service that automatically creates data views for `mule-logs-*` and `logstash-*` indices

**Configuration:**
- Single-node ElasticSearch cluster configuration
- Health checks implemented for all services
- Persistent volume for ElasticSearch data storage
- Integrated with Backend network (`ce-base-micronet` and `ce-base-network`)
- Service dependencies: Logstash, Kibana, APM Server depend on ElasticSearch; APISIX depends on APM Server
- Security: `xpack.security.enabled=false` for development (enable for production with TLS)
- APM Server version 8.10.4 (compatible with elastic-apm-agent 1.17.0)
- **Memory Settings:**
  - ElasticSearch: 512MB heap (`-Xms512m -Xmx512m`). Production minimum: 2GB
  - Logstash: 256MB heap (`-Xms256m -Xmx256m`). Adjust based on pipeline complexity
- **Ulimits:**
  - `memlock`: Unlimited (prevents memory swapping)
  - `nofile`: 65536 (file descriptors)

### Mule Application (git/CE-MULE-4-Platform-Backend-Mule)

A Maven-based Mule 4.4.0 application with RESTful APIs.

**Key Components:**
- `pom.xml`: Maven project configuration with Mule runtime 4.4.0-20250919
- `src/main/mule/`: Mule flow definitions (ce-backend.xml, global-config.xml, prc-status.xml)
- `src/main/resources/api/ce-backend.raml`: RAML API specification
- `src/main/resources/config/`: Environment-specific properties (common.properties, local-docker.properties)
- `src/main/resources/log4j2.xml`: Log4j2 configuration with ELK integration
- `01-build-and-deploy.sh`: Automated build script that auto-increments versions and deploys to artifact repository

**API Endpoints:**
- `GET /api/v1/status`: Health check endpoint returning application version from common.properties

**Build Process:**
1. The build script reads version from `src/main/resources/config/common.properties`
2. Auto-increments patch version
3. Commits version change with message "deploy X.Y.Z"
4. Runs `mvn clean package`
5. Deploys JAR to JFrog Artifactory

**Dependencies:**
- Mule HTTP Connector 1.10.3
- Mule Sockets Connector 1.2.5
- APIKit Module 1.11.7
- Elastic APM Mule4 Agent 0.4.0 (for performance monitoring)

**Artifact Repository:**
- JFrog Artifactory: `jfrog.atina-connection.com`
- Repository ID: `acquanet-central` (releases), `acquanet-snapshots` (snapshots)
- Maven settings: `CE-Platform/_sota/settings.xml`
- For complete deployment guide, see [ARTIFACTORY_DEPLOYMENT.md](docs/ARTIFACTORY_DEPLOYMENT.md)

### Docker Infrastructure (git/CE-MULE-4-Platform-Backend-Docker)

Production Docker environment for running Mule applications with supporting services.

**Services in docker-compose.yml:**
- **ce-base-mule-backend-1** & **ce-base-mule-backend-2**: Mule 4.4.0 runtime servers (Workers 1 & 2)
  - Internal ports: 8081 (HTTP), 8082 (HTTPS) - no direct external access
  - External access via APISIX: `/api/*` (load balanced)
  - Auto-downloads Mule apps from artifact repository via Maven coordinates
  - Health check: Waits for "DEPLOYED" in mule.log
  - IPs: 172.42.0.2, 172.42.0.30
- **ce-base-apachemq-backend**: Apache ActiveMQ 5.15.3 (IP: 172.42.0.5)
- **ce-base-maven-backend**: Maven service for downloading application artifacts (IP: 172.42.0.4)
- **ce-base-status-viewer**: Custom status monitoring service (IP: 172.42.0.6)
- **ce-base-db-backend**: MySQL database (IP: 172.42.0.3)

**Network:**
- Internal network: `ce-base-micronet` (172.42.0.0/16) with static IPs
- External network: `ce-base-network` for external connectivity

**Volumes:**
- CEBackendHome: Application home directory (shared by both workers)
- CEBackendMuleLog1/2: Mule worker logs (connected to ELK stack)
- CEBackendMuleApps1/2: Deployed Mule applications for workers
- CEBackendActiveMQConf/Data: ActiveMQ configuration and data (shared)
- CEBackendDBBackendConfig/Data: MySQL configuration and data
- CEBackendMavenRepository: Maven local repository cache (shared)

**Environment Variables Required:**
- Mule version and environment settings
- Maven coordinates for application download: `MULEAPP_GROUP_ID`, `MULEAPP_ARTIFACT_ID`, `MULEAPP_VERSION`
- Repository URL: `ATINA_REPOSITORY_URL`
- Volume mount paths for persistent storage
- MySQL credentials and database name
- Port mappings

### SOTA Components (CE-Platform/_sota)

State-of-the-art component archives for offline/air-gapped installations:
- `apache-activemq-5.15.3-bin.tar.gz` (58 MB)
- `apache-maven-3.6.3-bin.tar.gz` (9.5 MB)
- `mule-standalone-4.4.0.tar.gz` (184 MB)
- `OpenJDK8U-jdk_x64_linux_hotspot_8u362b09.tar.gz` (103 MB)
- `settings.xml`: Maven settings for artifact repository access
- `docker-images/`: Docker image exports for offline deployment (see Docker Images Export section)

### Docker Images Export/Import

For offline, air-gapped, or restricted network deployments, the platform includes scripts to export and import all Docker images.

**Quick Export (Machine with Internet):**
```bash
# Windows
cd scripts\docker-images
export-images.bat

# Linux/Mac
cd scripts/docker-images
chmod +x export-images.sh
./export-images.sh
```

**Quick Import (Target Machine):**
```bash
# Windows
cd docker-images-export
import-images.bat

# Linux/Mac
cd docker-images-export
chmod +x import-images.sh
./import-images.sh
```

**Images Exported:**
- ElasticSearch, Kibana, Logstash 8.11.3
- APM Server 8.10.4
- Apache APISIX 3.7.0, APISIX Dashboard 3.0.1
- etcd v3.5.9
- Prometheus v2.48.0, Grafana 10.2.2
- Alertmanager v0.26.0, ElasticSearch Exporter v1.6.0
- Utility images (curl)

**Total Size:** ~3-4 GB uncompressed, ~2-3 GB compressed

**Use Cases:**
- Air-gapped environments (no internet access)
- Restricted networks (limited connectivity)
- Offline installations
- Backup and disaster recovery
- Consistent deployments across environments
- Integration with SOTA components for complete offline package

For complete guide, see [DOCKER_IMAGES_EXPORT.md](docs/DOCKER_IMAGES_EXPORT.md).

## Common Commands

### ELK Stack + APISIX Gateway Commands (Root Directory)

**Start/Stop Services:**
```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# Stop and remove all data (including indexed logs)
docker-compose down -v

# Check service status
docker-compose ps

# View logs
docker-compose logs -f [service-name]

# Restart services
docker-compose restart [service-name]
```

### APISIX Gateway Commands

**Access Services via APISIX:**
```bash
# All services accessible at http://localhost:9080/[service-path]
curl http://localhost:9080/kibana              # Kibana UI
curl http://localhost:9080/elasticsearch/_cluster/health?pretty
curl http://localhost:9080/api/v1/status       # Mule API (load balanced)
```

**APISIX Management:**
```bash
# Dashboard: http://localhost:9000 (admin/admin)

# View routes via Admin API
curl http://localhost:9180/apisix/admin/routes \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"

# View upstream status
curl http://localhost:9180/apisix/admin/upstreams/1 \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"

# Prometheus metrics
curl http://localhost:9091/apisix/prometheus/metrics
```

For detailed APISIX configuration, see `config/apisix/` directory and `config/scripts/setup/setup-apisix.sh`.

### Mule Application Commands

**Build and Deploy:**
```bash
cd "git/CE-MULE-4-Platform-Backend-Mule"
./01-build-and-deploy.sh    # Auto-increment version, build, and deploy to Artifactory
mvn clean package           # Manual build (without deploy)
```

For detailed Artifactory deployment instructions, see [ARTIFACTORY_DEPLOYMENT.md](docs/ARTIFACTORY_DEPLOYMENT.md).

### Docker Infrastructure Commands

**Manage Mule Platform:**
```bash
cd "git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice"
docker-compose up -d                                          # Start platform
docker-compose down                                           # Stop platform
docker-compose logs -f ce-base-mule-backend-1                 # View worker logs
docker exec ce-base-mule-backend-1 tail -f /opt/mule/mule-standalone-4.4.0/logs/mule.log
```

**Check Worker Health:**
```bash
# Via APISIX (load balanced, recommended)
curl http://localhost:9080/api/v1/status

# Direct access (internal network only)
curl http://ce-base-mule-backend-1:8081/api/v1/status
curl http://ce-base-mule-backend-2:8081/api/v1/status
```

### ElasticSearch Query Commands

**Basic Operations (via APISIX):**
```bash
# Cluster health
curl http://localhost:9080/elasticsearch/_cluster/health?pretty

# View indices
curl http://localhost:9080/elasticsearch/_cat/indices?v

# Search Mule logs
curl http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty

# Search with query
curl http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match": {"level": "ERROR"}}}'
```

**Direct Access (Internal Network Only):**
For troubleshooting when APISIX is down, access from within Docker network:
```bash
curl http://elasticsearch:9200/_cluster/health?pretty
```

### Test Logstash Connection

```bash
# Send test data via TCP
echo '{"message":"test from TCP"}' | nc localhost 5000

# Send Mule-formatted test log
echo '{"application":"test-app","environment":"dev","log_type":"mule","level":"INFO","message":"Test log"}' | nc localhost 5000

# Check Logstash API (via APISIX)
curl http://localhost:9080/logstash
```

### Log Retention Policy Commands

**Quick Setup:**
```bash
# Run with defaults (2 years retention, 1GB rollover)
./config/ilm/setup-retention-policy.sh

# Custom retention periods via environment variables
export MULE_LOGS_RETENTION_DAYS=365
export LOGSTASH_LOGS_RETENTION_DAYS=90
export ROLLOVER_SIZE=5gb
./config/ilm/setup-retention-policy.sh
```

**View Configured Policies:**
```bash
curl http://localhost:9080/elasticsearch/_ilm/policy?pretty
curl http://localhost:9080/elasticsearch/_ilm/policy/mule-logs-policy?pretty
```

**Manage via Kibana UI:**
Navigate to: http://localhost:9080/kibana → Management → Stack Management → Index Lifecycle Policies

For complete documentation, see [RETENTION_POLICY_GUIDE.md](docs/RETENTION_POLICY_GUIDE.md).

### Monitoring and Alerting Commands

**Quick Check:**
```bash
./config/monitoring/check-health.sh                # Basic health check
./config/monitoring/check-health.sh --verbose      # Detailed status
./config/monitoring/check-health.sh --watch        # Continuous monitoring
./config/monitoring/setup-monitoring.sh --status   # View monitoring config
```

**Access Dashboards:**
- Prometheus: http://localhost:9080/prometheus
- Grafana: http://localhost:9080/grafana (admin / from GRAFANA_ADMIN_PASSWORD in .env)
- Alertmanager: http://localhost:9080/alertmanager (if enabled)

For complete documentation, see [MONITORING_SETUP.md](docs/MONITORING_SETUP.md).

### Backup and Restore Commands

**Quick Backup:**
```bash
./config/backup/configure-backup.sh       # Initial setup
./config/backup/backup.sh                 # Create backup (daily mode: only today's indices)
./config/backup/restore.sh snapshot-name  # Restore from backup
./config/backup/setup-backup-cron.sh      # Enable automated backups
```

**Backup Configuration:**
```bash
# In .env file:
BACKUP_INDICES=daily              # Only today's indices (recommended)
BACKUP_RETENTION_DAYS=30          # Delete snapshots older than 30 days
BACKUP_MAX_COUNT=30               # Maximum 30 snapshots (one per day)

# Each daily snapshot is self-contained and independent
# Deleting old snapshots frees the full disk space
```

**View Snapshots:**
```bash
curl -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo/_all?pretty"
```

For complete documentation including cloud storage options, see [BACKUP_SETUP.md](docs/BACKUP_SETUP.md).

## Accessing Services

### Via APISIX Gateway (Recommended - External Access)

All HTTP/HTTPS services are accessible through the APISIX gateway for security and load balancing:

- **APISIX Dashboard**: http://localhost:9000 (admin/admin)
- **Kibana UI**: http://localhost:9080/kibana
- **Kibana APM UI**: http://localhost:9080/kibana/app/apm
- **ElasticSearch API**: http://localhost:9080/elasticsearch
- **Logstash Monitoring API**: http://localhost:9080/logstash
- **APM Server**: http://localhost:9080/apm-server
- **Mule Application API** (load balanced): http://localhost:9080/api/v1/status
- **ActiveMQ Web Console**: http://localhost:9080/activemq
- **Prometheus Metrics**: http://localhost:9091/apisix/prometheus/metrics

### Direct Access (Internal or Optional)

**Logstash Inputs (Internal-Only by Default):**
- Ports 5044 (Beats), 5000 (TCP/UDP) are internal by default for security
- To enable external access for CloudHub/external deployments, uncomment ports in `docker-compose.yml`
- HTTP monitoring API accessible via APISIX with load balancing
- For TCP/UDP load balancing across multiple instances, use external LB (HAProxy/nginx)

**APM Server (Direct + APISIX Access):**
- Direct: http://localhost:8200 (for debugging)
- Via APISIX: http://localhost:9080/apm-server (recommended)
- Internal (Mule agents): http://apm-server:8200

**MySQL Database (Direct Access):**
- MySQL Database: localhost:3306

**Internal Network Only (Not Externally Accessible):**
- ElasticSearch: http://elasticsearch:9200 (access via APISIX at /elasticsearch)
- Kibana: http://kibana:5601 (access via APISIX at /kibana)
- Logstash API: http://logstash:9600 (access via APISIX at /logstash)
- Mule Workers: http://ce-base-mule-backend-1:8081 (load balanced via APISIX at /api)
- ActiveMQ Console: http://ce-base-apachemq-backend:8161 (access via APISIX at /activemq)
- etcd: http://etcd:2379

## Logstash Pipeline Configuration

Logstash pipeline configuration is located in `config/logstash/pipeline/logstash.conf`.

**Input Plugins:**
- Beats (port 5044), TCP (port 5000), UDP (port 5000)

**Filter Plugins:**
- Mule log detection via `log_type` or `application` fields
- Index routing: Mule logs → `mule-logs-*`, others → `logstash-*`
- JSON parsing, timestamp processing, field cleanup
- Tagging: Adds `mule` tag to Mule logs

**Output Plugins:**
- ElasticSearch with daily indices: `mule-logs-YYYY.MM.dd`, `logstash-YYYY.MM.dd`
- Stdout (debugging, disable in production)

**Configuration Files:**
- `config/logstash/config/logstash.yml`: Main Logstash configuration
- `config/logstash/pipeline/logstash.conf`: Pipeline definition

To modify, edit `config/logstash/pipeline/logstash.conf` and restart: `docker-compose restart logstash`

## Data Persistence

ElasticSearch data is persisted in a Docker volume named `elasticsearch-data`. This ensures data survives container restarts. To completely reset the data, use `docker-compose down -v`.

## Log Retention Policies

ElasticSearch includes built-in Index Lifecycle Management (ILM) for automatic log retention and deletion.

**Default Retention Periods:**

| Index Pattern | Default Retention | Rollover Size | Policy Name |
|--------------|-------------------|---------------|-------------|
| `mule-logs-*` | 2 years (730 days) | 1GB | `mule-logs-policy` |
| `logstash-*` | 2 years (730 days) | 1GB | `logstash-logs-policy` |

**Quick Setup:**
```bash
./config/ilm/setup-retention-policy.sh
```

**Custom Retention:**
```bash
export MULE_LOGS_RETENTION_DAYS=365
export LOGSTASH_LOGS_RETENTION_DAYS=90
export ROLLOVER_SIZE=5gb
./config/ilm/setup-retention-policy.sh
```

**What ILM Does:**
- Automatic deletion of indices older than retention period
- Daily rollover or when reaching configured size
- Performance optimization for recent (hot) data
- Applies to all new indices via index templates

For complete documentation, see [RETENTION_POLICY_GUIDE.md](docs/RETENTION_POLICY_GUIDE.md).

### SSL/TLS Architecture

**Default Setup: SSL Termination at Gateway**

The platform uses SSL termination at the APISIX gateway for simplified SSL management:

```
External Client (HTTPS)
        ↓
  APISIX Gateway (port 9443)
  [SSL/TLS Termination]
        ↓
Internal Services (HTTP on trusted Docker network)
  - ElasticSearch
  - Kibana
  - Logstash
  - Prometheus
  - Grafana
```

**Active Certificates:**
- `certs/apisix/` - Gateway SSL termination (REQUIRED)
- `certs/apm-server/` - Direct HTTPS endpoint for CloudHub (REQUIRED)
- `certs/ca/` - Certificate Authority for signing (REQUIRED)

**Optional Certificates (certs/extra/):**
Certificates for end-to-end encryption are pre-generated and available in `certs/extra/`:
- `elasticsearch/`, `kibana/`, `logstash/`, `prometheus/`, `grafana/`, `alertmanager/`

**When to use end-to-end encryption:**
- HIPAA compliance (healthcare data)
- PCI-DSS compliance (payment card data)
- Government/military deployments
- Zero-trust network architecture

To enable, see `docs/SSL_TLS_SETUP.md` for detailed configuration.

### SSL/TLS Commands

**Generate Self-Signed Certificates (Development/Testing):**

```bash
# Generate all certificates for the stack
./config/scripts/setup/generate-certs.sh

# Generate with custom domain
./config/scripts/setup/generate-certs.sh --domain mydomain.local

# Generate with custom validity period (default: 3650 days / 10 years)
./config/scripts/setup/generate-certs.sh --days 365

# Force regeneration (overwrite existing certs)
./config/scripts/setup/generate-certs.sh --force

# Generate only CA certificate
./config/scripts/setup/generate-certs.sh --ca-only
```

**Setup Let's Encrypt (Production with Real Domain):**

```bash
# Basic setup with domain and email
./config/scripts/setup/setup-letsencrypt.sh \
  --domain yourdomain.com \
  --email admin@yourdomain.com

# Use staging server for testing (doesn't count against rate limits)
./config/scripts/setup/setup-letsencrypt.sh \
  --domain yourdomain.com \
  --email admin@yourdomain.com \
  --staging

# Use standalone mode (temporarily stops APISIX)
./config/scripts/setup/setup-letsencrypt.sh \
  --domain yourdomain.com \
  --email admin@yourdomain.com \
  --standalone

# Use webroot mode (works with running web server)
./config/scripts/setup/setup-letsencrypt.sh \
  --domain yourdomain.com \
  --email admin@yourdomain.com \
  --webroot /var/www/html
```

**Enable SSL/TLS in Configuration:**

```bash
# Edit .env file
SSL_ENABLED=true
SSL_DOMAIN=yourdomain.com

# APISIX Gateway (SSL termination)
APISIX_SSL_ENABLED=true
APISIX_FORCE_HTTPS=true  # Redirect HTTP to HTTPS

# APM Server (Direct HTTPS endpoint)
APM_SERVER_SSL_ENABLED=true

# Internal services use HTTP (no SSL configuration needed)
```

**Start Services with SSL/TLS:**

```bash
# Using SSL override file
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d

# Or set SSL_ENABLED=true in .env and restart
docker-compose restart
```

**Verify SSL/TLS Setup:**

```bash
# Test HTTPS connection to APISIX
curl -k https://localhost:9443/elasticsearch/_cluster/health

# Test with certificate verification (production)
curl --cacert certs/ca/ca.crt https://yourdomain.com:9443/elasticsearch/_cluster/health

# Check certificate details
openssl x509 -in certs/apisix/apisix.crt -text -noout

# Check certificate expiration
openssl x509 -in certs/apisix/apisix.crt -noout -dates

# Verify certificate chain
openssl verify -CAfile certs/ca/ca.crt certs/apisix/apisix.crt
```

**Certificate Renewal:**

```bash
# Manual renewal (Let's Encrypt)
./config/scripts/setup/renew-letsencrypt.sh

# Manual renewal (self-signed - regenerate)
./config/scripts/setup/generate-certs.sh --force

# Setup automatic renewal (cron)
# Add to crontab:
0 3 * * * /path/to/config/scripts/setup/renew-letsencrypt.sh >> /var/log/letsencrypt-renewal.log 2>&1
```

**View Certificate Information:**

```bash
# List all certificates
find certs/ -name "*.crt" -exec echo {} \; -exec openssl x509 -in {} -noout -subject -dates \;

# Check certificate inventory
cat certs/CERTIFICATE_INVENTORY.txt

# View Let's Encrypt info (if using Let's Encrypt)
cat certs/LETSENCRYPT_INFO.txt
```

**Test SSL/TLS Security:**

```bash
# Test SSL/TLS configuration with testssl.sh
docker run --rm -it drwetter/testssl.sh https://yourdomain.com:9443

# Test with nmap
nmap --script ssl-enum-ciphers -p 9443 yourdomain.com

# Test certificate with OpenSSL
openssl s_client -connect localhost:9443 -servername yourdomain.com
```

**Troubleshooting SSL/TLS:**

```bash
# Check if certificates exist
ls -la certs/*/

# Verify certificate permissions
find certs/ -name "*.key" -exec ls -l {} \;  # Should be 600
find certs/ -name "*.crt" -exec ls -l {} \;  # Should be 644

# Test ElasticSearch HTTPS
curl -k -u elastic:${ELASTIC_PASSWORD} https://localhost:9200/_cluster/health

# Check APISIX SSL configuration
docker-compose exec apisix cat /usr/local/apisix/conf/config.yaml | grep -A 10 ssl

# View service logs for SSL errors
docker-compose logs elasticsearch | grep -i ssl
docker-compose logs kibana | grep -i ssl
docker-compose logs apisix | grep -i ssl
```

**Common SSL/TLS Configurations:**

```bash
# Development (self-signed, 10 years validity)
./config/scripts/setup/generate-certs.sh
SSL_ENABLED=true
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d

# Production (Let's Encrypt, auto-renewal)
./config/scripts/setup/setup-letsencrypt.sh --domain prod.example.com --email ops@example.com
SSL_ENABLED=true
APISIX_FORCE_HTTPS=true
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d

# Staging (Let's Encrypt staging server for testing)
./config/scripts/setup/setup-letsencrypt.sh --domain staging.example.com --email ops@example.com --staging
SSL_ENABLED=true
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d
```

For complete SSL/TLS setup documentation, see [SSL_TLS_SETUP.md](docs/SSL_TLS_SETUP.md).

## Version Management

Current version: ElasticSearch, Logstash, and Kibana 8.11.3

To upgrade versions, update the image tags in `docker-compose.yml`. Ensure all three components (ElasticSearch, Logstash, Kibana) use the same version to avoid compatibility issues.

## Network Architecture

The platform uses Apache APISIX as the unified gateway for all services, with ELK stack and Mule platform fully integrated on a shared network infrastructure.

**Networks:**
- **ce-base-micronet**: Internal bridge network (172.42.0.0/16) with static IP assignments
- **ce-base-network**: External network for external connectivity (must be created before starting services)

**IP Address Assignments (on ce-base-micronet):**

*APISIX Gateway:*
- APISIX Gateway: 172.42.0.20 (main entry point - all external HTTP/HTTPS traffic)
- etcd: 172.42.0.21 (APISIX configuration storage)
- APISIX Dashboard: 172.42.0.22 (web UI for route management)

*ELK Stack:*
- ElasticSearch: 172.42.0.10 (internal only, access via APISIX)
- Logstash: 172.42.0.11 (internal API via APISIX, TCP/UDP ports externally accessible)
- Kibana: 172.42.0.12 (internal only, access via APISIX)
- APM Server: 172.42.0.13 (direct access + via APISIX)

*Mule Platform:*
- Mule Worker 1: 172.42.0.2 (load balanced via APISIX)
- Mule Worker 2: 172.42.0.30 (load balanced via APISIX)
- MySQL Database: 172.42.0.3 (direct access, not via APISIX)
- Maven Service: 172.42.0.4 (internal only, one-time deployment)
- ActiveMQ: 172.42.0.5 (access via APISIX for web console)
- Status Viewer: 172.42.0.6 (internal only, monitors workers)

**Traffic Flow:**
```
External Client
      ↓
APISIX Gateway (172.42.0.20:9080)
      ↓
   ┌──────────────────────────────┐
   │  Round-Robin Load Balancing  │
   └──────────────────────────────┘
      ↓                    ↓
 Mule Worker 1      Mule Worker 2
 (172.42.0.2)       (172.42.0.30)
      ↓                    ↓
   ┌──────────────────────────────┐
   │   Logstash (log shipping)    │
   │    (172.42.0.11:5000)        │
   └──────────────────────────────┘
      ↓
   ElasticSearch (172.42.0.10)
      ↓
   Kibana (172.42.0.12)
```

**Communication Patterns:**
- All services can communicate using either IP addresses or container names (e.g., `elasticsearch`, `logstash`)
- Mule workers send logs to Logstash via TCP port 5000 using the hostname `logstash`
- External HTTP/HTTPS traffic goes through APISIX gateway only
- Logstash TCP/UDP ports (5000, 5044) are directly accessible for CloudHub and external log sources
- Internal services (ElasticSearch, Kibana, Mule workers) are not directly accessible from outside the Docker network

## Mule Application Integration

This ELK stack is configured to receive and process logs from Mule applications.

**Setup Overview:**
- Mule application (`ce-mule-base`) is pre-configured with log4j2 Socket Appender in `src/main/resources/log4j2.xml`
- Logs are sent as JSON to Logstash TCP port 5000 using the hostname `logstash`
- Logstash automatically detects Mule logs and indexes them as `mule-logs-YYYY.MM.dd`
- Logs include application name, environment, correlation IDs, and standard log4j2 fields
- No additional configuration required - logs flow automatically when both stacks are running

**Configuration Files:**
- `git/CE-MULE-4-Platform-Backend-Mule/src/main/resources/log4j2.xml`: Mule application log4j2 configuration
- `config/mule/log4j2.xml`: Template log4j2 configuration for reference
- `docs/setup/08-logging-integration.md`: Complete logging setup guide (Docker and CloudHub)

**Logstash Pipeline for Mule:**
- Detects Mule logs via `log_type` or `application` fields
- Routes to separate index: `mule-logs-*` instead of `logstash-*`
- Parses log4j2 JSON format automatically
- Extracts timestamp from `timeMillis` field
- Adds `mule` tag for easy filtering

**Mule Log Fields (available in Kibana):**
- `application`, `environment`, `worker_id`, `level`, `loggerName`, `message`, `thread`, `correlationId`, `@timestamp`

**Viewing Mule Logs in Kibana:**
1. Create index pattern: `mule-logs-*`
2. Filter by application: `application:"your-app-name"`
3. Filter by worker: `worker_id:"worker-1"` (Docker) or `worker_id:"0"` (CloudHub)
4. Search by correlation ID: `correlationId:"uuid"`
5. Filter errors: `level:"ERROR"`

**Testing Integration:**
```bash
echo '{"application":"test-app","environment":"dev","log_type":"mule","level":"INFO","message":"Test log"}' | nc localhost 5000
curl http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty
```

## Complete Development Workflow

### 1. Initial Setup

Start the ELK stack:
```bash
docker-compose up -d
docker-compose ps    # Wait for all services to be healthy
```

### 2. Develop Mule Application

Navigate to Mule application:
```bash
cd "git/CE-MULE-4-Platform-Backend-Mule"
```

Make changes to Mule flows in `src/main/mule/`, update API definitions in `src/main/resources/api/ce-backend.raml`, and test locally.

### 3. Build and Deploy

Run the automated build/deploy script:
```bash
./01-build-and-deploy.sh    # Auto-increments version, commits, builds, deploys to Artifactory
git push                    # Push version commit to remote
```

### 4. Deploy to Docker Infrastructure

Navigate to Docker infrastructure:
```bash
cd "git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice"
```

Update environment variables with new version (`MULEAPP_VERSION=1.0.X`), then start/restart:
```bash
docker-compose up -d
docker-compose logs -f ce-base-mule-backend    # Monitor deployment
```

Wait for "DEPLOYED" message in logs (health check will pass when ready).

### 5. Verify Deployment

Test the API:
```bash
curl http://localhost:9080/api/v1/status    # Via APISIX (load balanced)
```

Check logs in Kibana:
1. Open http://localhost:9080/kibana
2. Go to Discover
3. Select `mule-logs-*` index pattern
4. Filter by `application:"ce-mule-base"`

Query logs via ElasticSearch:
```bash
curl http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match": {"application": "ce-mule-base"}}, "sort": [{"@timestamp": "desc"}], "size": 10}'
```

### 6. Troubleshooting

If Mule app doesn't start:
```bash
docker exec ce-base-mule-backend-1 tail -100 /opt/mule/mule-standalone-4.4.0/logs/mule.log
docker exec ce-base-mule-backend-1 ls -la /opt/mule/mule-standalone-4.4.0/apps/
docker-compose logs ce-base-maven-backend
```

If logs aren't appearing in Kibana:
```bash
docker-compose logs -f logstash
echo '{"message":"test"}' | nc localhost 5000
curl http://localhost:9080/elasticsearch/_cat/indices?v
```

## Key File Locations

**Mule Application:**
- Source code: `git/CE-MULE-4-Platform-Backend-Mule/src/main/mule/`
- API definitions: `git/CE-MULE-4-Platform-Backend-Mule/src/main/resources/api/`
- Configuration: `git/CE-MULE-4-Platform-Backend-Mule/src/main/resources/config/`
- Log4j2 config: `git/CE-MULE-4-Platform-Backend-Mule/src/main/resources/log4j2.xml`
- Build script: `git/CE-MULE-4-Platform-Backend-Mule/01-build-and-deploy.sh`
- POM: `git/CE-MULE-4-Platform-Backend-Mule/pom.xml`

**Docker Infrastructure:**
- Compose file: `git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/docker-compose.yml`
- Mule Dockerfile: `git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/docker_mulesoft/`
- Maven Dockerfile: `git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/docker_maven/`

**ELK Stack:**
- Compose file: `docker-compose.yml`
- Logstash pipeline: `logstash/pipeline/logstash.conf`
- Logstash config: `logstash/config/logstash.yml`
- Kibana setup script: `scripts/setup-kibana.sh`

**SOTA Components:**
- Location: `CE-Platform/_sota/`
- Maven settings: `CE-Platform/_sota/settings.xml`

## Security Considerations

**Security Status:**
- ✅ **X-Pack Security**: Enabled by default (authentication required for ElasticSearch and Kibana)
- ✅ **Password Management**: Secure random passwords generated via `./config/scripts/setup/generate-secrets.sh`
- ⚠️ **Transport SSL**: Disabled by default (enable for production with TLS certificates)
- ⚠️ **HTTP SSL**: Disabled by default (enable for production HTTPS)

**Production Deployment Checklist:**
- ✅ X-Pack Security is already enabled - ElasticSearch and Kibana require authentication
- ⚠️ Enable TLS encryption for transport and HTTP layers (see [SSL_TLS_SETUP.md](docs/SSL_TLS_SETUP.md))
- ⚠️ Change default passwords: APISIX admin (`admin/admin`), Grafana, ElasticSearch
- ⚠️ Change APISIX Admin API key (`edd1c9f034335f136f87ad84b625c8f1`)
- ⚠️ Secure ActiveMQ and MySQL with strong credentials
- Configure proper resource limits and memory settings
- Disable Logstash stdout output in production
- Use HTTPS for all external communications
- Enable authentication plugins in APISIX for public-facing services
- Configure firewall rules to restrict access to management interfaces
- Rotate credentials regularly and use secrets management

**Quick Security Setup:**
```bash
# Generate secure credentials
./config/scripts/setup/generate-secrets.sh

# Start services (X-Pack Security enabled automatically)
docker-compose up -d

# Access Kibana (login required)
# URL: http://localhost:9080/kibana
# Username: elastic
# Password: (from .env file - ELASTIC_PASSWORD)
```

For complete security setup details, see [SECURITY_SETUP.md](docs/SECURITY_SETUP.md).

## Important Notes

1. **Version Management**: The Mule application version in `common.properties` is independent of the Maven POM version. The build script manages `common.properties` for runtime versioning.

2. **Artifact Repository**: Requires network access to `jfrog.atina-connection.com` for deploying and downloading artifacts. Use SOTA components for offline installations. See [ARTIFACTORY_DEPLOYMENT.md](docs/ARTIFACTORY_DEPLOYMENT.md) for complete guide.

3. **Network Connectivity**: The ELK stack and Mule platform share the same Docker network (`ce-base-micronet` and `ce-base-network`). The Mule application connects to Logstash using the hostname `logstash` on port 5000. Both networks must exist before starting services.

4. **Data Persistence**: ElasticSearch data persists in Docker volumes. Use `docker-compose down -v` to completely reset logs.

5. **Kibana Data Views**: The `kibana-setup` service automatically creates data views on first startup. If they're missing, restart the service: `docker-compose restart kibana-setup`

6. **Environment Variables**: A `.env.example` file is provided with all configurable parameters. Copy to `.env` and customize as needed. Note: The current `docker-compose.yml` has some hardcoded values that can be migrated to environment variables.
