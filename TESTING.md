# Platform Testing Guide

Comprehensive testing procedures for the ELK + APISIX + Mule platform before production deployment.

---

## Table of Contents

1. [Pre-Deployment Checks](#pre-deployment-checks)
2. [Infrastructure Testing](#infrastructure-testing)
3. [Service Testing](#service-testing)
4. [Integration Testing](#integration-testing)
5. [Security Testing](#security-testing)
6. [Performance Testing](#performance-testing)
7. [Failure & Recovery Testing](#failure--recovery-testing)
8. [Production Readiness Checklist](#production-readiness-checklist)

---

## Pre-Deployment Checks

### Environment Preparation

**Check 1: System Requirements**
```bash
# Docker version (20.10+)
docker --version

# Docker Compose version (1.29+)
docker-compose --version

# Available disk space (min 10GB)
df -h

# Available memory (min 8GB recommended)
free -h
```

**Check 2: Configuration Files**
```bash
# Verify .env file exists
test -f .env && echo "✓ .env exists" || echo "✗ .env missing"

# Verify config directory structure
ls -la config/

# Verify all required directories
for dir in apisix apm-server logstash prometheus grafana alertmanager mule scripts; do
  test -d "config/$dir" && echo "✓ config/$dir exists" || echo "✗ config/$dir missing"
done
```

**Check 3: Network Prerequisites**
```bash
# Check if external network exists, create if not
docker network ls | grep ce-base-network || docker network create ce-base-network

# Verify no port conflicts
netstat -tuln | grep -E ":(9080|9443|9200|5601|8200|3306|5000)"
```

---

## Infrastructure Testing

### Test 1: Docker Compose Validation

```bash
# Validate docker-compose.yml syntax
docker-compose config

# Validate SSL override syntax
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml config

# Expected: No errors, valid YAML output
```

### Test 2: Service Startup (HTTP Mode)

```bash
# Start all services
docker-compose up -d

# Wait for services to initialize
sleep 30

# Check all services are running
docker-compose ps

# Expected: All services should be "Up" or "Up (healthy)"
```

**Verify Output:**
- ✓ elasticsearch: Up (healthy)
- ✓ kibana: Up (healthy)
- ✓ logstash: Up
- ✓ apisix: Up (healthy)
- ✓ etcd: Up
- ✓ apisix-dashboard: Up
- ✓ apm-server: Up
- ✓ prometheus: Up
- ✓ grafana: Up

### Test 3: Network Connectivity

```bash
# Check internal network
docker network inspect ce-base-micronet | grep -A 5 "Containers"

# Verify static IP assignments
docker inspect elasticsearch | grep -A 1 IPAddress | grep 172.42.0.10
docker inspect kibana | grep -A 1 IPAddress | grep 172.42.0.12
docker inspect logstash | grep -A 1 IPAddress | grep 172.42.0.11
docker inspect apisix | grep -A 1 IPAddress | grep 172.42.0.20

# Expected: All IPs match configuration
```

### Test 4: Volume Persistence

```bash
# Check volumes are created
docker volume ls | grep elasticsearch-data

# Verify volume mounts
docker inspect elasticsearch | grep -A 10 Mounts

# Expected: elasticsearch-data volume mounted
```

---

## Service Testing

### Test 5: ElasticSearch

```bash
# Basic health check
curl -s http://localhost:9080/elasticsearch/_cluster/health | jq .

# Expected output:
# {
#   "cluster_name": "docker-cluster",
#   "status": "green" or "yellow",
#   "number_of_nodes": 1
# }

# Check indices
curl -s http://localhost:9080/elasticsearch/_cat/indices?v

# Verify no errors
curl -s http://localhost:9080/elasticsearch/_cat/health
```

**Success Criteria:**
- ✓ Cluster status: green or yellow
- ✓ Number of nodes: 1
- ✓ No errors in response

### Test 6: Kibana

```bash
# Check Kibana status via APISIX
curl -s http://localhost:9080/kibana/api/status | jq '.status.overall.state'

# Expected: "green"

# Verify Kibana UI accessible
curl -I http://localhost:9080/kibana/

# Expected: HTTP 200
```

**Success Criteria:**
- ✓ Overall state: green
- ✓ UI accessible via APISIX

### Test 7: Logstash

```bash
# Check Logstash API via APISIX
curl -s http://localhost:9080/logstash/ | jq '.status'

# Expected: "green"

# Test TCP input
echo '{"test":"message","timestamp":"'$(date -Iseconds)'"}' | nc localhost 5000

# Wait for processing
sleep 5

# Verify log was indexed
curl -s "http://localhost:9080/elasticsearch/logstash-*/_search?size=1" | jq '.hits.total.value'

# Expected: At least 1 hit
```

**Success Criteria:**
- ✓ Logstash API responding
- ✓ TCP input accepting connections
- ✓ Logs indexed in ElasticSearch

### Test 8: APISIX Gateway

```bash
# Check APISIX status
curl -s http://localhost:9080/apisix/status | jq .

# Check etcd connectivity
docker exec apisix curl -s http://etcd:2379/health

# Verify routes configured
curl -s http://localhost:9180/apisix/admin/routes \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1" | jq '.list | length'

# Expected: Routes configured (count > 0)

# Test route to Kibana
curl -I http://localhost:9080/kibana/

# Test route to ElasticSearch
curl -I http://localhost:9080/elasticsearch/

# Expected: All return 200 or 302
```

**Success Criteria:**
- ✓ APISIX status endpoint responding
- ✓ etcd connection healthy
- ✓ Routes configured
- ✓ All proxied services accessible

### Test 9: APM Server

```bash
# Check APM Server health
curl -s http://localhost:8200/ | jq .

# Expected output with build_date, version

# Test via APISIX
curl -s http://localhost:9080/apm-server/ | jq .

# Send test APM data
curl -X POST http://localhost:8200/intake/v2/events \
  -H "Content-Type: application/x-ndjson" \
  -d '{"metadata":{"service":{"name":"test","version":"1.0.0"}}}
{"transaction":{"name":"test","type":"request","duration":100}}'

# Expected: HTTP 202 Accepted
```

**Success Criteria:**
- ✓ APM Server responding on port 8200
- ✓ Accessible via APISIX
- ✓ Accepting APM events

### Test 10: Prometheus

```bash
# Check Prometheus via APISIX
curl -s http://localhost:9080/prometheus/-/healthy

# Expected: Prometheus is Healthy.

# Check targets
curl -s http://localhost:9080/prometheus/api/v1/targets | jq '.data.activeTargets | length'

# Expected: At least 1 active target

# Query APISIX metrics
curl -s http://localhost:9080/prometheus/api/v1/query?query=apisix_http_status | jq .
```

**Success Criteria:**
- ✓ Prometheus healthy
- ✓ Scraping targets configured
- ✓ APISIX metrics available

### Test 11: Grafana

```bash
# Check Grafana via APISIX
curl -I http://localhost:9080/grafana/api/health

# Expected: HTTP 200

# Check datasources
curl -s http://localhost:9080/grafana/api/datasources \
  -u "admin:${GRAFANA_ADMIN_PASSWORD}" | jq 'length'

# Expected: At least 1 datasource (Prometheus)
```

**Success Criteria:**
- ✓ Grafana healthy
- ✓ Prometheus datasource configured

---

## Integration Testing

### Test 12: End-to-End Logging Flow

```bash
# Send structured log via Logstash TCP
echo '{
  "application": "test-app",
  "environment": "testing",
  "log_type": "mule",
  "level": "INFO",
  "message": "Integration test log message",
  "timestamp": "'$(date -Iseconds)'"
}' | nc localhost 5000

# Wait for processing
sleep 10

# Query ElasticSearch for the log
curl -s "http://localhost:9080/elasticsearch/mule-logs-*/_search?q=message:Integration" | jq '.hits.hits[0]._source'

# Expected: Log message found with all fields
```

**Success Criteria:**
- ✓ Log sent successfully
- ✓ Log indexed in mule-logs-* index
- ✓ All fields present and correct

### Test 13: Kibana Data Views

```bash
# Check if mule-logs data view exists
curl -s "http://localhost:9080/kibana/api/data_views" \
  -H "kbn-xsrf: true" | jq '.data_view[] | select(.name | contains("mule"))'

# Expected: mule-logs data view exists

# Check if logstash data view exists
curl -s "http://localhost:9080/kibana/api/data_views" \
  -H "kbn-xsrf: true" | jq '.data_view[] | select(.name | contains("logstash"))'

# Expected: logstash data view exists
```

**Success Criteria:**
- ✓ mule-logs-* data view exists
- ✓ logstash-* data view exists
- ✓ Both configured with @timestamp field

### Test 14: APM Integration

```bash
# Send sample transaction to APM
curl -X POST http://localhost:8200/intake/v2/events \
  -H "Content-Type: application/x-ndjson" \
  -H "Authorization: Bearer ${APM_SECRET_TOKEN}" \
  -d '{"metadata":{"service":{"name":"integration-test","version":"1.0.0","environment":"testing"}}}
{"transaction":{"id":"test-txn-001","trace_id":"test-trace-001","name":"GET /test","type":"request","duration":250,"result":"success","timestamp":'$(date +%s%N | cut -b1-16)'000}}'

# Wait for processing
sleep 10

# Check APM indices
curl -s "http://localhost:9080/elasticsearch/_cat/indices?v" | grep apm

# Query for transaction
curl -s "http://localhost:9080/elasticsearch/apm-*/_search?q=transaction.id:test-txn-001" | jq '.hits.total.value'

# Expected: Transaction found
```

**Success Criteria:**
- ✓ APM event accepted
- ✓ APM indices created
- ✓ Transaction data indexed

### Test 15: Monitoring Stack Integration

```bash
# Verify Prometheus is scraping metrics
curl -s http://localhost:9080/prometheus/api/v1/query?query=up | jq '.data.result[] | select(.metric.job == "apisix")'

# Expected: APISIX scrape target up

# Check ElasticSearch metrics
curl -s http://localhost:9080/prometheus/api/v1/query?query=elasticsearch_cluster_health_status | jq .

# Expected: Metric available

# Verify Grafana can query Prometheus
curl -s http://localhost:9080/grafana/api/datasources/proxy/1/api/v1/query?query=up \
  -u "admin:${GRAFANA_ADMIN_PASSWORD}" | jq '.data.result | length'

# Expected: Results returned
```

**Success Criteria:**
- ✓ Prometheus scraping all targets
- ✓ ElasticSearch exporter working
- ✓ Grafana can query Prometheus

---

## Security Testing

### Test 16: Network Isolation

```bash
# Verify internal services NOT directly accessible
# (Should fail if ports not exposed)

# Try direct ElasticSearch (should timeout/fail)
timeout 3 curl http://localhost:9200 2>&1 | grep -q "Connection refused\|timed out" && echo "✓ ES not directly accessible" || echo "✗ ES exposed"

# Try direct Kibana (should timeout/fail)
timeout 3 curl http://localhost:5601 2>&1 | grep -q "Connection refused\|timed out" && echo "✓ Kibana not directly accessible" || echo "✗ Kibana exposed"

# Verify services accessible ONLY via APISIX
curl -I http://localhost:9080/elasticsearch/ && echo "✓ ES accessible via APISIX"
curl -I http://localhost:9080/kibana/ && echo "✓ Kibana accessible via APISIX"
```

**Success Criteria:**
- ✓ Internal services NOT directly accessible from host
- ✓ All services accessible via APISIX gateway

### Test 17: Environment Variables Security

```bash
# Check .env is git-ignored
git check-ignore .env && echo "✓ .env is git-ignored" || echo "✗ WARNING: .env not ignored!"

# Verify no hardcoded passwords in docker-compose.yml
grep -E "password|PASSWORD" docker-compose.yml | grep -v "\${" && echo "✗ Hardcoded passwords found!" || echo "✓ No hardcoded passwords"

# Check required secrets exist
for var in ELASTIC_PASSWORD KIBANA_PASSWORD APM_SECRET_TOKEN GRAFANA_ADMIN_PASSWORD; do
  grep -q "^${var}=" .env && echo "✓ ${var} configured" || echo "✗ ${var} missing"
done
```

**Success Criteria:**
- ✓ .env is git-ignored
- ✓ No hardcoded passwords
- ✓ All required secrets configured

### Test 18: SSL/TLS Configuration (Optional)

```bash
# Test SSL certificate generation
./config/scripts/setup/generate-certs.sh --active-only --domain test.local

# Verify certificates created
test -f certs/ca/ca.crt && echo "✓ CA cert exists"
test -f certs/apisix/apisix.crt && echo "✓ APISIX cert exists"
test -f certs/apm-server/apm-server.crt && echo "✓ APM cert exists"

# Test SSL mode startup (optional - can skip for HTTP-only deployment)
# docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d
# curl -k https://localhost:9443/apisix/status
# docker-compose down
```

**Success Criteria:**
- ✓ Certificate generation script works
- ✓ All required certificates created
- ✓ (Optional) HTTPS mode starts successfully

---

## Performance Testing

### Test 19: APISIX Response Time

```bash
# Benchmark APISIX gateway
time curl -s http://localhost:9080/elasticsearch/_cluster/health > /dev/null

# Run multiple requests
for i in {1..10}; do
  curl -s -w "%{time_total}\n" -o /dev/null http://localhost:9080/elasticsearch/_cluster/health
done | awk '{sum+=$1; count++} END {print "Average:", sum/count, "seconds"}'

# Expected: Average < 0.5 seconds
```

**Success Criteria:**
- ✓ Average response time < 500ms
- ✓ No timeouts
- ✓ Consistent performance

### Test 20: Logstash Throughput

```bash
# Send 100 log messages
for i in {1..100}; do
  echo '{"application":"perf-test","level":"INFO","message":"Test message '$i'","timestamp":"'$(date -Iseconds)'"}' | nc localhost 5000
done

# Wait for processing
sleep 10

# Check all messages indexed
curl -s "http://localhost:9080/elasticsearch/logstash-*/_count?q=application:perf-test" | jq '.count'

# Expected: count >= 100
```

**Success Criteria:**
- ✓ All messages processed
- ✓ No message loss
- ✓ Processing time reasonable

### Test 21: ElasticSearch Query Performance

```bash
# Index some test data first (if not already done)
for i in {1..1000}; do
  curl -s -X POST "http://localhost:9080/elasticsearch/test-index/_doc" \
    -H "Content-Type: application/json" \
    -d '{"message":"Test document '$i'","timestamp":"'$(date -Iseconds)'"}'
done

# Query performance test
time curl -s "http://localhost:9080/elasticsearch/test-index/_search?q=message:Test" > /dev/null

# Aggregation test
time curl -s "http://localhost:9080/elasticsearch/test-index/_search" \
  -H "Content-Type: application/json" \
  -d '{"size":0,"aggs":{"by_minute":{"date_histogram":{"field":"timestamp","fixed_interval":"1m"}}}}' > /dev/null

# Expected: Both queries < 2 seconds
```

**Success Criteria:**
- ✓ Search query < 2s
- ✓ Aggregation query < 2s
- ✓ Results accurate

---

## Failure & Recovery Testing

### Test 22: Service Restart Recovery

```bash
# Restart ElasticSearch
docker-compose restart elasticsearch

# Wait for recovery
sleep 30

# Verify cluster healthy
curl -s http://localhost:9080/elasticsearch/_cluster/health | jq '.status'

# Expected: "green" or "yellow"

# Restart APISIX
docker-compose restart apisix

# Verify gateway recovers
sleep 10
curl -I http://localhost:9080/

# Expected: HTTP 200
```

**Success Criteria:**
- ✓ Services restart cleanly
- ✓ No data loss
- ✓ All routes functional after restart

### Test 23: Network Failure Simulation

```bash
# Disconnect ElasticSearch temporarily
docker network disconnect ce-base-micronet elasticsearch

# Verify Kibana handles disconnect gracefully
curl -s http://localhost:9080/kibana/api/status | jq '.status.overall.state'

# Reconnect
docker network connect ce-base-micronet elasticsearch --ip 172.42.0.10

# Wait for recovery
sleep 20

# Verify system recovered
curl -s http://localhost:9080/elasticsearch/_cluster/health | jq '.status'

# Expected: System recovers to healthy state
```

**Success Criteria:**
- ✓ Services handle network issues gracefully
- ✓ System recovers automatically
- ✓ No manual intervention needed

### Test 24: Resource Limit Testing

```bash
# Check current resource usage
docker stats --no-stream

# Verify memory limits respected
docker inspect elasticsearch | grep -A 5 Memory

# Check disk usage
df -h | grep docker

# Expected: All within limits
```

**Success Criteria:**
- ✓ Memory usage within configured limits
- ✓ No OOM (Out of Memory) kills
- ✓ Sufficient disk space available

---

## Production Readiness Checklist

### Configuration

- [ ] `.env` file created with secure passwords
- [ ] All passwords are strong (>16 characters, random)
- [ ] `.env` is git-ignored
- [ ] External network `ce-base-network` created
- [ ] SSL certificates generated (if using HTTPS)
- [ ] APISIX Admin API key changed from default
- [ ] Grafana admin password set and secured

### Services

- [ ] All services start successfully (`docker-compose ps`)
- [ ] All services pass health checks
- [ ] No errors in logs (`docker-compose logs`)
- [ ] All ports accessible as expected
- [ ] Internal services NOT directly accessible (only via APISIX)

### Logging

- [ ] Logstash accepting logs on TCP port 5000
- [ ] Logs being indexed in ElasticSearch
- [ ] Kibana data views created (`mule-logs-*`, `logstash-*`)
- [ ] Kibana UI accessible via APISIX

### Monitoring

- [ ] Prometheus scraping metrics
- [ ] Grafana dashboards accessible
- [ ] APISIX metrics available in Prometheus
- [ ] ElasticSearch metrics available in Prometheus

### Security

- [ ] No hardcoded passwords in configuration files
- [ ] All secrets in `.env` file
- [ ] `.gitignore` properly configured
- [ ] Network isolation verified
- [ ] (Optional) SSL/TLS enabled for production

### Performance

- [ ] APISIX response time < 500ms
- [ ] ElasticSearch queries < 2s
- [ ] No memory/CPU bottlenecks
- [ ] Disk space sufficient (>50% free)

### Documentation

- [ ] SETUP.md reviewed and followed
- [ ] All test cases passed
- [ ] Known issues documented
- [ ] Backup procedures tested (if applicable)

---

## Test Execution Summary

**Date:** _________________

**Tester:** _________________

**Environment:** Development / Staging / Production

### Results Summary

| Category | Tests Passed | Tests Failed | Notes |
|----------|-------------|--------------|-------|
| Pre-Deployment | __ / 3 | | |
| Infrastructure | __ / 4 | | |
| Services | __ / 7 | | |
| Integration | __ / 4 | | |
| Security | __ / 3 | | |
| Performance | __ / 3 | | |
| Failure/Recovery | __ / 3 | | |
| **TOTAL** | **__ / 27** | | |

### Issues Found

| Issue # | Description | Severity | Status |
|---------|-------------|----------|--------|
| | | | |

### Sign-Off

- [ ] All critical tests passed
- [ ] All issues resolved or documented
- [ ] Platform ready for deployment

**Approved by:** _________________

**Date:** _________________

---

**Platform Version:** 1.0
**Last Updated:** 2026-01-02
