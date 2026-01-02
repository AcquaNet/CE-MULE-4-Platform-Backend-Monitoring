# Architecture Overview

This chapter explains the overall architecture of the ELK + APISIX + Mule platform.

## System Architecture

```
┌──────────────────────┐
│   External Client    │
│  (Browser, cURL,     │
│   CloudHub, etc.)    │
└──────────┬───────────┘
           │
┌──────────▼──────────────────────────────────────────────┐
│              APISIX Gateway (Port 9080)                  │
│  - Reverse Proxy                                         │
│  - Load Balancer                                         │
│  - Health Checks                                         │
│  - Centralized Access Control                            │
└──────────┬──────────────────────────────────────────────┘
           │
    ┌──────┴──────┬─────────────┬──────────────┐
    │             │             │              │
┌───▼────┐  ┌────▼─────┐  ┌───▼────────┐  ┌──▼───────┐
│Kibana  │  │  Mule    │  │ElasticSearch│  │ActiveMQ │
│:5601   │  │ Workers  │  │   :9200     │  │ :8161   │
│        │  │  (x2)    │  │             │  │         │
└────────┘  └────┬─────┘  └─────────────┘  └─────────┘
                 │
         ┌───────┴────────┐
         │                │
    ┌────▼────┐     ┌────▼────┐
    │Worker 1 │     │Worker 2 │
    │.2:8081  │     │.30:8081 │
    └─────────┘     └─────────┘
         │               │
         └───────┬───────┘
                 │
          ┌──────▼───────┐
          │  Logstash    │
          │    :5000     │
          │    :5044     │
          └──────┬───────┘
                 │
          ┌──────▼───────┐
          │ElasticSearch │
          │    :9200     │
          └──────────────┘
```

## Components

### APISIX Gateway Layer

**Purpose:** Centralized API gateway for all HTTP/HTTPS traffic

**Components:**
- **APISIX Gateway** (172.42.0.20)
  - Ports: 9080 (HTTP), 9443 (HTTPS), 9180 (Admin API), 9091 (Metrics)
  - Main entry point for all external requests
  - Reverse proxy and load balancer
  - Active health monitoring of upstream services

- **etcd** (172.42.0.21)
  - Port: 2379
  - Distributed configuration storage for APISIX
  - Stores routes, upstreams, plugins configuration

- **APISIX Dashboard** (172.42.0.22)
  - Port: 9000
  - Web UI for managing APISIX
  - Route visualization and configuration
  - Real-time monitoring

**Key Features:**
- Round-robin load balancing
- Active health checks every 30 seconds
- Automatic failover for unhealthy upstreams
- Path-based routing with URL rewriting
- CORS support for browser-based clients

### ELK Stack Layer

**Purpose:** Centralized logging and analytics

**Components:**
- **ElasticSearch** (172.42.0.10)
  - Internal port: 9200, 9300
  - External access: Via APISIX at `/elasticsearch`
  - Full-text search and analytics engine
  - Stores logs with daily indices

- **Logstash** (172.42.0.11)
  - Ports: 5000 (TCP/UDP), 5044 (Beats), 9600 (Monitoring API)
  - Data processing pipeline
  - JSON parsing and timestamp extraction
  - Routes Mule logs to `mule-logs-*` indices

- **Kibana** (172.42.0.12)
  - Internal port: 5601
  - External access: Via APISIX at `/kibana`
  - Log visualization and search interface
  - Dashboard creation and management

**Key Features:**
- Daily log rotation (`mule-logs-YYYY.MM.DD`, `logstash-YYYY.MM.DD`)
- Automatic Mule log detection and indexing
- JSON log parsing with field extraction
- Direct TCP/UDP access for CloudHub deployments

### Mule Application Layer

**Purpose:** Business logic and API implementation

**Components:**
- **Mule Worker 1** (172.42.0.2)
  - Port: 8081 (HTTP), 8082 (HTTPS)
  - Mule Runtime 4.4.0
  - Separate logs and apps volumes

- **Mule Worker 2** (172.42.0.30)
  - Port: 8081 (HTTP), 8082 (HTTPS)
  - Mule Runtime 4.4.0
  - Separate logs and apps volumes

