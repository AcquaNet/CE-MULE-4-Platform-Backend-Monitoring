# Monitoring and Alerting Setup Guide

This guide explains how to configure and use the monitoring and alerting system for your ELK stack deployment.

## Quick Start

### Step 1: Enable Monitoring (Default: Enabled)

Monitoring is **enabled by default** and includes:
- **Prometheus**: Metrics collection and storage
- **Grafana**: Visualization dashboards
- **ElasticSearch Exporter**: ElasticSearch-specific metrics

No configuration needed for basic monitoring - it's ready to use!

### Step 2: Access Dashboards

```bash
# Start the stack (monitoring starts automatically)
docker-compose up -d

# Access dashboards
Prometheus: http://localhost:9080/prometheus
Grafana:    http://localhost:9080/grafana (admin / your-password-from-.env)
```

### Step 3: Enable Alerting (Optional)

To receive alert notifications, configure in `.env`:

```bash
# Enable alerting
ALERTING_ENABLED=true

# Configure email notifications
ALERT_EMAIL_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_ADDRESS=alerts@yourdomain.com
SMTP_TO_ADDRESSES=admin@yourdomain.com,ops@yourdomain.com

# Or configure Slack
ALERT_SLACK_ENABLED=true
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SLACK_CHANNEL=#alerts
```

Then run:

```bash
./scripts/setup-monitoring.sh
docker-compose --profile alerting up -d
```

## What's Included

### Monitoring Services

| Service | Purpose | Default State | Access URL |
|---------|---------|---------------|------------|
| **Prometheus** | Metrics collection and storage | Enabled | http://localhost:9080/prometheus |
| **Grafana** | Visualization dashboards | Enabled | http://localhost:9080/grafana |
| **ElasticSearch Exporter** | ES metrics for Prometheus | Enabled | Internal only (port 9114) |
| **Alertmanager** | Alert routing and notifications | Disabled | http://localhost:9080/alertmanager |

### Metrics Collected

**ElasticSearch Metrics:**
- Cluster health status (green/yellow/red)
- Node count and availability
- JVM heap usage and garbage collection
- Disk space usage per node
- Index and shard statistics
- Search and indexing performance
- Snapshot status

**APISIX Gateway Metrics:**
- Request rate and latency
- HTTP status codes distribution
- Upstream health status
- Bandwidth usage

**System Metrics:**
- Service uptime
- Container health status
- Prometheus and Grafana health

### Pre-configured Alerts

When alerting is enabled, you get these alerts out of the box:

**Critical Alerts:**
- ElasticSearch cluster down
- ElasticSearch cluster health RED
- APISIX gateway down
- Disk space < 15%
- JVM heap usage > 90%
- High 5xx error rate
- Backup failures

**Warning Alerts:**
- ElasticSearch cluster health YELLOW
- Disk space < 30%
- JVM heap usage > 85%
- Unassigned shards
- High request latency
- No recent backup (> 24 hours)

## Configuration

### Monitoring Configuration (.env)

```bash
# -----------------------------------------------------------------------------
# Monitoring and Alerting Configuration
# -----------------------------------------------------------------------------

# Enable Prometheus metrics collection (default: true)
MONITORING_ENABLED=true

# Enable Alertmanager for notifications (default: false)
ALERTING_ENABLED=false

# Prometheus settings
PROMETHEUS_RETENTION=30d              # How long to keep metrics
PROMETHEUS_SCRAPE_INTERVAL=15s        # How often to collect metrics
PROMETHEUS_EVALUATION_INTERVAL=15s    # How often to evaluate alert rules

# Enable ElasticSearch exporter (default: true when monitoring enabled)
ELASTICSEARCH_EXPORTER_ENABLED=true

# Enable Logstash monitoring (uses built-in API)
LOGSTASH_MONITORING_ENABLED=true
```

### Alert Thresholds (.env)

Customize when alerts fire:

```bash
# Alert Thresholds
ALERT_ES_CLUSTER_STATUS=yellow        # Alert when cluster not green
ALERT_DISK_USAGE_THRESHOLD=85         # Alert at 85% disk usage
ALERT_MEMORY_USAGE_THRESHOLD=90       # Alert at 90% memory
ALERT_JVM_HEAP_THRESHOLD=90           # Alert at 90% JVM heap
ALERT_SERVICE_DOWN_DURATION=5m        # Alert after 5 min downtime
ALERT_REQUEST_LATENCY_MS=1000         # Alert when latency > 1000ms
ALERT_ON_FAILED_BACKUP=true           # Alert on backup failures
```

