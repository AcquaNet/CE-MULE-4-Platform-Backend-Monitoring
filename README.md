# ELK + APISIX + Mule Platform

A production-ready, containerized platform combining API Gateway, centralized logging, and microservices runtime with built-in high availability and load balancing.

## Architecture Overview

### System Design

This platform implements a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL TRAFFIC                              │
│              (HTTP/HTTPS, Logs, Database Connections)                │
└────────────┬────────────────────────────────┬────────────────────────┘
             │                                │
             │                                │ (Direct TCP/UDP for CloudHub)
             │                                │
┌────────────▼────────────────────────────────▼────────────────────────┐
│                      GATEWAY & INGRESS LAYER                          │
│  ┌──────────────────────────┐      ┌─────────────────────────────┐  │
│  │   APISIX API Gateway     │      │   Logstash Inputs           │  │
│  │   - Route Management     │      │   - TCP/UDP :5000           │  │
│  │   - Load Balancing       │      │   - Beats :5044             │  │
│  │   - Health Checks        │      │                             │  │
│  │   - Security             │      │                             │  │
│  └──────────┬───────────────┘      └──────────┬──────────────────┘  │
└─────────────┼──────────────────────────────────┼──────────────────────┘
              │                                  │
┌─────────────┼──────────────────────────────────┼──────────────────────┐
│             │        SERVICE LAYER             │                      │
│  ┌──────────▼────────┐  ┌──────────▼─────────┐  ┌─────────────────┐ │
│  │  Mule Workers (x2)│  │  Logstash Pipeline │  │  Web Services   │ │
│  │  - Load Balanced  │  │  - Parse & Filter  │  │  - Kibana       │ │
│  │  - Round Robin    │  │  - Enrich Logs     │  │  - ActiveMQ     │ │
│  │  - Health Checks  │  │  - Route to ES     │  │                 │ │
│  └──────────┬────────┘  └──────────┬─────────┘  └────────┬────────┘ │
└─────────────┼──────────────────────┼──────────────────────┼──────────┘
              │                      │                      │
┌─────────────┼──────────────────────┼──────────────────────┼──────────┐
│             │        DATA LAYER    │                      │          │
│  ┌──────────▼─────────┐  ┌────────▼─────────┐  ┌─────────▼────────┐ │
│  │  ActiveMQ          │  │  ElasticSearch   │  │  MySQL           │ │
│  │  - Message Queue   │  │  - Log Storage   │  │  - App Database  │ │
│  │  - Async Processing│  │  - Search Engine │  │  - Persistence   │ │
│  └────────────────────┘  └──────────────────┘  └──────────────────┘ │
└───────────────────────────────────────────────────────────────────────┘
```

### Design Principles

**1. Gateway-First Architecture**
- All HTTP/HTTPS traffic enters through APISIX API Gateway
- No direct external access to backend services (except Logstash inputs for CloudHub)
- Centralized security, routing, and load balancing

**2. High Availability**
- Multiple Mule worker instances (2+) with automatic failover
- Active health monitoring every 30 seconds
- Round-robin load distribution with unhealthy node removal

**3. Centralized Logging**
- All application logs flow through Logstash pipeline
- Automatic parsing, enrichment, and indexing
- Real-time search and visualization via Kibana

**4. Service Isolation**
- Each component runs in isolated Docker container
- Dedicated networks (internal micronet, external network)
- Volume-based persistence for stateful services

**5. Scalability**
- Horizontal scaling: Add more Mule workers as needed
- Vertical scaling: Adjust heap sizes and resource limits
- ElasticSearch can be clustered for larger deployments

### Network Topology

```
┌──────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL NETWORK                               │
│                     (Host Network Bridge)                             │
└───────┬──────────────────────────────────────────────────────────────┘
        │
        │ Exposed Ports:
        │  - 9080  (APISIX HTTP Gateway)
        │  - 9000  (APISIX Dashboard)
        │  - 9180  (APISIX Admin API)
        │  - 5000  (Logstash TCP/UDP)
        │  - 5044  (Logstash Beats)
        │  - 3306  (MySQL)
        │
