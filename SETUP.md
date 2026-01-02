# Platform Setup Guide

Complete guide for deploying and configuring the ELK + APISIX + Mule platform.

## Platform Overview

This platform provides:
- **API Gateway**: Apache APISIX for centralized routing and load balancing
- **Logging Stack**: ElasticSearch, Logstash, and Kibana (ELK) for centralized logging
- **Application Layer**: Mule 4 runtime with 2-worker deployment for high availability
- **Message Broker**: Apache ActiveMQ for asynchronous communication
- **Database**: MySQL for application data

## Quick Start

**For experienced users:**
```bash
# Start ELK + APISIX
cd "/mnt/c/work/Aqua/Docker ElasticSearch"
docker-compose up -d

# Start Mule backend
cd git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice
docker-compose up -d

# Test
curl http://localhost:9080/api/v1/status
```

**For detailed instructions**, see [Chapter 1: Quick Start](docs/setup/01-quick-start.md).

## Table of Contents

### Core Setup

1. **[Quick Start Guide](docs/setup/01-quick-start.md)**
   - Prerequisites and requirements
   - Starting the stack
   - Verifying the installation
   - Basic testing
   - Common startup issues

2. **[Architecture Overview](docs/setup/02-architecture.md)**
   - System architecture diagram
   - Component descriptions
   - Network topology
   - IP address allocation
   - Traffic flow
   - Security architecture
   - Scalability considerations

### Component Guides

3. **[APISIX Gateway](docs/setup/03-apisix-gateway.md)**
   - Gateway configuration
   - Route management
   - Load balancing setup
   - Health check configuration
   - Plugin system
   - Security and authentication
   - Monitoring and metrics
   - Troubleshooting gateway issues

4. **[ELK Stack](docs/setup/04-elk-stack.md)**
   - ElasticSearch configuration
   - Logstash pipeline setup
   - Kibana dashboard creation
   - Index management
   - Search and query examples
   - Mule log integration
   - Data retention policies
   - Performance tuning

5. **[Mule Backend](docs/setup/05-mule-backend.md)**
   - 2-worker deployment
   - Application deployment methods
   - Maven artifact repository
   - Volume management
   - ActiveMQ integration
   - MySQL configuration
   - Building custom applications
   - Scaling workers
   - Monitoring and troubleshooting

### Advanced Topics

6. **[Configuration](docs/setup/06-configuration.md)**
   - Environment variables
   - APISIX advanced configuration
   - SSL/TLS setup
   - Production hardening
   - Resource limits
   - Performance tuning
   - High availability setup

7. **[Troubleshooting](docs/setup/07-troubleshooting.md)**
   - APISIX gateway issues
   - ELK stack problems
   - Mule backend errors
   - Network connectivity
   - Docker issues
   - Performance problems
   - Diagnostic commands
   - Getting help

8. **[Logging Integration](docs/setup/08-logging-integration.md)**
   - Logstash pipeline configuration
   - Log4j2 setup for Mule applications
   - Docker deployment (Socket appender)
   - CloudHub deployment (external connectivity)
   - Security configuration (token authentication)
   - Worker identification
   - Viewing logs in Kibana
   - Troubleshooting guide

9. **[APM Integration](docs/setup/09-apm-integration.md)**
   - APM Server setup and configuration
   - Security options (secret tokens, API keys)
   - Mule application integration
   - Docker deployment configuration
   - CloudHub deployment configuration
   - Performance metrics collection
   - Distributed tracing
   - Troubleshooting guide

### Production Operations

10. **[Security Configuration](docs/SECURITY_SETUP.md)**
   - Environment variable management
   - Credential migration from docker-compose
   - Secure password generation
   - Secret rotation
   - Production security checklist

11. **[SSL/TLS Setup](docs/SSL_TLS_SETUP.md)**
    - Self-signed certificates for development
    - Let's Encrypt for production
    - Certificate management and renewal
    - TLS configuration for all services

12. **[Backup & Restore](docs/BACKUP_SETUP.md)**
    - Automated ElasticSearch snapshots
    - Multiple storage backends (filesystem, S3, Azure, GCS)
    - Snapshot retention policies
    - Disaster recovery procedures
    - Automated backup scheduling

