# Troubleshooting Guide

Common issues and their solutions.

## APISIX Gateway Issues

### 502 Bad Gateway

**Symptoms:** APISIX returns 502 error when accessing routes

**Causes:**
- Upstream service not running
- Upstream service not healthy
- Network connectivity issue
- Incorrect route configuration

**Solutions:**

1. Check if upstream is running:
```bash
docker ps | grep mule-backend
# Should show both workers as "healthy"
```

2. Test upstream directly:
```bash
docker exec ce-base-mule-backend-1 curl http://localhost:8081/api/v1/status
```

3. Check APISIX route configuration:
```bash
curl http://localhost:9180/apisix/admin/routes/mule-api \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

4. Check APISIX logs:
```bash
docker logs apisix | tail -50
```

5. Verify network connectivity:
```bash
docker exec apisix ping ce-base-mule-backend-1
```

### Route Not Found (404)

**Symptoms:** APISIX returns 404 for configured route

**Solutions:**

1. Verify route exists:
```bash
curl http://localhost:9180/apisix/admin/routes \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" | jq
```

2. Check URI pattern matches:
```bash
# Route: "/api/*"
# Request: "/api/v1/status"  ✓ Matches
# Request: "/v1/status"      ✗ Doesn't match
```

3. Recreate route if missing (see Chapter 3).

### Health Checks Failing

**Symptoms:** Workers marked as unhealthy, requests fail intermittently

**Solutions:**

1. Check health endpoint directly:
```bash
docker exec ce-base-mule-backend-1 curl http://localhost:8081/api/v1/status
```

2. Review health check settings:
```bash
curl http://localhost:9180/apisix/admin/routes/mule-api \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" | jq '.value.upstream.checks'
```

3. Adjust health check interval if too aggressive:
```bash
# Increase interval from 30s to 60s
curl -X PATCH "http://localhost:9180/apisix/admin/routes/mule-api" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "upstream": {
      "checks": {
        "active": {
          "healthy": { "interval": 60 },
          "unhealthy": { "interval": 60 }
        }
      }
    }
  }'
```

## ELK Stack Issues

### ElasticSearch Not Starting

**Symptoms:** ElasticSearch container exits or restarts repeatedly

**Solutions:**

1. Check logs:
```bash
docker logs elasticsearch
```

2. Common issues:

**Insufficient memory:**
```bash
# Reduce heap size in docker-compose.yml
ES_JAVA_OPTS=-Xms256m -Xmx256m
```

**vm.max_map_count too low:**
```bash
# On WSL/Linux host
sudo sysctl -w vm.max_map_count=262144

# Make permanent
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
```

3. Check disk space:
```bash
df -h
```

### Logs Not Appearing in Kibana

**Symptoms:** Logs sent to Logstash but not visible in Kibana

**Solutions:**

1. Test Logstash connectivity:
```bash
echo '{"message":"test","level":"INFO"}' | nc localhost 5000
```

2. Check Logstash logs:
```bash
docker logs logstash | tail -50
```

3. Verify ElasticSearch has indices:
```bash
curl http://localhost:9080/elasticsearch/_cat/indices?v
```

4. Check Kibana index pattern:
- Navigate to Stack Management → Index Patterns
- Ensure `mule-logs-*` or `logstash-*` exists
- Refresh if needed

5. Check time range in Kibana:
- Expand to "Last 7 days" or wider
- Ensure @timestamp field is correctly parsed

### Kibana "Unable to connect to ElasticSearch"

**Solutions:**

1. Check if ElasticSearch is healthy:
```bash
curl http://localhost:9080/elasticsearch/_cluster/health
```

2. Restart Kibana:
```bash
docker-compose restart kibana
```

3. Check kibana logs:
```bash
docker logs kibana | tail -50
```

### Logstash Issues

#### Logstash Monitoring API Not Accessible via APISIX

**Symptoms:** `curl http://localhost:9080/logstash/` returns 404 or connection error

**Solutions:**

1. Verify Logstash is running and healthy:
```bash
docker ps --filter "name=logstash"
docker logs logstash | tail -30
```