┌───────▼──────────────────────────────────────────────────────────────┐
│               CE-BASE-MICRONET (172.42.0.0/16)                        │
│                   Internal Service Network                            │
│                                                                       │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ APISIX Layer    │  │  ELK Stack   │  │  Mule Platform         │  │
│  │                 │  │              │  │                        │  │
│  │ • Gateway .20   │  │ • ES .10     │  │ • Worker 1 .2          │  │
│  │ • etcd .21      │  │ • Logstash.11│  │ • Worker 2 .30         │  │
│  │ • Dashboard .22 │  │ • Kibana .12 │  │ • ActiveMQ .5          │  │
│  │                 │  │ • APM .13    │  │ • MySQL .3             │  │
│  │                 │  │              │  │ • Maven .4             │  │
│  │                 │  │              │  │ • Status .6            │  │
│  └─────────────────┘  └──────────────┘  └────────────────────────┘  │
│                                                                       │
│  Static IP Allocation:                                                │
│  • APISIX: 172.42.0.20-22                                            │
│  • ELK Stack: 172.42.0.10-13                                         │
│  • Mule Platform: 172.42.0.2-6, .30                                  │
└───────────────────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────────┐
│                     CE-BASE-NETWORK                                   │
│                   External Connectivity                               │
└───────────────────────────────────────────────────────────────────────┘
```

### Traffic Flow Patterns

#### 1. API Request Flow (Load Balanced)

```
External Client
      │
      │ HTTP Request: GET /api/v1/status
      ▼
