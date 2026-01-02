# Advanced Configuration

This chapter covers advanced configuration options for production deployments.

## Environment Configuration

### ELK Stack (.env.example)

Location: `/mnt/c/work/Aqua/Docker ElasticSearch/.env.example`

```bash
# ElasticSearch
ES_VERSION=8.11.3
ES_PORT=9200
ES_HEAP_SIZE=512m              # Production: 2g minimum

# Logstash
LOGSTASH_VERSION=8.11.3
LOGSTASH_PORT=5000
LOGSTASH_HEAP_SIZE=256m        # Production: 512m-1g

# Kibana
KIBANA_VERSION=8.11.3
KIBANA_PORT=5601

# Security (enable for production!)
XPACK_SECURITY_ENABLED=false
```

### Mule Backend (.env)

Location: `git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/.env`

```bash
# Mule Runtime
muleVersion=4.4.0
mule_env=local-docker           # Options: local-docker, dev, qa, prod

# Application
MULEAPP_VERSION=1.0.9

# Repository
ATINA_REPOSITORY_URL=http://jfrog.atina-connection.com:8081/artifactory/libs-release

# Database
MYSQL_DATABASE=ce_backend_db
MYSQL_USER=ce_user
MYSQL_PASSWORD=ce_password
```

## APISIX Configuration

### Main Configuration

Location: `apisix-config/config/config.yaml`

```yaml
deployment:
  role: traditional
  role_traditional:
    config_provider: etcd
  admin:
    admin_key:
      - name: "admin"
        key: edd1c9f034335f136f87ad84b625c8f1  # CHANGE IN PRODUCTION!

  etcd:
    host:
      - "http://etcd:2379"
    prefix: "/apisix"
    timeout: 30

nginx_config:
  http:
    proxy_connect_timeout: 60s
    proxy_send_timeout: 60s
    proxy_read_timeout: 60s
    client_max_body_size: 50m
```

### SSL/TLS Configuration

1. Generate or obtain SSL certificate
2. Mount certificate in docker-compose.yml:
```yaml
apisix:
  volumes:
    - ./certs/cert.pem:/usr/local/apisix/conf/cert/cert.pem
    - ./certs/key.pem:/usr/local/apisix/conf/cert/key.pem
```

3. Configure HTTPS in config.yaml:
```yaml
nginx_config:
  http:
    ssl:
      ssl_protocols: TLSv1.2 TLSv1.3
      ssl_ciphers: HIGH:!aNULL:!MD5
```

## Production Hardening

### Security Checklist

**APISIX:**
- [ ] Change admin API key
- [ ] Enable HTTPS/TLS
- [ ] Restrict Admin API to internal network
- [ ] Enable authentication on routes (JWT/API Key)
- [ ] Implement rate limiting
- [ ] Add IP whitelisting for sensitive endpoints

**ELK Stack:**
- [ ] Enable ElasticSearch security (xpack)
- [ ] Configure TLS for ElasticSearch
- [ ] Set up Kibana authentication
- [ ] Implement index lifecycle management (ILM)
- [ ] Configure log retention policies

**Mule:**
- [ ] Use encrypted properties for secrets
- [ ] Enable HTTPS listeners
- [ ] Configure proper database credentials
- [ ] Implement API authentication
- [ ] Set up log rotation

**Infrastructure:**
- [ ] Use Docker secrets for sensitive data
- [ ] Implement network segmentation
- [ ] Configure firewall rules
- [ ] Set up monitoring and alerting
- [ ] Regular security updates

### Resource Limits

Add to docker-compose.yml:

```yaml
services:
  elasticsearch:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
```

## Monitoring Configuration

### Prometheus Integration

APISIX metrics are available at:
```
http://localhost:9091/apisix/prometheus/metrics
```

Configure Prometheus:
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'apisix'
    static_configs:
      - targets: ['localhost:9091']
```

### Grafana Dashboards

Import APISIX dashboard:
1. Navigate to Grafana
2. Import dashboard ID: 11719
3. Configure Prometheus data source

### APM Integration

Elastic APM Server is included:
```bash
# APM Server endpoint
http://localhost:8200

# Configure in Mule app
elasticapm.server_urls=http://apm-server:8200
elasticapm.service_name=ce-mule-base
```

## Backup and Recovery

### ElasticSearch Snapshots

Configure snapshot repository:
```bash
curl -X PUT "http://localhost:9080/elasticsearch/_snapshot/my_backup" \
  -H 'Content-Type: application/json' -d'
{
  "type": "fs",
  "settings": {
    "location": "/mnt/backups/elasticsearch"
  }
}'
```

Create snapshot:
```bash
curl -X PUT "http://localhost:9080/elasticsearch/_snapshot/my_backup/snapshot_1?wait_for_completion=true"
```

### Volume Backups

```bash
# Backup ElasticSearch data
docker run --rm --volumes-from elasticsearch \
  -v $(pwd):/backup \
  ubuntu tar czf /backup/elasticsearch-backup.tar.gz /usr/share/elasticsearch/data

# Backup Mule volumes
tar czf mule-volumes-backup.tar.gz \
  git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/volumes
```

## Performance Tuning

### ElasticSearch

```yaml
# Increase heap (50% of available RAM, max 32GB)
ES_JAVA_OPTS=-Xms4g -Xmx4g

# Adjust thread pools
thread_pool.write.queue_size: 1000
thread_pool.search.queue_size: 1000

# Optimize for time-series data
index.number_of_shards: 1
index.number_of_replicas: 0
index.refresh_interval: 30s
```

### Logstash

```yaml
# Worker threads
pipeline.workers: 4           # CPU cores
pipeline.batch.size: 250
pipeline.batch.delay: 50

# Queue
queue.type: persisted
queue.max_bytes: 1gb
```

### Mule Workers

Edit `wrapper.conf`:
```properties
wrapper.java.initmemory=1024
wrapper.java.maxmemory=2048
```

## High Availability

### ElasticSearch Cluster

For production, deploy 3+ node cluster:
```yaml
services:
  elasticsearch-1:
    environment:
      - cluster.name=prod-cluster
      - node.name=es-node-1
      - discovery.seed_hosts=es-node-2,es-node-3
      - cluster.initial_master_nodes=es-node-1,es-node-2,es-node-3
```

### APISIX Clustering

Deploy multiple APISIX instances sharing the same etcd cluster.

### Mule Workers

Already configured for 2 workers. Add more as needed (see Chapter 5).

## Network Configuration

### Custom Docker Networks

Create networks:
```bash
docker network create ce-base-micronet --subnet=172.42.0.0/16
docker network create ce-base-network
```

### Port Mapping

Production port mapping:
```yaml
apisix:
  ports:
    - "80:9080"      # HTTP
    - "443:9443"     # HTTPS
    # Remove other ports for security
```

## Logging Configuration

### Log Rotation

Configure in docker-compose.yml:
```yaml
services:
  apisix:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Centralized Logging

All logs already centralized in ELK stack. Configure retention in Kibana ILM policies.

## Next Chapter

Continue to [Chapter 7: Troubleshooting](07-troubleshooting.md) for common issues and solutions.