2. Check APISIX route exists:
```bash
curl http://localhost:9180/apisix/admin/routes/logstash-api \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

3. Check Logstash upstream:
```bash
curl http://localhost:9180/apisix/admin/upstreams/2 \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

4. Test Logstash directly (from within Docker network):
```bash
docker exec apisix curl http://logstash:9600/
```

5. Recreate the route if missing (see Chapter 3: APISIX Gateway)

#### Logstash TCP/UDP Ports Not Accessible

**Symptoms:** Cannot send logs via TCP/UDP to ports 5000 or 5044

**Solutions:**

1. Check if ports are exposed in `docker-compose.yml`:
```bash
grep -A 5 "logstash:" docker-compose.yml | grep "ports:"
```

2. Ports are internal-only by default. To enable external access, edit `docker-compose.yml`:
```yaml
logstash:
  ports:
    - "5044:5044"      # Beats input
    - "5000:5000/tcp"  # TCP input
    - "5000:5000/udp"  # UDP input (optional)
```

3. Restart Logstash:
```bash
docker-compose restart logstash
```

4. Test TCP connection:
```bash
echo '{"message":"test"}' | nc localhost 5000
```

#### Logstash Pipeline Errors

**Symptoms:** Logs show parsing errors or pipeline failures

**Solutions:**

1. Check Logstash logs for pipeline errors:
```bash
docker logs logstash | grep -i "error\|exception"
```

2. Verify pipeline configuration:
```bash
docker exec logstash cat /usr/share/logstash/pipeline/logstash.conf
```

3. Test pipeline syntax:
```bash
docker exec logstash /usr/share/logstash/bin/logstash --config.test_and_exit -f /usr/share/logstash/pipeline/logstash.conf
```

4. Check ElasticSearch connection from Logstash:
```bash
docker exec logstash curl http://elasticsearch:9200/_cluster/health
```

#### Logstash Health Check Failing in APISIX

**Symptoms:** APISIX marks Logstash as unhealthy

**Solutions:**

1. Check Logstash health endpoint:
```bash
curl http://localhost:9080/logstash/
```

2. Verify health check configuration in upstream:
```bash
curl http://localhost:9180/apisix/admin/upstreams/2 \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" | jq '.value.checks'
```

3. Check APISIX logs for health check failures:
```bash
docker logs apisix | grep -i "logstash\|unhealthy"
```

4. Adjust health check interval if too aggressive:
```bash
curl -X PATCH "http://localhost:9180/apisix/admin/upstreams/2" \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" \
  -H "Content-Type: application/json" \
  -d '{
    "checks": {
      "active": {
        "healthy": { "interval": 60 },
        "unhealthy": { "interval": 60 }
      }
    }
  }'
```

## Mule Backend Issues

### Workers Not Starting

**Symptoms:** Mule worker containers exit or show unhealthy status

**Solutions:**

1. Check logs for errors:
```bash
docker logs ce-base-mule-backend-1 | grep ERROR
```

2. Common issues:

**Port conflict:**
```bash
# Check what's using port 8081
sudo lsof -i :8081
# or
netstat -an | grep 8081
```

**Insufficient memory:**
Edit `wrapper.conf` to reduce heap:
```properties
wrapper.java.maxmemory=1024
```

**Volume mount issues:**
```bash
# Check volume permissions
ls -la git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/volumes/worker1/
```

3. View full container logs:
```bash
docker logs --tail 100 ce-base-mule-backend-1
```

### Application Not Deploying

**Symptoms:** Worker starts but application doesn't deploy

**Solutions:**

1. Check if JAR exists in apps directory:
```bash
ls -lh git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/volumes/worker1/apps/
```

2. Check Maven service logs:
```bash
docker logs ce-base-maven-backend
```

3. Check Mule deployment logs:
```bash
docker exec ce-base-mule-backend-1 tail -f /opt/mule/mule-standalone-4.4.0/logs/mule.log
```

4. Look for deployment errors:
```bash
docker exec ce-base-mule-backend-1 grep "deployment" /opt/mule/mule-standalone-4.4.0/logs/mule.log
```