APISIX Gateway (:9080)
      │
      │ Route matching: /api/* → mule-api-loadbalanced
      │ Load balancing: Round-robin algorithm
      │
      ├────────────────┬────────────────┐
      │                │                │
      ▼                ▼                ▼
 Worker 1         Worker 2         Worker N
(.2:8081)        (.30:8081)       (.X:8081)
      │                │                │
      │ Process Request │               │
      │ Generate Logs   │               │
      │                │                │
      └────────────────┴────────────────┘
                       │
                       │ JSON Response
                       ▼
                 APISIX Gateway
                       │
                       │ Response to Client
                       ▼
                External Client
```

#### 2. Logging Flow (All Services)

```
Application Layer
(Mule Workers, Services)
      │
      │ Log Events (JSON via Log4j2 Socket Appender)
      ▼
Logstash TCP/UDP Input (:5000)
      │
      │ JSON Parsing
      │ Field Extraction
      │ Timestamp Processing
      │ Mule Log Detection
      │
      ├─── Mule Logs ────┐
      │                  │
      ▼                  ▼
  mule-logs-*      logstash-*
  (Index)          (Index)
      │                  │
      └────────┬─────────┘
               │
               ▼
      ElasticSearch (:9200)
               │
               │ Store & Index
               ▼
          Kibana (:5601)
               │
               │ via APISIX: /kibana
               ▼
          Web Browser
```

#### 2a. APM Tracing Flow (Performance Monitoring)

```
Mule Workers
(with elastic-apm-mule4-agent)
      │
      │ APM Events (Transactions, Spans, Metrics, Errors)
      │ via Elastic APM protocol (JSON over HTTP)
      ▼
APM Server (:8200)
      │
      │ Data Enrichment
      │ Trace Correlation
      │ Metric Aggregation
      │
      ├─── Transactions ─┬─── Spans ─┬─── Metrics ─┬─── Errors ─┐
      │                  │            │             │            │
      ▼                  ▼            ▼             ▼            ▼
apm-*.transaction  apm-*.span  apm-*.metric  apm-*.error  apm-*.onboarding
      │                  │            │             │            │
      └──────────────────┴────────────┴─────────────┴────────────┘
                                      │
                                      ▼
                            ElasticSearch (:9200)
                                      │
                                      │ Store & Index
                                      ▼
                            Kibana APM UI (:5601/app/apm)
                                      │
                                      │ via APISIX: /kibana/app/apm
                                      ▼
                                 Web Browser
```

#### 3. Service Discovery Flow

```
APISIX Gateway
      │
      │ Health Check Every 30s
      │
      ├────────────────┬────────────────┐
      │                │                │
      ▼                ▼                ▼
 Worker 1         Worker 2         Worker N
      │                │                │
      │ GET /api/v1/status             │
      │                │                │
      ├────────────────┴────────────────┘
      │
      │ Response Analysis:
      │  - 200, 201, 204 → Healthy (keep in rotation)
      │  - 2 consecutive successes → Mark healthy
      │  - 429, 500, 502, 503, 504 → Unhealthy
      │  - 3 consecutive failures → Remove from rotation
      │
      ▼
etcd Configuration Store
      │
      │ Update Upstream Health Status
      ▼
APISIX Routing Table
```

### Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐   │
│  │ HTTP Traffic │  │  Log Events  │  │  Application Messages   │   │
│  │ (API Calls)  │  │  (JSON Logs) │  │  (JMS Messages)         │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬────────────────┘   │
└─────────┼──────────────────┼──────────────────┼──────────────────────┘
          │                  │                  │
┌─────────▼──────────────────▼──────────────────▼──────────────────────┐
│                      INGESTION LAYER                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐   │
│  │    APISIX    │  │   Logstash   │  │      ActiveMQ           │   │
│  │   Gateway    │  │   Pipeline   │  │   Message Broker        │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬────────────────┘   │
└─────────┼──────────────────┼──────────────────┼──────────────────────┘
          │                  │                  │
┌─────────▼──────────────────▼──────────────────▼──────────────────────┐
│                     PROCESSING LAYER                                  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Mule Workers (Application Logic)                 │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │   │
│  │  │ Worker 1 │  │ Worker 2 │  │ Worker 3 │  │ Worker N │    │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │   │
│  └────────┬─────────────┬──────────────┬──────────────┬─────────┘   │
└───────────┼─────────────┼──────────────┼──────────────┼─────────────┘
            │             │              │              │
┌───────────▼─────────────▼──────────────▼──────────────▼─────────────┐
│                       STORAGE LAYER                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐   │
│  │    MySQL     │  │ElasticSearch │  │   ActiveMQ Persistent   │   │
│  │  (Relational)│  │  (Documents) │  │   Queue Storage         │   │
│  │  App Data    │  │  Log Data    │  │   Message Data          │   │
│  └──────────────┘  └──────────────┘  └─────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────┘
```

## Container Catalog

Each container serves a specific purpose in the platform. Below is a comprehensive description of every container, organized by layer.

### Gateway & Routing Layer

#### APISIX Gateway (`apisix`)
**Image:** `apache/apisix:3.7.0-debian`
**IP:** 172.42.0.20
**Ports:** 9080 (HTTP), 9443 (HTTPS), 9180 (Admin), 9091 (Metrics), 9092 (Control)

**Purpose:**
High-performance API gateway serving as the single entry point for all HTTP/HTTPS traffic. Routes requests to appropriate backend services with load balancing and health checking.

**Key Responsibilities:**
- **Reverse Proxy**: Routes external requests to internal services based on URI patterns
- **Load Balancing**: Distributes traffic across multiple Mule workers using round-robin algorithm
- **Health Monitoring**: Actively polls upstream services every 30 seconds on `/api/v1/status` endpoint
- **Security**: Provides centralized point for authentication, authorization, and rate limiting
- **Metrics**: Exposes Prometheus-compatible metrics for monitoring
- **CORS Handling**: Manages cross-origin requests for browser-based clients

**Routes Configured:**
- `/api/*` → Mule workers (2 instances, load balanced)
- `/kibana/*` → Kibana UI (path rewriting enabled)
- `/elasticsearch/*` → ElasticSearch API (path rewriting enabled)
- `/apm-server/*` → APM Server (path rewriting enabled)
- `/logstash/*` → Logstash monitoring API (path rewriting enabled)
- `/activemq/*` → ActiveMQ web console (path rewriting enabled)

**Configuration:**
- Uses etcd for dynamic configuration storage
- No restart required for route changes
- Admin API secured with API key (default: `edd1c9f034335f136f87ad84b625c8f1`)

**Health Check Algorithm:**
- Poll interval: 30 seconds
- Healthy criteria: 2 consecutive 200/201/204 responses
- Unhealthy criteria: 3 consecutive 429/500/502/503/504 responses or timeouts
- Automatic node removal/addition based on health status

---

#### etcd (`etcd`)
**Image:** `quay.io/coreos/etcd:v3.5.9`
**IP:** 172.42.0.21
**Port:** 2379

**Purpose:**
Distributed key-value store used exclusively by APISIX for configuration persistence. Acts as the "brain" of the APISIX gateway.

**Key Responsibilities:**
- **Configuration Storage**: Stores all APISIX routes, upstreams, plugins, and services
- **Dynamic Updates**: Enables real-time configuration changes without gateway restart
- **Consistency**: Ensures all APISIX instances (if clustered) have same configuration
- **Persistence**: Maintains configuration across container restarts

**Data Stored:**
- Route definitions (URI patterns, names, plugins)
- Upstream configurations (backend nodes, weights, health checks)
- Plugin configurations (CORS, authentication, rate limiting)
- Service definitions and consumers

**Single-Node vs. Cluster:**
- Current: Single-node deployment (sufficient for development/small deployments)
- Production: Can be clustered (3+ nodes) for high availability

---

#### APISIX Dashboard (`apisix-dashboard`)
**Image:** `apache/apisix-dashboard:3.0.1-alpine`
**IP:** 172.42.0.22
**Port:** 9000

**Purpose:**
Web-based management interface for APISIX gateway. Provides visual tools for configuring routes, monitoring traffic, and managing the gateway.

**Key Responsibilities:**
- **Visual Route Management**: Create, edit, and delete routes through web UI
- **Upstream Configuration**: Manage backend service pools and load balancing
- **Plugin Management**: Enable and configure plugins (auth, rate limit, logging)
- **Monitoring Dashboard**: Real-time metrics, request rates, and error tracking
- **Testing Tools**: Test routes and upstreams directly from the UI

**Access:**
- URL: http://localhost:9000
- Default credentials: `admin` / `admin`
- Connects to APISIX via Admin API on port 9180

**Use Cases:**
- Visual route creation instead of curl commands
- Monitoring traffic patterns and error rates
- Troubleshooting routing issues
- Testing route configurations before production deployment

---

### Logging & Analytics Layer (ELK Stack)

#### ElasticSearch (`elasticsearch`)
**Image:** `docker.elastic.co/elasticsearch/elasticsearch:8.11.3`
**IP:** 172.42.0.10
**Internal Ports:** 9200 (HTTP), 9300 (Transport)
**External Access:** Via APISIX at `/elasticsearch`

**Purpose:**
Distributed search and analytics engine. Central repository for all application logs, providing real-time indexing, search, and aggregation capabilities.

**Key Responsibilities:**
- **Log Storage**: Stores all logs from Mule applications and other services
- **Full-Text Search**: Enables fast searching across millions of log entries
- **Time-Series Data**: Optimized for time-based data with daily indices
- **Aggregations**: Provides analytics (counts, averages, percentiles) on log data
- **RESTful API**: Exposes HTTP API for queries and index management

**Index Strategy:**
- Daily indices: `mule-logs-YYYY.MM.DD` for Mule application logs
- Daily indices: `logstash-YYYY.MM.DD` for general logs
- Automatic index creation by Logstash
- No automatic deletion (manual cleanup required)

**Configuration:**
- Single-node cluster (development mode)
- 512MB heap (minimum; 2GB recommended for production)
- Security disabled (xpack.security.enabled=false)
- Bootstrap memory lock enabled (prevents swapping)

**Query Capabilities:**
- Search by application, level, message, timestamp
- Filter by correlation ID for request tracing
- Aggregate error counts, response times, etc.
- Real-time updates (refresh interval: 1s)

---

#### Logstash (`logstash`)
**Image:** `docker.elastic.co/logstash/logstash:8.11.3`
**IP:** 172.42.0.11
**Internal Ports:** 5000 (TCP/UDP), 5044 (Beats), 9600 (Monitoring API)
**External Access:** Monitoring API via APISIX at `/logstash` (load balanced)

**Purpose:**
Data processing pipeline that ingests logs from multiple sources, parses and enriches them, then forwards to ElasticSearch. Acts as the "ETL" layer for logs. Routed through APISIX for load balancing and centralized management.

**Key Responsibilities:**
- **Log Ingestion**: Receives logs via TCP, UDP, and Beats protocol (internal-only by default)
- **JSON Parsing**: Parses JSON-formatted logs and extracts fields
- **Mule Log Detection**: Automatically identifies Mule logs via `log_type` or `application` field
- **Timestamp Processing**: Converts log4j2 `timeMillis` to ElasticSearch `@timestamp`
- **Index Routing**: Routes Mule logs to `mule-logs-*`, others to `logstash-*`
- **Field Cleanup**: Removes unnecessary log4j2 fields (timeMillis, endOfBatch)
- **Health Monitoring**: Provides monitoring API for APISIX health checks

**Input Sources:**
- **TCP (5000)**: CloudHub deployments, external Mule runtimes (internal-only; see config)
- **UDP (5000)**: High-throughput log shipping (internal-only; see config)
- **Beats (5044)**: Filebeat, Metricbeat, other Elastic Beats (internal-only; see config)

**Access Methods:**
- **Monitoring API (via APISIX)**: `http://localhost:9080/logstash/` (recommended, load balanced)
- **TCP/UDP Inputs**: Internal-only by default; uncomment ports in docker-compose.yml for external access
- **Scaling**: Supports multiple instances via APISIX upstream load balancing

**Pipeline Processing:**
1. **Input**: Receive log event
2. **Filter**: Detect log type, parse JSON, extract timestamp
3. **Mutate**: Add tags, set index metadata, clean fields
4. **Output**: Send to ElasticSearch with appropriate index name

**Configuration:**
- Upstream ID: `2` (logstash-monitoring)
- Health checks: Active HTTP checks every 30s on `/` endpoint
- Load balancing: Round-robin across multiple instances
- TCP/UDP load balancing: Use external LB (HAProxy/nginx) for production

**Performance:**
- 256MB heap (default; increase for high volume)
- Batch processing (125 events per batch)
- Persistent queue for reliability (optional)

---

#### Kibana (`kibana`)
**Image:** `docker.elastic.co/kibana/kibana:8.11.3`
**IP:** 172.42.0.12
**Internal Port:** 5601
**External Access:** Via APISIX at `/kibana`

**Purpose:**
Web-based visualization and exploration tool for ElasticSearch data. Provides dashboards, search interfaces, and analytics for logs.

**Key Responsibilities:**
- **Log Search**: Discover interface for searching and filtering logs
- **Visualizations**: Create charts, graphs, and tables from log data
- **Dashboards**: Combine multiple visualizations into monitoring dashboards
- **Index Management**: Create and manage index patterns
- **Alerting**: Set up alerts based on log patterns (requires x-pack)

**Features:**
- **Discover**: Real-time log search with filters and field analysis
- **Visualize**: Create pie charts, line graphs, heat maps, etc.
- **Dashboard**: Combine visualizations for comprehensive monitoring
- **Dev Tools**: Console for testing ElasticSearch queries

**Index Patterns:**
- `mule-logs-*`: Mule application logs
- `logstash-*`: General system logs

**Common Use Cases:**
- Search for error logs in last 24 hours
- View request volume over time
- Analyze error distribution by application
- Trace specific requests via correlation ID
- Monitor application health trends

---

#### APM Server (`apm-server`)
**Image:** `docker.elastic.co/apm/apm-server:8.10.4`
**IP:** 172.42.0.13
**Port:** 8200
**External Access:** Via APISIX at `/apm-server` and Direct at `:8200`

**Purpose:**
Application Performance Monitoring server that collects distributed tracing data, performance metrics, and error tracking from Mule applications and other services.

**Key Responsibilities:**
- **Trace Collection**: Receives distributed tracing data from APM agents (elastic-apm-mule4-agent)
- **Performance Metrics**: Collects transaction times, span durations, throughput, error rates
- **Error Tracking**: Captures application exceptions with full stack traces
- **Service Maps**: Builds dependency maps showing service interactions and call paths
- **JVM Metrics**: Monitors heap usage, GC activity, thread counts from Mule workers
- **Data Transformation**: Enriches and transforms APM data before sending to ElasticSearch

**Mule Integration:**
- **Agent**: Uses `elastic-apm-mule4-agent` v0.4.0 (wraps elastic-apm-agent 1.17.0)
- **Configuration**: Mule workers configured with JAVA_OPTS pointing to `http://apm-server:8200`
- **Service Names**: `ce-mule-base-worker-1` and `ce-mule-base-worker-2`
- **Sampling**: 100% transaction sampling rate (configurable for production)
- **Instrumentation**: Automatic flow tracing via Mule notification listeners

**Access Methods:**
- **Internal (Agents)**: `http://apm-server:8200` - Used by Mule APM agents
- **External (APISIX)**: `http://localhost:9080/apm-server` - For debugging and testing
- **Direct**: `http://localhost:8200` - Debug access from host

**Data Storage:**
- Stores APM data in ElasticSearch indices:
  - `apm-8.10.4-transaction-*`: Transaction events (API calls, flows)
  - `apm-8.10.4-span-*`: Span events (flow steps, components)
  - `apm-8.10.4-metric-*`: JVM and application metrics
  - `apm-8.10.4-error-*`: Exception and error events

**Kibana APM UI:**
- **URL**: `http://localhost:9080/kibana/app/apm`
- **Features**:
  - Transaction overview and detailed traces
  - Service dependency maps
  - Error tracking and grouping
  - JVM metrics dashboard
  - Performance trend analysis

**Configuration:**
- **Version**: 8.10.4 (compatible with elastic-apm-agent 1.17.0)
- **Authentication**: Anonymous enabled (development only)
- **RUM**: Disabled (backend monitoring only)
- **Kibana Integration**: Enabled for APM UI setup
- **Output**: Direct to ElasticSearch at `http://elasticsearch:9200`

**Deployment Requirements:**
1. Add `mule4-agent` dependency to Mule application POM
2. Import `tracer.xml` in Mule global configuration
3. Configure JAVA_OPTS with APM Server URL and service name
4. Rebuild and redeploy Mule application

**Use Cases:**
- **Performance Monitoring**: Track Mule flow execution times and identify bottlenecks
- **Distributed Tracing**: Trace requests across multiple Mule flows and external services
- **Error Analysis**: Capture and analyze exceptions with context
- **Capacity Planning**: Monitor JVM metrics to optimize heap and thread allocation
- **SLA Monitoring**: Track response times and error rates for SLA compliance
- **Dependency Mapping**: Visualize service interactions and identify integration points

**Production Recommendations:**
- Reduce sampling rate: `elastic.apm.transaction_sample_rate=0.1` (10%)
- Enable API key authentication
- Add TLS/HTTPS encryption
- Implement retention policies for APM indices
- Monitor APM Server performance and resource usage

---

### Application Runtime Layer (Mule Platform)

#### Mule Worker 1 (`ce-base-mule-backend-1`)
**Image:** `92455890/ce-base-mule-server:4.4.0`
**IP:** 172.42.0.2
**Internal Ports:** 8081 (HTTP), 8082 (HTTPS)

**Purpose:**
Primary Mule runtime instance running the backend application. Processes API requests in a load-balanced pool managed by APISIX.

**Key Responsibilities:**
- **API Execution**: Runs Mule flows defined in deployed applications
- **Request Processing**: Handles business logic for incoming requests
- **Integration**: Connects to databases, message queues, external APIs
- **Log Generation**: Sends structured JSON logs to Logstash via TCP socket
- **Health Reporting**: Exposes `/api/v1/status` for health checks

**Runtime Configuration:**
- Mule Runtime: 4.4.0
- JDK: OpenJDK 8u362
- Environment: `local-docker`
- Heap: Configured in wrapper.conf

**Volumes:**
- Logs: `volumes/worker1/logs/` (mule.log, application logs)
- Apps: `volumes/worker1/apps/` (deployed .jar files)
- Shared: `volumes/home/` (configuration, shared resources)

**Application Deployment:**
- Auto-deployment from `apps/` directory
- Hot deployment (no restart required)
- Deployment detected via anchor file creation

**Logging Integration:**
- Log4j2 Socket Appender sends to `logstash:5000`
- JSON format with application name, environment, level
- Includes correlation IDs for request tracing

**APM Integration:**
- Elastic APM agent sends traces to `apm-server:8200`
- Automatic instrumentation via `tracer.xml` import
- Configured via JAVA_OPTS environment variables
- Service name: `ce-mule-base-worker-1`

---

#### Mule Worker 2 (`ce-base-mule-backend-2`)
**Image:** `92455890/ce-base-mule-server:4.4.0`
**IP:** 172.42.0.30
**Internal Ports:** 8081 (HTTP), 8082 (HTTPS)

**Purpose:**
Secondary Mule runtime instance, identical to Worker 1. Provides high availability and load distribution.

**Key Responsibilities:**
- Identical to Worker 1 (see above)
- Shares load with Worker 1 via APISIX round-robin
- Automatic failover if Worker 1 fails health checks
- Independent logs and deployment directory

**APM Integration:**
- Elastic APM agent sends traces to `apm-server:8200`
- Service name: `ce-mule-base-worker-2`
- Independent APM service tracking in Kibana

**Volumes:**
- Logs: `volumes/worker2/logs/`
- Apps: `volumes/worker2/apps/`
- Shared: `volumes/home/`

**Scaling:**
- Additional workers (Worker 3, 4, etc.) can be added
- Each worker needs unique IP and volume directories
- APISIX upstream configuration updated to include new workers
- Equal weight distribution (100 each) by default

---

#### Maven Service (`ce-base-maven-backend`)
**Image:** `92455890/ce-base-maven-backend-server:3.6.3`
**IP:** 172.42.0.4
**No External Ports**

**Purpose:**
One-time deployment service that downloads Mule application JARs from artifact repository and deploys them to all worker instances.

**Key Responsibilities:**
- **Artifact Download**: Fetches Mule applications from JFrog Artifactory
- **Multi-Worker Deployment**: Copies application to both worker1 and worker2 apps directories
- **Dependency Management**: Uses Maven to resolve and download artifacts
- **Repository Caching**: Maintains local Maven repository to speed up deployments

**Process:**
1. Waits for both Mule workers to be healthy
2. Reads Maven coordinates from environment variables:
   - `MULEAPP_GROUP_ID`: com.acqua
   - `MULEAPP_ARTIFACT_ID`: ce-mule-base
   - `MULEAPP_VERSION`: 1.0.9
3. Downloads JAR from `ATINA_REPOSITORY_URL`
4. Copies JAR to `/home/apps/worker1/` and `/home/apps/worker2/`
5. Workers auto-detect and deploy the application
6. Container exits (restart policy: no)

**Volumes:**
- Worker 1 Apps: `/home/apps/worker1`
- Worker 2 Apps: `/home/apps/worker2`
- Maven Cache: `/home/repository`

**Configuration:**
- Uses settings.xml with repository credentials
- Supports both release and snapshot repositories

---

#### Status Viewer (`ce-base-status-viewer-backend`)
**Image:** `92455890/ce-base-status-viewer-backend-server:1.0`
**IP:** 172.42.0.6
**No External Ports**

**Purpose:**
Monitoring service that periodically polls both Mule workers' health endpoints and reports status.

**Key Responsibilities:**
- **Health Polling**: Regularly checks `/api/v1/status` on both workers
- **Status Aggregation**: Combines health status from all workers
- **Monitoring**: Can be used for external health check integrations

**Configuration:**
- `API_STATUS_URL`: http://ce-base-mule-backend-1:8081/api/v1/status
- Polls both workers independently
- Lightweight Alpine-based container

---

### Message & Data Layer

#### ActiveMQ (`ce-base-apachemq-backend`)
**Image:** `92455890/ce-base-apachemq-backend:5.15.3`
**IP:** 172.42.0.5
**Ports:** 8161 (Web Console), 5672 (AMQP), 61616 (OpenWire)

**Purpose:**
JMS message broker providing asynchronous message queuing and pub/sub capabilities for Mule applications.

**Key Responsibilities:**
- **Message Queuing**: Point-to-point messaging between services
- **Publish/Subscribe**: Topic-based message distribution
- **Reliable Delivery**: Persistent message storage
- **Protocol Support**: JMS, AMQP, STOMP, MQTT, OpenWire
- **Web Console**: Management UI for queues, topics, connections

**Use Cases:**
- Asynchronous processing (order processing, email sending)
- Event-driven architecture (publish events to multiple subscribers)
- Decoupling services (producer doesn't wait for consumer)
- Reliable message delivery (survives restarts)

**Configuration:**
- Volumes for persistent storage (conf, data)
- Shared with both Mule workers
- Web console accessible via APISIX (planned)

**Protocols:**
- **OpenWire (61616)**: Native ActiveMQ protocol (fastest)
- **AMQP (5672)**: Standard protocol for interoperability
- **STOMP**: Simple text-based protocol

---

#### MySQL (`ce-base-db-backend`)
**Image:** `mysql:latest`
**IP:** 172.42.0.3
**Port:** 3306 (Direct external access)

**Purpose:**
Relational database for persistent storage of application data. Shared by both Mule workers.

**Key Responsibilities:**
- **Data Persistence**: Store application entities (users, orders, etc.)
- **Transactional Support**: ACID guarantees for data consistency
- **SQL Queries**: Complex queries and joins
- **Backup/Restore**: Database dump and restore capabilities

**Configuration:**
- Database: `ce_backend_db`
- User: `ce_user`
- Password: `ce_password` (from .env)
- Root password: `root_password`

**Volumes:**
- Config: `volumes/mysql-conf/`
- Data: `volumes/mysql-data/`

**Access:**
- Direct: `mysql -h 127.0.0.1 -P 3306 -u ce_user -p`
- From Mule workers: `ce-base-db-backend:3306`

**Use Cases:**
- Store user accounts, customer data
- Order processing and inventory
- Application configuration
- Audit logs and transaction history

---

### Support Services

#### Kibana Setup (`kibana-setup`)
**Image:** `curlimages/curl:latest`
**No IP (One-time container)**

**Purpose:**
Initialization container that automatically creates Kibana index patterns on first deployment.

**Process:**
1. Waits for Kibana to be healthy
2. Creates index pattern for `mule-logs-*`
3. Creates index pattern for `logstash-*`
4. Sets default time field to `@timestamp`
5. Exits (restart policy: on-failure)

**Why Needed:**
Without index patterns, Kibana can't access log data. This automates the manual setup step.

---

#### APISIX Setup (`apisix-setup`)
**Image:** `curlimages/curl:latest`
**No IP (One-time container)**

**Purpose:**
Initialization container that configures APISIX routes via Admin API on first deployment.

**Process:**
1. Waits for APISIX to be healthy
2. Creates routes for Kibana, ElasticSearch, Mule API
3. Configures load balancing and health checks
4. Exits (restart policy: on-failure)

**Note:**
Currently has line-ending issues. Manual route configuration via `config/scripts/setup/configure-apisix-routes.sh` is recommended.

---

## Platform Capabilities

### High Availability Features

1. **Load Balancing**
   - Round-robin distribution across Mule workers
   - Equal weight allocation (customizable)
   - Automatic traffic rerouting on worker failure

2. **Health Monitoring**
   - Active HTTP health checks every 30 seconds
   - Configurable healthy/unhealthy thresholds
   - Automatic node addition/removal from pool

3. **Failover**
   - Unhealthy workers removed from rotation automatically
   - No manual intervention required
   - Traffic continues on healthy workers

4. **Scalability**
   - Add workers dynamically
   - Update APISIX configuration without restart
   - Horizontal scaling for Mule, ElasticSearch, Logstash

### Observability Features

1. **Centralized Logging**
   - All logs in single ElasticSearch cluster
   - Structured JSON logs with consistent fields
   - Real-time search and analysis

2. **Distributed Tracing**
   - Correlation IDs across all services
   - Request flow tracking through logs
   - APM server for detailed tracing

3. **Metrics**
   - Prometheus metrics from APISIX
   - Request rates, error rates, latency
   - Custom metrics from Mule applications

4. **Dashboards**
   - Kibana for log visualization
   - APISIX Dashboard for gateway metrics
   - Custom dashboards for business KPIs

### Security Features

1. **Gateway Security**
   - Centralized entry point (single attack surface)
   - Plugin-based authentication (JWT, OAuth, API Key)
   - Rate limiting and IP whitelisting

2. **Network Isolation**
   - Internal services not directly accessible
   - Dedicated Docker networks
   - Static IP allocation

3. **SSL/TLS Encryption**
   - SSL termination at APISIX gateway (port 9443)
   - HTTPS for APM Server (direct CloudHub connections)
   - Internal services use HTTP on trusted network
   - Optional end-to-end encryption (certs in `certs/extra/` for HIPAA/PCI-DSS)

4. **Configuration Security**
   - etcd for secure config storage
   - Admin API key protection
   - Environment-based secrets (via .env)

## Technology Stack Summary

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| **Gateway** | Apache APISIX | 3.7.0 | API Gateway, Load Balancer |
| **Config Store** | etcd | 3.5.9 | APISIX Configuration |
| **Search** | ElasticSearch | 8.11.3 | Log Storage & Search |
| **Pipeline** | Logstash | 8.11.3 | Log Processing |
| **Visualization** | Kibana | 8.11.3 | Log Analysis UI |
| **APM** | Elastic APM | 8.10.4 | Application Monitoring |
| **Runtime** | Mule Runtime | 4.4.0 | Integration Platform |
| **JDK** | OpenJDK | 8u362 | Java Runtime |
| **Message Broker** | ActiveMQ | 5.16.2 | Async Messaging |
| **Database** | MySQL | Latest | Data Persistence |
| **Build Tool** | Maven | 3.6.3 | Dependency Management |
| **Container** | Docker | - | Containerization |
| **Orchestration** | Docker Compose | - | Multi-container Management |

## Quick Reference

### Port Mapping

| Port | Service | Purpose | Status |
|------|---------|---------|--------|
| 9080 | APISIX Gateway | Main HTTP entry point | Active |
| 9000 | APISIX Dashboard | Gateway management UI | Active |
| 9180 | APISIX Admin API | Route configuration | Active |
| 9091 | APISIX Metrics | Prometheus metrics | Active |
| 5000 | Logstash | TCP/UDP log input | Internal (optional) |
| 5044 | Logstash | Beats protocol | Internal (optional) |
| 3306 | MySQL | Database access | Active |
| 8200 | APM Server | APM data ingestion (direct) | Active |

**Note**: Logstash TCP/UDP ports (5000, 5044) are internal-only by default for security. HTTP monitoring API accessible via APISIX at `/logstash`. To enable direct TCP/UDP access, uncomment ports in `docker-compose.yml`.

### Container Health Status

Check all containers:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Expected healthy state:
```
NAMES                        STATUS
apisix                       Up (healthy)
etcd                         Up (healthy)
apisix-dashboard             Up (healthy)
elasticsearch                Up (healthy)
logstash                     Up (healthy)
kibana                       Up (healthy)
apm-server                   Up (healthy)
ce-base-mule-backend-1       Up (healthy)
ce-base-mule-backend-2       Up (healthy)
ce-base-apachemq-backend     Up
ce-base-db-backend           Up
```

### Key URLs

- **APISIX Dashboard**: http://localhost:9000 (admin/admin)
- **Kibana**: http://localhost:9080/kibana
- **Kibana APM**: http://localhost:9080/kibana/app/apm
- **Mule API**: http://localhost:9080/api/v1/status
- **ElasticSearch**: http://localhost:9080/elasticsearch/_cluster/health
- **APM Server**: http://localhost:9080/apm-server (or http://localhost:8200 direct)
- **Logstash API**: http://localhost:9080/logstash

## Getting Started

For detailed setup instructions, see [SETUP.md](SETUP.md) which contains:
- Quick start guide
- Detailed architecture documentation
- Configuration guides
- Troubleshooting steps

## Documentation

- **[SETUP.md](SETUP.md)** - Complete setup and deployment guide
- **[CLAUDE.md](CLAUDE.md)** - Detailed project overview for Claude Code
- **[docs/setup/08-logging-integration.md](docs/setup/08-logging-integration.md)** - Mule logging with ELK stack
- **[docs/setup/09-apm-integration.md](docs/setup/09-apm-integration.md)** - Application Performance Monitoring

## Platform Status

**Version**: 1.0
**Last Updated**: 2025-12-26
**Status**: ✅ Production-Ready (Development Configuration)

**What's Working**:
- ✅ APISIX Gateway with 2-worker load balancing
- ✅ ELK Stack with centralized logging
- ✅ APM Server with Mule integration for performance monitoring
- ✅ Mule 4 runtime with auto-deployment
- ✅ Active health checks and failover
- ✅ Structured logging with correlation IDs
- ✅ Distributed tracing via Elastic APM
