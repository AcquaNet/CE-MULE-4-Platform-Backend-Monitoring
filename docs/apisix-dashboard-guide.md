# APISIX Dashboard Configuration Guide

## Dashboard Access
- **URL**: http://localhost:9080/
- **Username**: admin
- **Password**: admin

## Grafana Monitoring Configuration

### Current Setup
All routes are automatically monitored via Prometheus plugin. Metrics are available at:
- **Metrics Endpoint**: http://localhost:9080/apisix/prometheus/metrics (or port 9091)
- **Prometheus UI**: http://localhost:9080/prometheus/
- **Grafana Dashboards**: http://localhost:9080/grafana/

### View Metrics in APISIX Dashboard

1. **Routes with Prometheus Plugin**
   - Navigate to: Routes → List
   - Routes with monitoring enabled: `mule-api-v1`, `mule-api-all`
   - Click "Configure" to view/edit plugin settings

2. **Global Plugins**
   - Navigate to: Plugin Config → Global Plugins
   - Enable plugins that apply to ALL routes

3. **Plugin Templates**
   - Navigate to: Plugin Config → Plugin Template Config
   - Create reusable plugin configurations

### Enable Additional Monitoring Plugins

#### HTTP Logger (Send logs to external service)
```json
{
  "uri": "http://your-log-collector:8080/logs",
  "batch_max_size": 1000,
  "include_req_body": false,
  "include_resp_body": false
}
```

#### Zipkin (Distributed Tracing)
```json
{
  "endpoint": "http://zipkin:9411/api/v2/spans",
  "sample_ratio": 1
}
```

#### Request Validation (with metrics)
```json
{
  "header_schema": {
    "type": "object",
    "properties": {
      "Authorization": {
        "type": "string"
      }
    },
    "required": ["Authorization"]
  }
}
```

### View Real-Time Metrics

#### In APISIX Dashboard
- **Routes**: Shows request counts per route
- **Upstream**: Shows backend server health status
- **Service**: Shows service-level metrics

#### In Prometheus
1. Go to http://localhost:9080/prometheus/
2. Try these queries:
   - `apisix_http_status` - HTTP status code distribution
   - `rate(apisix_http_requests_total[5m])` - Request rate per 5 minutes
   - `apisix_http_latency_bucket` - Response time distribution
   - `apisix_bandwidth` - Bandwidth usage

#### In Grafana
1. Go to http://localhost:9080/grafana/
2. Navigate to: Dashboards → APISIX → Apache APISIX
3. Pre-configured panels show:
   - Request rates
   - HTTP status codes
   - Latency percentiles (p50, p90, p99)
   - Bandwidth usage
   - Upstream health
   - Top routes by traffic

### Add Custom Dashboard Panels in Grafana

1. **Access Grafana**: http://localhost:9080/grafana/
2. **Create New Panel**:
   - Go to existing dashboard or create new
   - Click "Add" → "Visualization"
3. **Select Prometheus Datasource**
4. **Enter Query** (examples):
   ```promql
   # Request rate by route
   sum by (route) (rate(apisix_http_requests_total[5m]))

   # Error rate
   sum(rate(apisix_http_status{code=~"5.."}[5m]))

   # P95 latency
   histogram_quantile(0.95, sum(rate(apisix_http_latency_bucket[5m])) by (le))

   # Upstream health
   apisix_upstream_status{state="up"}
   ```

### Configure Alerts (Future Enhancement)

To add alerting:
1. Add Alertmanager service to docker-compose.yml
2. Configure Prometheus alert rules
3. Set up Grafana alert notifications
4. Or use APISIX plugins:
   - `error-log-logger` - Export errors to external system
   - `api-breaker` - Circuit breaker with thresholds

## APISIX Dashboard Features

### 1. Routes Management
- **Create Route**: Define URL patterns and route traffic
- **Configure Plugins**: Add prometheus, rate limiting, auth, etc.
- **Test Route**: Use built-in testing tools

### 2. Upstreams Management
- **Load Balancing**: Round-robin (currently used), consistent hashing, etc.
- **Health Checks**: Active and passive health monitoring
- **Add/Remove Nodes**: Scale backend services

### 3. Services (Optional)
- Group routes together
- Share plugin configurations
- Easier management of related APIs

### 4. Consumers (For Authentication)
- Create API consumers
- Configure authentication (JWT, Key Auth, Basic Auth)
- Apply consumer-specific rate limits

### 5. SSL Certificates
- Upload SSL certificates
- Enable HTTPS on port 9443
- Automatic certificate management

### 6. Global Rules
- Apply plugins to ALL routes
- Security policies
- Rate limiting
- CORS settings

## Monitoring Best Practices

1. **Enable Prometheus on Important Routes**
   - Already done for Mule API routes
   - Add to other critical paths

2. **Set Up Health Checks**
   - Already configured on Mule workers upstream
   - Monitor backend service availability

3. **Use Grafana Dashboards**
   - Pre-loaded APISIX dashboard for overview
   - Create custom dashboards for business metrics

4. **Review Metrics Regularly**
   - Check request rates and identify trends
   - Monitor error rates (4xx, 5xx)
   - Watch latency percentiles (p95, p99)

5. **Set Up Alerts** (Future)
   - High error rate
   - Slow response times
   - Backend service failures

## Troubleshooting

### Metrics Not Showing in Grafana
1. Check Prometheus is scraping: http://localhost:9080/prometheus/targets
2. Verify APISIX metrics endpoint: http://localhost:9091/apisix/prometheus/metrics
3. Check Grafana datasource: Settings → Datasources → Prometheus

### Dashboard Not Loading
1. Verify containers are healthy: `docker ps`
2. Check APISIX logs: `docker logs apisix`
3. Verify routes are configured: APISIX Dashboard → Routes

### No Data in Panels
1. Send test requests to generate metrics:
   ```bash
   curl http://localhost:9080/api/v1/status
   ```
2. Wait 10-15 seconds for Prometheus to scrape
3. Refresh Grafana dashboard