13. **[Index Lifecycle Management](docs/RETENTION_POLICY_GUIDE.md)**
    - Automatic log retention and deletion
    - Index rollover policies
    - Storage optimization
    - Compliance configurations

14. **[Monitoring & Alerting](docs/MONITORING_SETUP.md)**
    - Prometheus metrics collection (enabled by default)
    - Grafana dashboards
    - ElasticSearch cluster health monitoring
    - Alert configuration (email, Slack, PagerDuty)
    - Custom alert rules
    - Health check scripts

## Service Access

All services are accessible through the APISIX gateway for security and centralized management.

### External Access (via APISIX)

| Service | URL | Notes |
|---------|-----|-------|
| **APISIX Dashboard** | http://localhost:9000 | admin/admin |
| **Kibana** | http://localhost:9080/kibana | Log visualization |
| **ElasticSearch API** | http://localhost:9080/elasticsearch | REST API |
| **Logstash Monitoring API** | http://localhost:9080/logstash | Load balanced |
| **Mule API** | http://localhost:9080/api/v1/status | Load balanced |
| **ActiveMQ Console** | http://localhost:9080/activemq | Coming soon |
| **Prometheus** | http://localhost:9080/prometheus | Metrics & alerts (enabled by default) |
| **Grafana** | http://localhost:9080/grafana | Dashboards (enabled by default) |
| **Alertmanager** | http://localhost:9080/alertmanager | Alert notifications (optional) |

### Direct External Access (Bypassing APISIX)

| Service | Port | Purpose | Status |
|---------|------|---------|--------|
| **Logstash TCP** | 5000 | CloudHub log ingestion | Optional (see note below) |
| **Logstash Beats** | 5044 | Filebeat, Metricbeat | Optional (see note below) |
| **MySQL** | 3306 | Database access | Enabled |

**Note on Logstash Direct Ports:**
- By default, Logstash ports are internal-only for security
- HTTP monitoring API is accessible via APISIX: `http://localhost:9080/logstash`
- To enable direct TCP/UDP access, uncomment the ports in `docker-compose.yml`:
  ```yaml
  # Uncomment these lines for direct Logstash access:
  # ports:
  #   - "5044:5044"      # Beats input
  #   - "5000:5000/tcp"  # TCP input
  #   - "5000:5000/udp"  # UDP input (not routed via APISIX)
  ```
- For multiple Logstash instances, use an external TCP load balancer (HAProxy/nginx)

### Internal Only (Not Externally Accessible)

- ElasticSearch: 172.42.0.10:9200 (access via APISIX)
- Logstash Monitoring: 172.42.0.11:9600 (access via APISIX)
- Logstash TCP/UDP: 172.42.0.11:5000, 5044 (internal only unless ports uncommented)
- Kibana: 172.42.0.12:5601 (access via APISIX)
- Mule Worker 1: 172.42.0.2:8081 (load balanced via APISIX)
- Mule Worker 2: 172.42.0.30:8081 (load balanced via APISIX)
- ActiveMQ: 172.42.0.5:8161 (access via APISIX)

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      External Client                          │
│           (Browser, cURL, CloudHub, External Apps)            │
└───────────────┬──────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────┐
│            APISIX Gateway - Port 9080 (HTTP)                   │
│  • Reverse Proxy      • Load Balancer     • Health Checks     │
│  • Route Management   • Security          • Metrics           │
└───────────────┬───────────────────────────────────────────────┘
                │
       ┌────────┴─────────┬─────────────┬─────────────┐
       │                  │             │             │