- **Maven Service** (172.42.0.4)
  - Downloads Mule applications from artifact repository
  - Deploys to both workers' apps directories
  - Runs once on startup

- **ActiveMQ** (172.42.0.5)
  - Ports: 8161 (Web Console), 5672 (AMQP), 61616 (OpenWire)
  - Message broker for asynchronous communication

- **MySQL** (172.42.0.3)
  - Port: 3306
  - Application database

**Key Features:**
- 2-worker deployment for high availability
- Automatic application deployment via Maven
- Load balanced via APISIX round-robin
- Health checks on `/api/v1/status` endpoint
- Integrated logging to ELK stack via Logstash

## Network Architecture

### Docker Networks

**ce-base-micronet** (172.42.0.0/16):
- Static IP allocation for all services
- Internal communication between containers
- Bridge network type

**ce-base-network**:
- External connectivity
- Bridge network type

### IP Address Allocation

| Service | IP Address |
|---------|------------|
| Mule Worker 1 | 172.42.0.2 |
| MySQL | 172.42.0.3 |
| Maven Service | 172.42.0.4 |
| ActiveMQ | 172.42.0.5 |
| Status Viewer | 172.42.0.6 |
| ElasticSearch | 172.42.0.10 |
| Logstash | 172.42.0.11 |
| Kibana | 172.42.0.12 |
| APM Server | 172.42.0.13 |
| APISIX Gateway | 172.42.0.20 |
| etcd | 172.42.0.21 |
| APISIX Dashboard | 172.42.0.22 |
| Mule Worker 2 | 172.42.0.30 |

## Traffic Flow

### External HTTP Request Flow

1. **External Client** → Request to `http://your-server:9080/api/v1/status`
2. **APISIX Gateway** (172.42.0.20:9080)
   - Receives request
   - Matches route: `/api/*` → `mule-api-loadbalanced`
   - Selects upstream worker via round-robin algorithm
3. **Mule Worker** (172.42.0.2:8081 or 172.42.0.30:8081)
   - Processes request
   - Returns JSON response
   - Logs to Logstash
4. **APISIX** → Returns response to client

### Logging Flow

1. **Mule Worker** → Log event generated
2. **Log4j2 Socket Appender** → Sends JSON to Logstash:5000
3. **Logstash** → Receives, parses, enriches log data
4. **ElasticSearch** → Stores in daily index (`mule-logs-YYYY.MM.DD`)
5. **Kibana** → Visualizes and searches logs

## Security Architecture

### Production vs Development

**Development (Current):**
- Direct port exposure for debugging (9080, 9000, 5000, 5044)
- No authentication on APISIX routes
- ElasticSearch security disabled
- Default APISIX admin key
- HTTP only (no TLS)

**Production (Recommended):**
- Only expose ports 9080 (HTTP) and 9443 (HTTPS)
- Enable APISIX authentication (JWT, API Key, OAuth)
- Enable ElasticSearch security with TLS
- Rotate APISIX admin key
- Implement rate limiting
- Add IP whitelisting for Admin API
- Configure SSL/TLS certificates

### Access Control

**External Access (Production):**
- APISIX HTTP/HTTPS ports only
- Logstash TCP/UDP ports (for CloudHub)
- All other services internal only

**Internal Access:**
- Services communicate via Docker network
- Use container names or IP addresses
- No external exposure needed

## Scalability Considerations

### Horizontal Scaling

**Currently Scalable:**
- Mule workers: Add more worker containers, update APISIX upstream
- ElasticSearch: Add data nodes (requires cluster configuration)

**Fixed Components:**
- APISIX: Single instance (can be clustered with shared etcd)
- etcd: Single node (can be clustered for HA)
- Logstash: Single instance (can run multiple with input balancing)
- Kibana: Single instance (typically doesn't need scaling)

### Vertical Scaling

Adjust heap sizes in `docker-compose.yml`:
- ElasticSearch: `ES_JAVA_OPTS=-Xms512m -Xmx512m` (min: 2GB for production)
- Logstash: `LS_JAVA_OPTS=-Xms256m -Xmx256m`
- Mule workers: Update `wrapper.conf` for JVM settings

## Next Chapter

Continue to [Chapter 3: APISIX Gateway](03-apisix-gateway.md) to learn how to configure routes, load balancing, and manage the API gateway.
