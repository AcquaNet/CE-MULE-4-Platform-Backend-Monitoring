# Application Performance Monitoring (APM)

Complete guide for setting up and using Elastic APM Server to monitor Mule 4 applications in both Docker and CloudHub deployments.

## Overview

APM Server receives performance data from Mule applications instrumented with the `elastic-apm-mule4-agent` and stores it in ElasticSearch for visualization in Kibana.

**Version Compatibility:**
- APM Server: 8.10.4
- elastic-apm-mule4-agent: 0.4.0 (uses elastic-apm-agent 1.17.0)
- ElasticSearch: 8.11.3
- Kibana: 8.11.3

**Note**: APM Server 8.10.4 is fully compatible with elastic-apm-agent 1.17.0. Using APM Server 8.11.x would require upgrading the Java agent to 1.43.0+.

## Architecture

```
Mule Application (with APM agent)
  ↓ HTTP POST to port 8200
APM Server (172.42.0.13:8200)
  ↓ Transforms and enriches data
ElasticSearch (172.42.0.10:9200)
  ↓ Stores APM indices
Kibana APM UI (http://localhost:9080/kibana/app/apm)
```

---

## APM Server Setup

APM Server is already included in the ELK stack `docker-compose.yml` and starts automatically.

### Configuration

APM Server is configured via command-line options in `docker-compose.yml`:

```yaml
apm-server:
  image: docker.elastic.co/apm/apm-server:8.10.4
  command: >
    apm-server -e
      -E apm-server.host=0.0.0.0:8200
      -E output.elasticsearch.hosts=["http://elasticsearch:9200"]
      -E apm-server.kibana.enabled=true
      -E apm-server.kibana.host=http://kibana:5601
      -E apm-server.auth.anonymous.enabled=true
```

### Network Access

- **Internal (Docker)**: `http://apm-server:8200` (recommended for Mule agents)
- **Via APISIX**: `http://localhost:9080/apm-server` (external access)
- **Direct**: `http://localhost:8200` (debugging only)
- **IP Address**: 172.42.0.13 (on ce-base-micronet)

### Viewing APM Data

Access the Kibana APM UI at: **http://localhost:9080/kibana/app/apm**

---

## Security Configuration

### Current Status

**INSECURE**: APM Server currently has anonymous authentication enabled. Anyone who can reach port 8200 can send APM data.

### Option 1: Secret Token (Recommended for Internal Apps)

Single shared token for all applications.

**Pros:**
- Simple to configure
- Perfect for trusted internal applications

**Cons:**
- All apps share the same token
- Token rotation requires updating all apps

**Setup:**

1. **Generate a secure secret token:**
   ```bash
   openssl rand -base64 32
   ```

2. **Add to `.env` file:**
   ```bash
   APM_SECRET_TOKEN=<your-generated-token>
   ```

3. **Update `docker-compose.yml` APM Server configuration:**

   Change:
   ```yaml
   -E apm-server.auth.anonymous.enabled=true
   ```

   To:
   ```yaml
   -E apm-server.auth.anonymous.enabled=false
   -E apm-server.auth.secret_token=${APM_SECRET_TOKEN}
   ```

4. **Restart APM Server:**
   ```bash
   docker-compose restart apm-server
   ```

5. **Configure Mule applications** (see Mule Configuration section below)

**Testing:**
```bash
# Should fail (401 Unauthorized)
curl -X POST http://localhost:8200/intake/v2/events \
  -H "Content-Type: application/x-ndjson" \
  -d '{"metadata":{"service":{"name":"test"}}}'

# Should succeed (202 Accepted)
curl -X POST http://localhost:8200/intake/v2/events \
  -H "Content-Type: application/x-ndjson" \
  -H "Authorization: Bearer <your-token>" \
  -d '{"metadata":{"service":{"name":"test"}}}'
```

### Option 2: API Keys (Recommended for Production)

Individual keys per application with fine-grained control.

**Pros:**
- Individual keys per application
- Fine-grained control and revocation
- Audit trail of which app sent what

**Cons:**
- More complex setup
- Requires ElasticSearch with X-Pack security enabled

**Setup:**

1. **Enable X-Pack Security in ElasticSearch** (see SECURITY_SETUP.md)