┌──────▼──────┐   ┌──────▼──────┐  ┌──▼────────┐ ┌──▼────────┐
│   Kibana    │   │    Mule     │  │ElasticSearch│ │ ActiveMQ │
│   :5601     │   │  Workers    │  │   :9200     │ │  :8161   │
└─────────────┘   │   (x2)      │  └─────────────┘ └──────────┘
                  └──────┬──────┘
                         │
                  ┌──────┴──────┐
                  │             │
           ┌──────▼──────┐ ┌───▼──────────┐
           │  Worker 1   │ │   Worker 2   │
           │ .2:8081     │ │  .30:8081    │
           └──────┬──────┘ └───┬──────────┘
                  │            │
                  └──────┬─────┘
                         │
                  ┌──────▼──────┐
                  │  Logstash   │
                  │    :5000    │
                  └──────┬──────┘
                         │
                  ┌──────▼──────┐
                  │ElasticSearch│
                  │    :9200    │
                  └─────────────┘
```

## Technology Stack

### Infrastructure
- **Docker & Docker Compose**: Container orchestration
- **WSL2**: Windows Subsystem for Linux (development environment)

### API Gateway
- **Apache APISIX**: 3.7.0-debian
- **etcd**: 3.5.9 (APISIX configuration store)
- **APISIX Dashboard**: 3.0.1-alpine

### Logging & Monitoring
- **ElasticSearch**: 8.11.3 (search and analytics)
- **Logstash**: 8.11.3 (log processing pipeline)
- **Kibana**: 8.11.3 (visualization)
- **Elastic APM Server**: 8.10.4 (application performance monitoring)
- **Prometheus**: 2.48.0 (metrics collection - enabled by default)
- **Grafana**: 10.2.2 (visualization dashboards - enabled by default)
- **Alertmanager**: 0.26.0 (alert notifications - optional)
- **ElasticSearch Exporter**: 1.6.0 (ES metrics for Prometheus)

### Application Layer
- **Mule Runtime**: 4.4.0 (2 workers)
- **JDK**: OpenJDK 8u362
- **Apache Maven**: 3.6.3 (artifact management)
- **Apache ActiveMQ**: 5.16.2 (message broker)
- **MySQL**: Latest (application database)

## Development Environment

This platform is currently configured for **local development**:
- Security features disabled for ease of use (X-Pack Security can be enabled)
- Direct port exposure for debugging
- Verbose logging enabled
- SSL termination available at APISIX gateway (optional for development)

**For production deployment**, see [Chapter 6: Configuration](docs/setup/06-configuration.md) for hardening steps including SSL/TLS setup.

## Project Structure

```
Docker ElasticSearch/
├── SETUP.md                          ← You are here
├── docs/setup/                       ← Setup guide chapters
│   ├── 01-quick-start.md
│   ├── 02-architecture.md
│   ├── 03-apisix-gateway.md
│   ├── 04-elk-stack.md
│   ├── 05-mule-backend.md
│   ├── 06-configuration.md
│   └── 07-troubleshooting.md
├── docker-compose.yml                ← ELK + APISIX stack (HTTP)
├── docker-compose.ssl.yml            ← SSL/TLS override (HTTPS)
├── config/                           ← All configuration files
│   ├── apisix/                       ← APISIX gateway configuration
│   │   ├── config/config.yaml
│   │   └── apisix.yaml
│   ├── apisix-dashboard/             ← APISIX dashboard configuration
│   ├── apm-server/                   ← APM Server configuration
│   │   └── apm-server.yml
│   ├── logstash/                     ← Logstash configuration
│   │   ├── config/logstash.yml
│   │   └── pipeline/logstash.conf
│   ├── prometheus/                   ← Prometheus monitoring configuration
│   │   └── prometheus.yml
│   ├── grafana/                      ← Grafana dashboards configuration
│   ├── alertmanager/                 ← Alertmanager notification configuration
│   ├── mule/                         ← Mule logging templates
│   │   └── log4j2.xml
│   └── scripts/                      ← All operational scripts
│       ├── setup/                    ← Setup scripts (certs, APISIX, etc.)
│       ├── backup/                   ← Backup scripts
│       ├── monitoring/               ← Monitoring scripts
│       └── ilm/                      ← ILM scripts
├── certs/                            ← SSL/TLS certificates (git-ignored)
│   ├── ca/                           ← Certificate Authority (ACTIVE)
│   ├── apisix/                       ← APISIX gateway certs (ACTIVE)
│   ├── apm-server/                   ← APM Server certs (ACTIVE)
│   └── extra/                        ← Optional end-to-end encryption
│       ├── elasticsearch/
│       ├── kibana/
│       ├── logstash/
│       ├── prometheus/
│       ├── grafana/
│       └── alertmanager/
└── git/
    ├── CE-MULE-4-Platform-Backend-Mule/        ← Mule source code
    └── CE-MULE-4-Platform-Backend-Docker/      ← Mule deployment
        └── CE_Microservice/
            ├── docker-compose.yml              ← Mule workers
            ├── .env                            ← Configuration
            └── volumes/                        ← Persistent data
                ├── worker1/
                │   ├── logs/
                │   └── apps/
                └── worker2/
                    ├── logs/
                    └── apps/
