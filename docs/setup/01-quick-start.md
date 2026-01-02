# Quick Start Guide

This guide will get you up and running with the ELK + APISIX stack in minutes.

## Prerequisites

- Docker installed and running
- Docker Compose installed
- Network ports available: 9080, 9000, 9180, 5000, 5044

## Starting the Stack

### 1. Start ELK + APISIX Gateway

```bash
cd "/mnt/c/work/Aqua/Docker ElasticSearch"
docker-compose up -d
```

This starts:
- APISIX Gateway (ports 9080, 9000, 9180)
- etcd (APISIX configuration store)
- ElasticSearch (internal only, accessed via APISIX)
- Logstash (ports 5000, 5044 for external inputs)
- Kibana (internal only, accessed via APISIX)
- APM Server (port 8200)

### 2. Verify APISIX Gateway

```bash
curl http://localhost:9080/
```

Expected output: APISIX welcome page or 404 (normal, means gateway is running)

### 3. Access Services via APISIX

| Service | URL | Credentials |
|---------|-----|-------------|
| Kibana | http://localhost:9080/kibana | None |
| ElasticSearch | http://localhost:9080/elasticsearch | None |
| APISIX Dashboard | http://localhost:9000 | admin/admin |

### 4. Test Logstash

Send a test message via TCP:

```bash
echo '{"message":"Hello from Logstash!", "level":"INFO"}' | nc localhost 5000
```

Verify in ElasticSearch:

```bash
curl http://localhost:9080/elasticsearch/logstash-*/_search?pretty
```

### 5. (Optional) Start Mule Backend

If you want to run the Mule application with 2-worker load balancing:

```bash
cd git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice
docker-compose up -d
```

Wait for both workers to become healthy (about 2-3 minutes), then test:

```bash
curl http://localhost:9080/api/v1/status
```

Expected output:
```json
{
  "status": "OK",
  "version": "1.0.9",
  "environment": "local-docker"
}
```

## Stopping the Stack

### Stop ELK + APISIX only:

```bash
cd "/mnt/c/work/Aqua/Docker ElasticSearch"
docker-compose down
```

### Stop Mule backend:

```bash
cd git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice
docker-compose down
```

### Stop everything and remove data:

```bash
cd "/mnt/c/work/Aqua/Docker ElasticSearch"
docker-compose down -v

cd git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice
docker-compose down -v
```

## Next Steps

- [Architecture Overview](02-architecture.md) - Understand the system design
- [APISIX Gateway Guide](03-apisix-gateway.md) - Configure routes and load balancing
- [ELK Stack Guide](04-elk-stack.md) - ElasticSearch, Logstash, and Kibana details
- [Mule Backend Guide](05-mule-backend.md) - Deploy and manage Mule applications

## Common Issues

**APISIX returns 502 Bad Gateway:**
- Check if upstream service is running: `docker ps`
- Check APISIX logs: `docker logs apisix`
- Verify routes are configured: See [APISIX Gateway Guide](03-apisix-gateway.md)

**Logstash not receiving data:**
- Check if Logstash is running: `docker ps | grep logstash`
- Check Logstash logs: `docker-compose logs logstash`
- Test connection: `nc -zv localhost 5000`

**Kibana not accessible:**
- Wait 30-60 seconds for all services to start
- Check if kibana-setup container completed: `docker ps -a | grep kibana-setup`
- Access directly (debug only): http://localhost:9080/kibana

For more troubleshooting, see [Chapter 7: Troubleshooting](07-troubleshooting.md).