### Email Alerts (.env)

```bash
# Email Alert Configuration
ALERT_EMAIL_ENABLED=false

# SMTP Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_ADDRESS=alerts@yourdomain.com
SMTP_TO_ADDRESSES=admin@yourdomain.com,ops@yourdomain.com
SMTP_USE_TLS=true
```

**Gmail Setup:**
1. Enable 2-factor authentication on your Google account
2. Generate an App Password: https://myaccount.google.com/apppasswords
3. Use the app password as `SMTP_PASSWORD`

**Office 365 Setup:**
```bash
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USERNAME=your-email@yourdomain.com
SMTP_PASSWORD=your-password
```

### Slack Alerts (.env)

```bash
# Slack Alert Configuration
ALERT_SLACK_ENABLED=false
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SLACK_CHANNEL=#alerts
SLACK_USERNAME=ELK-Alertmanager
```

**Slack Setup:**
1. Go to your Slack workspace settings
2. Create an Incoming Webhook: https://api.slack.com/messaging/webhooks
3. Select the channel for alerts
4. Copy the webhook URL to `SLACK_WEBHOOK_URL`

### PagerDuty Alerts (.env)

```bash
# PagerDuty Alert Configuration
ALERT_PAGERDUTY_ENABLED=false
PAGERDUTY_INTEGRATION_KEY=your-integration-key
PAGERDUTY_SEVERITY=error                # critical, error, warning, info
```

**PagerDuty Setup:**
1. Log in to PagerDuty
2. Go to Services → your service → Integrations
3. Add Integration → Events API V2
4. Copy the Integration Key to `PAGERDUTY_INTEGRATION_KEY`

### Webhook Alerts (.env)

For custom integrations (Microsoft Teams, Discord, custom apps):

```bash
# Webhook Alert Configuration
ALERT_WEBHOOK_ENABLED=false
ALERT_WEBHOOK_URL=https://your-webhook-endpoint.com
ALERT_WEBHOOK_METHOD=POST             # POST or PUT
ALERT_WEBHOOK_TIMEOUT=10              # seconds
```

### Alert Grouping (.env)

Control how alerts are grouped and when notifications are sent:

```bash
# Alert Grouping and Throttling
ALERT_GROUP_BY=alertname,cluster,service    # Group similar alerts
ALERT_GROUP_WAIT=30s                         # Wait before first notification
ALERT_GROUP_INTERVAL=5m                      # Wait for more alerts in group
ALERT_REPEAT_INTERVAL=4h                     # Repeat notification every 4h
```

## Usage

### Start Monitoring (Default Configuration)

Monitoring is enabled by default and starts automatically:

```bash
# Start all services (monitoring included)
docker-compose up -d

# Check monitoring status
./scripts/setup-monitoring.sh --status
```

### Enable Alerting

```bash
# 1. Configure notification channels in .env
nano .env

# 2. Set ALERTING_ENABLED=true

# 3. Run setup script
./scripts/setup-monitoring.sh

# 4. Start Alertmanager
docker-compose --profile alerting up -d
```

### Check System Health

```bash
# One-time health check
./scripts/check-health.sh

# Detailed health check
./scripts/check-health.sh --verbose

# Continuous monitoring (updates every 10s)
./scripts/check-health.sh --watch

# JSON output (for automation)
./scripts/check-health.sh --json
```

### View Metrics in Prometheus

```bash
# Open Prometheus
http://localhost:9080/prometheus

# Example queries:
elasticsearch_cluster_health_status{color="green"}
rate(apisix_http_status{code="200"}[5m])
elasticsearch_jvm_memory_used_bytes{area="heap"}
```

### View Dashboards in Grafana

```bash
# Open Grafana
http://localhost:9080/grafana

# Default credentials
Username: admin
Password: (from GRAFANA_ADMIN_PASSWORD in .env)

# Pre-configured dashboards:
1. APISIX Gateway Overview
2. ElasticSearch Cluster (if you create it)
3. Prometheus Stats
```

### Create Custom Dashboards

Grafana dashboards can be created via:
1. **Web UI**: Grafana → Dashboards → New Dashboard
2. **JSON Import**: Place dashboard JSON in `grafana/provisioning/dashboards/`
3. **API**: Use Grafana HTTP API for automation