```

## Common Commands

### Stack Management
```bash
# Start everything
cd "/mnt/c/work/Aqua/Docker ElasticSearch"
docker-compose up -d
cd git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice
docker-compose up -d

# Stop everything
docker-compose down    # (run in both directories)

# View logs
docker-compose logs -f
docker logs -f container-name

# Restart service
docker-compose restart service-name
```

### Testing
```bash
# Test APISIX gateway
curl http://localhost:9080/

# Test Mule API (load balanced)
curl http://localhost:9080/api/v1/status

# Test Logstash Monitoring API (via APISIX)
curl http://localhost:9080/logstash/

# Test Logstash TCP (requires uncommented ports in docker-compose.yml)
echo '{"message":"test"}' | nc localhost 5000

# Check ElasticSearch
curl http://localhost:9080/elasticsearch/_cluster/health?pretty
```

### Monitoring
```bash
# Container status
docker ps

# Resource usage
docker stats

# APISIX metrics
curl http://localhost:9091/apisix/prometheus/metrics
```

## Getting Started

### For First-Time Users

1. **Start here**: [Chapter 1: Quick Start](docs/setup/01-quick-start.md)
2. **Understand the system**: [Chapter 2: Architecture](docs/setup/02-architecture.md)
3. **Configure routing**: [Chapter 3: APISIX Gateway](docs/setup/03-apisix-gateway.md)
4. **View logs**: [Chapter 4: ELK Stack](docs/setup/04-elk-stack.md)

### For Experienced Users

Jump directly to:
- **APISIX configuration**: [Chapter 3](docs/setup/03-apisix-gateway.md)
- **Mule deployment**: [Chapter 5](docs/setup/05-mule-backend.md)
- **Production setup**: [Chapter 6](docs/setup/06-configuration.md)
- **Troubleshooting**: [Chapter 7](docs/setup/07-troubleshooting.md)

## Support

### Documentation

All documentation is now organized in the `docs/` directory:

**Setup Guides** (`docs/setup/`)
- 01-quick-start.md
- 02-architecture.md
- 03-apisix-gateway.md
- 04-elk-stack.md
- 05-mule-backend.md
- 06-configuration.md
- 07-troubleshooting.md
- 08-logging-integration.md
- 09-apm-integration.md

**Security & Production** (`docs/`)
- SECURITY_SETUP.md - Credential management
- SSL_TLS_SETUP.md - TLS/SSL configuration

**Monitoring & Operations** (`docs/`)
- MONITORING_SETUP.md - Prometheus and Grafana
- BACKUP_SETUP.md - Backup and restore
- RETENTION_POLICY_GUIDE.md - Log retention policies

**Deployment** (`docs/`)
- ARTIFACTORY_DEPLOYMENT.md - JFrog Artifactory setup

**Project Overview**
- `CLAUDE.md` (root directory - technical reference for Claude Code)
- `README.md` (root directory - project introduction)

### Troubleshooting

If you encounter issues:
1. Check [Chapter 7: Troubleshooting](docs/setup/07-troubleshooting.md)
2. Review container logs: `docker logs container-name`
3. Verify configuration matches this guide
4. Check network connectivity

### Updates

**Last Updated**: 2026-01-01
**Platform Version**: 1.0
**Status**: Production-Ready (Development Configuration)

## Next Steps

**Get started now:** [Chapter 1: Quick Start Guide](docs/setup/01-quick-start.md)

---

**Happy deploying!** 🚀
