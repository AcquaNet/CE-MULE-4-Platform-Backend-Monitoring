# Mule Backend Deployment

This chapter covers deploying and managing the Mule 4 backend with 2-worker load balancing.

## Overview

The Mule backend runs with:
- **2 Workers**: Load balanced via APISIX
- **Maven Service**: Auto-downloads and deploys applications
- **ActiveMQ**: Message broker
- **MySQL**: Application database

## Quick Start

```bash
cd git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice
docker-compose up -d
```

Wait 2-3 minutes for workers to deploy the application, then test:
```bash
curl http://localhost:9080/api/v1/status
```

## Worker Architecture

### Worker 1
- Container: `ce-base-mule-backend-1`
- IP: 172.42.0.2:8081
- Volumes:
  - Logs: `volumes/worker1/logs`
  - Apps: `volumes/worker1/apps`

### Worker 2
- Container: `ce-base-mule-backend-2`
- IP: 172.42.0.30:8081
- Volumes:
  - Logs: `volumes/worker2/logs`
  - Apps: `volumes/worker2/apps`

## Application Deployment

### Automatic Deployment (Maven)

The Maven service automatically downloads and deploys applications from the artifact repository.

**Configuration** (`.env` file):
```bash
MULEAPP_GROUP_ID=com.acqua
MULEAPP_ARTIFACT_ID=ce-mule-base
MULEAPP_VERSION=1.0.9
ATINA_REPOSITORY_URL=http://jfrog.atina-connection.com:8081/artifactory/libs-release
```

**Process:**
1. Maven service starts after both workers are healthy
2. Downloads JAR from artifact repository
3. Copies to both workers' apps directories
4. Workers auto-deploy the application

### Manual Deployment

Copy JAR directly to worker volumes:

```bash
# Copy to Worker 1
cp your-app.jar git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/volumes/worker1/apps/

# Copy to Worker 2
cp your-app.jar git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/volumes/worker2/apps/
```

Mule auto-deploys within 5 seconds.

### Deployment Verification

Check Worker 1 logs:
```bash
docker exec ce-base-mule-backend-1 tail -f /opt/mule/mule-standalone-4.4.0/logs/mule.log
```

Look for:
```
**********************************************************************
* Started app 'your-app-name'                                        *
**********************************************************************
```

Check Worker 2:
```bash
docker exec ce-base-mule-backend-2 tail -f /opt/mule/mule-standalone-4.4.0/logs/mule.log
```

## Configuration

### Environment Variables

Location: `git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/.env`

**Key Variables:**
```bash
# Mule Runtime
muleVersion=4.4.0
mule_env=local-docker

# Application
MULEAPP_VERSION=1.0.9

# Volumes (auto-configured in project structure)
Volume_CE_base_BackendMuleLog1=.../volumes/worker1/logs
Volume_CE_base_BackendMuleApps1=.../volumes/worker1/apps
Volume_CE_base_BackendMuleLog2=.../volumes/worker2/logs
Volume_CE_base_BackendMuleApps2=.../volumes/worker2/apps
```

### Volume Structure

```
CE_Microservice/
└── volumes/
    ├── worker1/
    │   ├── logs/        ← Worker 1 Mule logs
    │   └── apps/        ← Worker 1 deployed apps
    ├── worker2/
    │   ├── logs/        ← Worker 2 Mule logs
    │   └── apps/        ← Worker 2 deployed apps
    ├── home/            ← Shared configuration
    ├── activemq-conf/   ← ActiveMQ config
    ├── activemq-data/   ← ActiveMQ data
    ├── mysql-conf/      ← MySQL config
    ├── mysql-data/      ← MySQL data
    └── maven-repo/      ← Maven cache
```

## Monitoring

### Check Worker Status

```bash
docker ps --filter "name=ce-base-mule"
```

Expected output:
```
NAMES                    STATUS
ce-base-mule-backend-1   Up 5 minutes (healthy)
ce-base-mule-backend-2   Up 5 minutes (healthy)
```

### View Worker Logs

```bash
# Worker 1
docker logs -f ce-base-mule-backend-1

# Worker 2
docker logs -f ce-base-mule-backend-2

# Both workers
docker logs -f ce-base-mule-backend-1 &
docker logs -f ce-base-mule-backend-2
```