2. **Create API key via Kibana:**
   - Navigate to: Stack Management → API Keys
   - Click "Create API Key"
   - Name: `mule-app-1-apm`
   - Set expiration (optional)
   - Note the API key and ID

3. **Update `docker-compose.yml`:**
   ```yaml
   -E apm-server.auth.anonymous.enabled=false
   -E apm-server.auth.api_key.enabled=true
   ```

4. **Configure Mule application:**
   ```properties
   elastic.apm.api_key=<api-key-id>:<api-key-secret>
   elastic.apm.server_urls=http://apm-server:8200
   ```

### Option 3: SSL/TLS with Client Certificates (Enterprise)

For maximum security, combine API keys with mutual TLS authentication.

See [SSL_TLS_SETUP.md](SSL_TLS_SETUP.md) for complete SSL/TLS configuration.

### Security Recommendations

For production deployments:

- Anonymous authentication is disabled
- Secret token or API keys are configured
- Tokens/keys are stored securely (not in source code)
- SSL/TLS is enabled for production
- API keys have expiration dates
- Regular token/key rotation policy is established
- Monitoring for unauthorized access attempts is in place

---

## Mule Application Configuration

### Prerequisites

The Mule application must include:

1. **APM agent dependency** in `pom.xml`:
   ```xml
   <dependency>
     <groupId>co.elastic.apm</groupId>
     <artifactId>mule4-agent</artifactId>
     <version>0.4.0</version>
   </dependency>
   ```

2. **Import tracer.xml** in your main flow:
   ```xml
   <import file="tracer.xml" doc:name="Import APM Tracer" />
   ```

### Docker Deployment

For Mule applications running in Docker (git/CE-MULE-4-Platform-Backend-Docker):

**Configure via environment variables in `docker-compose.yml`:**

```yaml
ce-base-mule-backend-1:
  environment:
    # Elastic APM Configuration
    JAVA_OPTS: >-
      -Delastic.apm.server_urls=http://apm-server:8200
      -Delastic.apm.service_name=ce-mule-base-worker-1
      -Delastic.apm.service_version=${MULEAPP_VERSION}
      -Delastic.apm.environment=${mule_env}
      -Delastic.apm.log_level=INFO
      -Delastic.apm.transaction_sample_rate=1.0
```

**With Secret Token:**
```yaml
    JAVA_OPTS: >-
      -Delastic.apm.server_urls=http://apm-server:8200
      -Delastic.apm.secret_token=${APM_SECRET_TOKEN}
      -Delastic.apm.service_name=ce-mule-base-worker-1
      ...
```

**Configuration Options:**
- `elastic.apm.server_urls`: APM Server endpoint (use internal hostname)
- `elastic.apm.service_name`: Service identifier in APM UI
- `elastic.apm.service_version`: Application version
- `elastic.apm.environment`: Environment (dev/qa/prod)
- `elastic.apm.transaction_sample_rate`: Sampling rate (1.0 = 100%)
- `elastic.apm.secret_token`: Authentication token (if enabled)
- `elastic.apm.api_key`: API key (if using API keys)

### CloudHub Deployment

For Mule applications deployed to CloudHub:

#### Architecture

```
CloudHub Mule App
      ↓ (HTTPS/HTTP)
APISIX Gateway (Public IP/Domain)
      ↓ (Internal Network)
APM Server (172.42.0.13:8200)
      ↓
ElasticSearch → Kibana APM UI
```

#### Prerequisites

1. APISIX Gateway must be accessible from the internet
   - Port 9080 (HTTP) or 9443 (HTTPS) open
   - Firewall rules configured for CloudHub IP ranges
2. APM Server running and connected to APISIX

#### Step 1: Verify APISIX Access

Test from external network (simulates CloudHub):

```bash
curl -v http://<your-apisix-ip>:9080/apm-server
```

**Expected Response:**
```json
{
  "build_date": "2023-11-09T11:25:47Z",
  "version": "8.10.4",
  "publish_ready": true
}
```

#### Step 2: Configure CloudHub Properties

Create `src/main/resources/config/cloudhub.properties`:

```properties
# APM Server URL (via APISIX)
elastic.apm.server_url=http://<your-apisix-ip>:9080/apm-server

# OR use domain name (recommended for production)
elastic.apm.server_url=https://apm.company.com:9443/apm-server

# Service Configuration
elastic.apm.service_name=ce-mule-base
elastic.apm.environment=cloudhub
elastic.apm.enabled=true

# Sampling (reduce for production)
elastic.apm.transaction_sample_rate=0.1

# Authentication (if enabled)
elastic.apm.secret_token=${APM_SECRET_TOKEN}
```

#### Step 3: Deploy to CloudHub

1. Build application: `mvn clean package`
2. Upload JAR to CloudHub Runtime Manager
3. Set environment variable `APM_SECRET_TOKEN` in CloudHub properties (if using authentication)

#### Step 4: Verify in Kibana

1. Open: http://localhost:9080/kibana/app/apm
2. Look for service: **ce-mule-base** with environment: **cloudhub**
3. Verify transactions are appearing

#### Network Access Options

**Option 1: Public IP (Testing)**
```properties
elastic.apm.server_url=http://157.245.236.175:9080/apm-server
```

**Option 2: Domain Name (Production)**
```properties
elastic.apm.server_url=https://apm.company.com:9443/apm-server
```

**Option 3: VPN/Private Link (Enterprise)**
```properties
elastic.apm.server_url=http://apm-internal.company.com:9080/apm-server
```

---

## Performance Tuning

### Sampling Rates

Control how much data is collected:

```properties
# Development: 100% (capture everything)
elastic.apm.transaction_sample_rate=1.0

# Staging: 50%
elastic.apm.transaction_sample_rate=0.5

# Production: 10% (reduce overhead)
elastic.apm.transaction_sample_rate=0.1
```

### Additional Tuning Options

```properties
# Limit stack trace depth
elastic.apm.stack_trace_limit=25

# Set minimum span duration
elastic.apm.span_frames_min_duration=5ms

# Disable specific features
elastic.apm.capture_body=off
elastic.apm.capture_headers=false
```

---

## Troubleshooting

### Issue: No APM Data in Kibana

**Check 1: Verify APM agent is enabled**
```properties
elastic.apm.enabled=true  # Must be true
```

**Check 2: Verify sampling rate**
```properties
elastic.apm.transaction_sample_rate=1.0  # Use 100% for testing
```

**Check 3: Generate test traffic**
```bash
curl http://localhost:9080/api/v1/status
```

**Check 4: Check Mule logs**
```bash
docker logs ce-base-mule-backend-1 2>&1 | grep -i "apm\|elastic"
```

**Check 5: Check APM Server logs**
```bash
docker logs apm-server
```

**Check 6: Verify APM indices**
```bash
curl http://localhost:9080/elasticsearch/_cat/indices?v | grep apm
```

Expected indices:
- `apm-8.10.4-transaction-*`
- `apm-8.10.4-span-*`
- `apm-8.10.4-metric-*`
- `apm-8.10.4-error-*`

### Issue: CloudHub Can't Reach APM Server

**Check 1: Test APISIX from external network**
```bash
curl -v http://<your-apisix-ip>:9080/apm-server
```

**Check 2: Verify firewall allows CloudHub IPs**

CloudHub IP ranges (AWS US-East):
- 52.0.0.0/8
- 54.0.0.0/8

**Check 3: Check APISIX logs**
```bash
docker logs apisix | grep apm-server
```

**Check 4: Verify route exists**
```bash
curl http://localhost:9180/apisix/admin/routes/apm-server-api \
  -H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

### Issue: Authentication Errors

**Check 1: Verify token is correct**
```bash
# In CloudHub, check environment variable
echo $APM_SECRET_TOKEN

# In Docker, check .env file
grep APM_SECRET_TOKEN .env
```

**Check 2: Test authentication**
```bash
curl -X POST http://localhost:8200/intake/v2/events \
  -H "Content-Type: application/x-ndjson" \
  -H "Authorization: Bearer <your-token>" \
  -d '{"metadata":{"service":{"name":"test"}}}'
```

---

## Related Documentation

- [SECURITY_SETUP.md](SECURITY_SETUP.md) - General security configuration
- [SSL_TLS_SETUP.md](SSL_TLS_SETUP.md) - SSL/TLS setup for production
- [MONITORING_SETUP.md](MONITORING_SETUP.md) - Prometheus and Grafana monitoring

---

**Last Updated**: 2026-01-01