### View Active Alerts

```bash
# Prometheus alerts
http://localhost:9080/prometheus/alerts

# Alertmanager (if enabled)
http://localhost:9080/alertmanager
```

### Test Alerting

```bash
# Trigger a test alert by stopping a service
docker-compose stop elasticsearch

# Check Alertmanager
http://localhost:9080/alertmanager

# Restart service
docker-compose start elasticsearch
```

### Reload Configuration

After changing Prometheus or alert rules:

```bash
# Reload Prometheus configuration without restart
./scripts/setup-monitoring.sh --reload

# Or restart services
docker-compose restart prometheus
docker-compose restart alertmanager
```

## Troubleshooting

### Issue: Prometheus Not Scraping Metrics

**Symptoms**: No data in Grafana, empty Prometheus queries

**Solution**:
```bash
# Check Prometheus targets
http://localhost:9080/prometheus/targets

# All targets should show "UP" status
# If DOWN, check:

# 1. Service is running
docker-compose ps

# 2. Service logs
docker-compose logs prometheus
docker-compose logs elasticsearch-exporter

# 3. Network connectivity
docker exec prometheus wget -O- http://elasticsearch-exporter:9114/metrics
```

### Issue: ElasticSearch Exporter Not Working

**Symptoms**: No ElasticSearch metrics in Prometheus

**Solution**:
```bash
# Check if exporter is enabled
./scripts/setup-monitoring.sh --status

# Check exporter health
curl http://localhost:9114/health

# Check ElasticSearch connectivity from exporter
docker exec elasticsearch-exporter wget -O- http://elasticsearch:9200/_cluster/health

# View exporter logs
docker-compose logs elasticsearch-exporter
```

### Issue: Grafana Dashboards Empty

**Symptoms**: Dashboards show "No Data"

**Solution**:
```bash
# 1. Check Prometheus data source in Grafana
#    Grafana → Connections → Data Sources → Prometheus
#    Click "Test" - should show "Data source is working"

# 2. Check if Prometheus has data
http://localhost:9080/prometheus
# Run query: up
# Should show 1 for all services

# 3. Check time range in Grafana
#    Top-right corner - set to "Last 6 hours"

# 4. Verify metrics exist
#    Explore → Prometheus → Metrics browser
```

### Issue: Alerts Not Sending Notifications

**Symptoms**: Alerts firing in Prometheus but no emails/Slack messages

**Solution**:
```bash
# 1. Check Alertmanager is running
docker-compose ps alertmanager

# 2. Check Alertmanager configuration
cat alertmanager/alertmanager.yml

# 3. Check Alertmanager logs
docker-compose logs alertmanager

# 4. Test notification channel manually
# For email:
docker exec alertmanager wget --post-data='{}' http://localhost:9093/api/v1/alerts

# 5. Check .env configuration
grep ALERT_ .env

# 6. Verify SMTP/Slack credentials
# Try sending test email with same credentials
```

### Issue: High Memory Usage

**Symptoms**: Prometheus or Grafana consuming too much memory

**Solution**:
```bash
# Reduce Prometheus retention
# In .env:
PROMETHEUS_RETENTION=15d  # Instead of 30d

# Increase scrape interval (less frequent collection)
PROMETHEUS_SCRAPE_INTERVAL=30s  # Instead of 15s

# Restart Prometheus
docker-compose restart prometheus

# Check memory usage
docker stats prometheus grafana
```

### Issue: Alerts Firing Incorrectly

**Symptoms**: False positive alerts

**Solution**:
```bash
# Adjust thresholds in .env
ALERT_DISK_USAGE_THRESHOLD=90  # Instead of 85
ALERT_SERVICE_DOWN_DURATION=10m  # Instead of 5m

# Regenerate configuration
./scripts/setup-monitoring.sh

# Reload Prometheus
./scripts/setup-monitoring.sh --reload
```

## Best Practices

### 1. Configure Alerts Gradually

Start with critical alerts only, then add warnings:

```bash
# Week 1: Critical only
ALERTING_ENABLED=true
ALERT_EMAIL_ENABLED=true
# Monitor: Cluster down, disk full, service outages

# Week 2: Add warnings
# Monitor: Yellow cluster, high heap, unassigned shards

# Week 3: Add performance alerts
ALERT_REQUEST_LATENCY_MS=1000
# Monitor: Slow queries, high error rates
```

### 2. Use Alert Grouping

Prevent notification spam:

```bash
ALERT_GROUP_BY=alertname,cluster,service
ALERT_GROUP_WAIT=30s          # Wait to group similar alerts
ALERT_REPEAT_INTERVAL=4h      # Don't spam every minute
```

### 3. Set Appropriate Thresholds

Based on your workload:

```bash
# Development
ALERT_DISK_USAGE_THRESHOLD=90
ALERT_SERVICE_DOWN_DURATION=15m

# Production
ALERT_DISK_USAGE_THRESHOLD=85
ALERT_SERVICE_DOWN_DURATION=5m
```

### 4. Monitor the Monitors

Set up alerts for monitoring infrastructure:

```bash
# Alerts already included:
- PrometheusDown (critical)
- AlertmanagerDown (critical)
- GrafanaDown (warning)
```

### 5. Regular Dashboard Reviews

Weekly:
- Review Grafana dashboards for trends
- Check for recurring alerts
- Adjust thresholds based on actual usage

Monthly:
- Review alert fatigue (too many alerts?)
- Update dashboards for new services
- Clean up old data if needed

### 6. Document Custom Alerts

If you add custom alert rules in `prometheus/rules/`:

```yaml
# Document each alert with:
- alert: CustomAlertName
  annotations:
    summary: "Clear summary"
    description: "Detailed description with context"
    runbook_url: "Link to fix instructions"
```

### 7. Test Disaster Scenarios

Quarterly:
```bash
# Test alert delivery
docker-compose stop elasticsearch

# Verify alerts received within expected time

# Test recovery
docker-compose start elasticsearch

# Verify recovery notifications
```

## Advanced Configuration

### Custom Prometheus Queries

Add custom metrics in `prometheus/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'my-custom-app'
    static_configs:
      - targets: ['my-app:8080']
    metrics_path: '/metrics'
```

### Custom Alert Rules

Add rules in `prometheus/rules/custom-alerts.yml`:

```yaml
groups:
  - name: custom_alerts
    interval: 60s
    rules:
      - alert: CustomAlert
        expr: my_metric > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Custom metric exceeded"
```

### Alertmanager Routing

Advanced routing in `alertmanager/alertmanager.yml.template`:

```yaml
route:
  routes:
    # Send critical alerts to PagerDuty
    - match:
        severity: critical
      receiver: 'pagerduty'

    # Send backup alerts to dedicated channel
    - match:
        component: backup
      receiver: 'backup-team-slack'
```

## Setup Guide

### Initial Setup

1. Copy `.env.example` to `.env`
2. Set `MONITORING_ENABLED=true` (enabled by default)
3. Start services: `docker-compose up -d`
4. Access Grafana: http://localhost:9080/grafana
5. Access Prometheus: http://localhost:9080/prometheus
6. Run health check: `./scripts/check-health.sh`

### Enable Alerting (Optional)

1. Set `ALERTING_ENABLED=true` in `.env`
2. Configure at least one notification channel (email/Slack/PagerDuty)
3. Run: `./scripts/setup-monitoring.sh`
4. Start Alertmanager: `docker-compose --profile alerting up -d`
5. Test alerts by stopping a service
6. Verify notifications received
7. Adjust thresholds in `.env` as needed

### Ongoing Maintenance

- Review dashboards weekly
- Update alert thresholds based on actual usage
- Check Prometheus disk usage monthly
- Test alert delivery quarterly
- Update dashboards for new services

## Summary

**Default State:**
- ✅ **Monitoring**: Enabled (Prometheus + Grafana + ElasticSearch Exporter)
- ❌ **Alerting**: Disabled (no notifications sent)

**To Enable Alerting:**
1. Configure notification channel in `.env` (email/Slack/PagerDuty)
2. Set `ALERTING_ENABLED=true`
3. Run `./scripts/setup-monitoring.sh`
4. Start Alertmanager: `docker-compose --profile alerting up -d`

**Access URLs:**
- Prometheus: http://localhost:9080/prometheus
- Grafana: http://localhost:9080/grafana
- Alertmanager: http://localhost:9080/alertmanager (when enabled)

**Key Commands:**
```bash
# Check status
./scripts/setup-monitoring.sh --status

# Health check
./scripts/check-health.sh

# Reload config
./scripts/setup-monitoring.sh --reload
```

For questions or issues, refer to the [Troubleshooting](#troubleshooting) section or check service logs with `docker-compose logs <service-name>`.