### Test Each Worker Directly

```bash
# Worker 1 (internal)
docker exec ce-base-mule-backend-1 curl http://localhost:8081/api/v1/status

# Worker 2 (internal)
docker exec ce-base-mule-backend-2 curl http://localhost:8081/api/v1/status
```

### Load Balancing Test

```bash
# Send 20 requests through APISIX
for i in {1..20}; do
  curl -s http://localhost:9080/api/v1/status > /dev/null && echo "Request #$i: Success"
done
```

## Scaling

### Adding More Workers

1. Edit `docker-compose.yml`, add Worker 3:
```yaml
ce-base-mule-backend-3:
  image: 92455890/ce-base-mule-server:${versionMule}
  container_name: ce-base-mule-backend-3
  expose:
    - "8081"
  volumes:
    - CEBackendMuleLog3:/opt/mule/mule-standalone-${muleVersion}/logs
    - CEBackendMuleApps3:/opt/mule/mule-standalone-${muleVersion}/apps
  networks:
    ce-base-micronet:
      ipv4_address: 172.42.0.31
```

2. Update APISIX route:
```bash
curl -X PATCH "http://localhost:9180/apisix/admin/routes/mule-api" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "upstream": {
      "nodes": {
        "ce-base-mule-backend-1:8081": 100,
        "ce-base-mule-backend-2:8081": 100,
        "ce-base-mule-backend-3:8081": 100
      }
    }
  }'
```

## ActiveMQ Integration

### Access

- **Web Console**: http://localhost:9080/activemq
- **OpenWire**: localhost:61616
- **AMQP**: localhost:5672

### Configuration

Location: `CE_Microservice/docker-apache/activemq/conf/activemq.xml`

### Testing

Send message via web console or programmatically from Mule.

## MySQL Database

### Access

```bash
mysql -h 127.0.0.1 -P 3306 -u ce_user -p
# Password: ce_password (from .env)
```

### Configuration

```bash
# From .env
MYSQL_ROOT_PASSWORD=root_password
MYSQL_DATABASE=ce_backend_db
MYSQL_USER=ce_user
MYSQL_PASSWORD=ce_password
```

## Building Custom Mule Apps

### Project Structure

```
CE-MULE-4-Platform-Backend-Mule/
├── src/main/
│   ├── mule/
│   │   ├── ce-backend.xml
│   │   └── global-config.xml
│   └── resources/
│       ├── api/
│       │   └── ce-backend.raml
│       ├── config/
│       │   ├── common.properties
│       │   └── local-docker.properties
│       └── log4j2.xml
└── pom.xml
```

### Build and Deploy

```bash
cd git/CE-MULE-4-Platform-Backend-Mule

# Build
mvn clean package

# Manual deploy to both workers
cp target/ce-mule-base-*.jar \
  ../CE-MULE-4-Platform-Backend-Docker/CE_Microservice/volumes/worker1/apps/

cp target/ce-mule-base-*.jar \
  ../CE-MULE-4-Platform-Backend-Docker/CE_Microservice/volumes/worker2/apps/
```

## Troubleshooting

### Workers Not Starting

**Check logs:**
```bash
docker logs ce-base-mule-backend-1 | grep ERROR
```

**Common issues:**
- JVM memory: Adjust `wrapper.conf` heap settings
- Port conflict: Ensure 8081/8082 not in use
- Volume permissions: Check directory ownership

### Application Not Deploying

**Check Maven logs:**
```bash
docker logs ce-base-maven-backend
```

**Common issues:**
- Artifact repository unreachable
- Incorrect Maven coordinates in `.env`
- Network connectivity to JFrog

**Manual deployment workaround:**
Copy JAR directly to worker volumes (see Manual Deployment section)

### Workers Marked Unhealthy by APISIX

**Check health endpoint:**
```bash
docker exec ce-base-mule-backend-1 curl http://localhost:8081/api/v1/status
```

**Review APISIX health checks:**
```bash
curl http://localhost:9180/apisix/admin/routes/mule-api \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" | jq '.value.upstream.checks'
```

## Next Chapter

Continue to [Chapter 6: Configuration](06-configuration.md) for advanced configuration options.