5. Manual deployment workaround:
```bash
cp git/CE-MULE-4-Platform-Backend-Mule/target/*.jar \
  git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/volumes/worker1/apps/
```

### Maven Download Failing

**Symptoms:** Maven service logs show connection errors

**Solutions:**

1. Check network connectivity to repository:
```bash
docker exec ce-base-maven-backend curl -I http://jfrog.atina-connection.com:8081
```

2. Verify Maven coordinates in `.env`:
```bash
cat git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/.env | grep MULEAPP
```

3. Test artifact exists:
```bash
# Replace with your coordinates
curl http://jfrog.atina-connection.com:8081/artifactory/libs-release/com/acqua/ce-mule-base/1.0.9/
```

4. Use manual deployment as workaround (see above).

## Network Issues

### Services Can't Communicate

**Symptoms:** Containers can't reach each other

**Solutions:**

1. Verify networks exist:
```bash
docker network ls | grep ce-base
```

2. Create if missing:
```bash
docker network create ce-base-micronet --subnet=172.42.0.0/16
docker network create ce-base-network
```

3. Check container network attachment:
```bash
docker inspect ce-base-mule-backend-1 | grep -A 10 Networks
```

4. Test connectivity:
```bash
docker exec ce-base-mule-backend-1 ping elasticsearch
docker exec apisix ping ce-base-mule-backend-1
```

### DNS Resolution Failing

**Solutions:**

1. Use IP addresses instead of hostnames temporarily
2. Restart Docker daemon (on WSL: `service docker restart`)
3. Check /etc/hosts in container:
```bash
docker exec apisix cat /etc/hosts
```

## Docker Issues

### Out of Disk Space

**Symptoms:** Containers fail to start, "no space left on device" errors

**Solutions:**

1. Check disk usage:
```bash
df -h
docker system df
```

2. Clean up:
```bash
# Remove unused containers
docker container prune

# Remove unused images
docker image prune -a

# Remove unused volumes
docker volume prune

# Nuclear option (removes everything)
docker system prune -a --volumes
```

3. Delete old ElasticSearch indices:
```bash
curl -X DELETE "http://localhost:9080/elasticsearch/mule-logs-2024*"
```

### Containers Restarting

**Symptoms:** Containers repeatedly restart

**Solutions:**

1. Check container logs:
```bash
docker logs --tail 100 container-name
```

2. Check exit code:
```bash
docker inspect container-name | grep -A 5 State
```

3. Disable restart policy temporarily:
```yaml
# In docker-compose.yml
restart: "no"
```

4. Start container manually to see error:
```bash
docker-compose up container-name
```

## Performance Issues

### Slow Response Times

**Solutions:**

1. Check APISIX metrics:
```bash
curl http://localhost:9091/apisix/prometheus/metrics | grep latency
```

2. Check ElasticSearch cluster health:
```bash
curl http://localhost:9080/elasticsearch/_cluster/health?pretty
```

3. Check Docker resource usage:
```bash
docker stats
```

4. Increase heap sizes (see Chapter 6: Configuration)

### High CPU Usage

**Solutions:**

1. Identify resource-hungry container:
```bash
docker stats --no-stream
```

2. Reduce workers or adjust resources:
```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'
```

3. Check for infinite loops in Mule flows

### Memory Issues

**Solutions:**

1. Increase Docker memory limit
2. Reduce heap sizes
3. Implement log rotation
4. Delete old ElasticSearch indices

## Getting Help

### Collect Diagnostic Information

```bash
# Container status
docker ps -a > diagnostic.txt

# All logs
docker-compose logs > logs.txt

# Network info
docker network inspect ce-base-micronet > network.txt

# APISIX routes
curl http://localhost:9180/apisix/admin/routes \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" > routes.json
```

### Useful Commands

```bash
# Restart everything
docker-compose restart

# Full reset (removes data!)
docker-compose down -v && docker-compose up -d

# View resource usage
docker stats

# Check Docker daemon
systemctl status docker      # Linux
service docker status        # WSL

# Network connectivity
docker exec container-name ping target
docker exec container-name curl http://target:port
```

## Back to Setup Guide

Return to [Setup Guide Index](../../SETUP.md) for the main documentation.
