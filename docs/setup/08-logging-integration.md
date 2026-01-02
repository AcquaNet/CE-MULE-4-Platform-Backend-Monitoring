# Mule Application Logging with ELK Stack

Complete guide for configuring Mule application logging to send logs to ElasticSearch via Logstash for both Docker and CloudHub deployments.

## Overview

This setup uses Log4j2's Socket Appender to send JSON-formatted logs to Logstash via TCP. Logstash processes and indexes the logs in ElasticSearch, making them searchable and visualizable in Kibana.

**Architecture Flow:**
```
Mule Application (Log4j2) → Logstash (TCP:5000) → ElasticSearch → Kibana
```

**Key Features:**
- Automatic worker identification (Docker and CloudHub)
- Load balancing visibility across workers
- Centralized log aggregation
- Real-time log streaming
- Security authentication support

---

## Logstash Configuration

Logstash is already configured in the ELK stack and running via `docker-compose.yml`.

### Network Access

**Internal (Docker Network):**
- Hostname: `logstash`
- TCP Port: 5000 (internal only by default)
- Beats Port: 5044 (internal only by default)
- HTTP Monitoring API: `http://localhost:9080/logstash` (via APISIX)

**External Access (CloudHub/External Apps):**

By default, Logstash ports are internal-only for security. To enable external access, uncomment in `docker-compose.yml`:

```yaml
logstash:
  ports:
    - "5044:5044"      # Beats input
    - "5000:5000/tcp"  # TCP input
    - "5000:5000/udp"  # UDP input
```

**Security Recommendations:**
- Keep ports internal for Docker deployments
- For CloudHub, enable authentication (see Security section below)
- Consider using VPN or private connectivity for production

---

## Mule Application Configuration

### Log4j2 Configuration File

Place this file at `src/main/resources/log4j2.xml` in your Mule project:

```xml
<?xml version="1.0" encoding="utf-8"?>
<Configuration>
    <Properties>
        <!-- Application properties -->
        <Property name="mule.app.name">ce-mule-base</Property>
        <Property name="mule.env">dev</Property>

        <!-- Logstash connection -->
        <Property name="logstash.host">logstash</Property>
        <Property name="logstash.port">5000</Property>
    </Properties>

    <Appenders>
        <!-- File appender for local logs -->
        <RollingFile name="file"
                     fileName="${sys:mule.home}${sys:file.separator}logs${sys:file.separator}${mule.app.name}.log"
                     filePattern="${sys:mule.home}${sys:file.separator}logs${sys:file.separator}${mule.app.name}-%i.log">
            <PatternLayout pattern="%-5p %d [%t] [processor: %X{processorPath}; event: %X{correlationId}] %c: %m%n"/>
            <SizeBasedTriggeringPolicy size="10 MB"/>
            <DefaultRolloverStrategy max="10"/>
        </RollingFile>

        <!-- Socket appender for Logstash -->
        <Socket name="logstash" host="${logstash.host}" port="${logstash.port}" protocol="TCP">
            <JsonLayout compact="true" eventEol="true" properties="true" stacktraceAsString="true">
                <KeyValuePair key="application" value="${mule.app.name}"/>
                <KeyValuePair key="environment" value="${sys:mule_env:-${sys:mule.env:-${mule.env}}}"/>
                <KeyValuePair key="log_type" value="mule"/>
                <!-- Hybrid worker ID: env var (Docker) → sys prop (CloudHub) → unknown -->
                <KeyValuePair key="worker_id" value="${env:WORKER_ID:-${sys:mule.worker.id:-unknown}}"/>
                <KeyValuePair key="correlationId" value="%X{correlationId}"/>
            </JsonLayout>
        </Socket>
    </Appenders>

    <Loggers>
        <!-- Reduce noise from HTTP connectors -->
        <AsyncLogger name="org.mule.service.http" level="WARN"/>
        <AsyncLogger name="org.mule.extension.http" level="WARN"/>
        <AsyncLogger name="org.mule.runtime.core.internal.processor.LoggerMessageProcessor" level="INFO"/>

        <!-- Root logger -->
        <AsyncRoot level="INFO">
            <AppenderRef ref="file"/>
            <AppenderRef ref="logstash"/>
        </AsyncRoot>
    </Loggers>
</Configuration>
```

### Configuration Properties

| Property | Description | Example |
|----------|-------------|---------|
| `mule.app.name` | Application name | `customer-api` |
| `mule.env` | Environment (dev/qa/prod) | `dev` |
| `logstash.host` | Logstash hostname/IP | `logstash` (Docker) or `logstash.company.com` (CloudHub) |
| `logstash.port` | Logstash TCP port | `5000` |

---

## Docker Deployment

For Mule applications running in Docker containers.

### Worker Identification

Set the `WORKER_ID` environment variable in `docker-compose.yml`:

```yaml
ce-base-mule-backend-1:
  environment:
    - WORKER_ID=worker-1
    - mule_env=docker-local
    # ... other variables ...

ce-base-mule-backend-2:
  environment:
    - WORKER_ID=worker-2
    - mule_env=docker-local
    # ... other variables ...
```

### Configuration

**Log4j2 uses internal hostname:**
```xml
<Property name="logstash.host">logstash</Property>
<Property name="logstash.port">5000</Property>
```

### Verification

1. **Start the stack:**
   ```bash
   docker-compose up -d
   ```

2. **Check logs are flowing:**
   ```bash
   # View Logstash logs
   docker-compose logs -f logstash

   # Query ElasticSearch
   curl http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty
   ```

3. **View in Kibana:**
   - Open: http://localhost:9080/kibana
   - Navigate to Discover
   - Select index pattern: `mule-logs-*`
   - Filter by: `worker_id:"worker-1"`

---

## CloudHub Deployment

For Mule applications deployed to CloudHub.

### Worker Identification

CloudHub automatically provides `mule.worker.id` as a system property:

- Single worker: `mule.worker.id = 0`
- Two workers: `mule.worker.id = 0` and `1`
- Three workers: `mule.worker.id = 0`, `1`, and `2`

The log4j2.xml configuration automatically uses this via:
```xml
<KeyValuePair key="worker_id" value="${env:WORKER_ID:-${sys:mule.worker.id:-unknown}}"/>
```

### Configuration Steps

#### Step 1: Update Logstash Host

Create `src/main/resources/config/cloudhub.properties`:

```properties
# Logstash external endpoint
logstash.host=your-logstash-server.com
logstash.port=5000

# OR use your APISIX gateway IP
logstash.host=157.245.236.175
logstash.port=5000
```

#### Step 2: Ensure External Access

Uncomment Logstash ports in `docker-compose.yml`:

```yaml
logstash:
  ports:
    - "5000:5000/tcp"
```

#### Step 3: Configure Firewall

Allow CloudHub IP ranges to access your Logstash server:

**CloudHub IP Ranges (AWS US-East):**
- 52.0.0.0/8
- 54.0.0.0/8

#### Step 4: Deploy to CloudHub

1. Build application: `mvn clean package`
2. Upload JAR to CloudHub Runtime Manager
3. Logs will automatically stream to your Logstash server

### Verification

1. **Check CloudHub logs** for connection confirmation
2. **Query ElasticSearch:**
   ```bash
   curl http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty \
     -H 'Content-Type: application/json' \
     -d '{"query": {"match": {"environment": "Production"}}}'
   ```

3. **View in Kibana:**
   - Filter by: `worker_id:"0"` or `worker_id:"1"`
   - Filter by: `environment:"Production"`

---

## Security Configuration

### Current Status

**INSECURE**: Logstash currently accepts data from anyone who can reach the ports.

### Option 1: Network Isolation (Docker Only)

Keep Logstash ports internal (default configuration). Only applications in the Docker network can send logs.

**Verification:**
```bash
# From outside Docker network (should fail)
nc -zv localhost 5000

# From inside Docker network (should work)
docker exec ce-base-mule-backend-1 nc -zv logstash 5000
```

**Recommended for:** Docker-only deployments where all Mule apps run in containers.

### Option 2: Token-Based Authentication (CloudHub/External)

Secure Logstash with token authentication for external applications.

#### Setup

**1. Generate authentication token:**
```bash
openssl rand -base64 32
```

**2. Add to `.env` file:**
```bash
LOGSTASH_AUTH_TOKEN=<your-generated-token>
```

**3. Update Logstash pipeline** (`logstash/pipeline/logstash.conf`):

Add HTTP filter to check for authentication token:

```ruby
filter {
  # Token-based authentication
  if [headers][authorization] {
    ruby {
      code => '
        auth_header = event.get("[headers][authorization]")
        expected_token = ENV["LOGSTASH_AUTH_TOKEN"]

        if auth_header && auth_header.include?("Bearer ")
          provided_token = auth_header.split("Bearer ")[1]
          if provided_token != expected_token
            event.cancel()
          end
        else
          event.cancel()
        end
      '
    }
  } else {
    # No auth header = reject
    mutate {
      add_tag => ["unauthorized"]
    }
    drop {}
  }

  # Rest of existing filters...
}
```

**4. Configure Mule application log4j2.xml:**

Replace Socket appender with HTTP appender:

```xml
<!-- Remove Socket appender, add HTTP appender -->
<Http name="logstash-http" url="http://${logstash.host}:8080">
    <Property name="Authorization" value="Bearer ${env:LOGSTASH_AUTH_TOKEN}"/>
    <Property name="Content-Type" value="application/json"/>
    <JsonLayout compact="true" eventEol="true">
        <KeyValuePair key="application" value="${mule.app.name}"/>
        <KeyValuePair key="environment" value="${mule.env}"/>
        <KeyValuePair key="log_type" value="mule"/>
        <KeyValuePair key="worker_id" value="${env:WORKER_ID:-${sys:mule.worker.id:-unknown}}"/>
    </JsonLayout>
</Http>
```

**5. Update docker-compose.yml to expose HTTP port:**

```yaml
logstash:
  ports:
    - "8080:8080"  # HTTP input with authentication
  environment:
    - LOGSTASH_AUTH_TOKEN=${LOGSTASH_AUTH_TOKEN}
```

**6. Set CloudHub environment variable:**

In CloudHub Runtime Manager properties:
```
LOGSTASH_AUTH_TOKEN=<your-generated-token>
```

#### Testing

```bash
# Should fail (401 Unauthorized)
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{"message":"test"}'

# Should succeed (200 OK)
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{"application":"test","level":"INFO","message":"test log"}'
```

### Option 3: SSL/TLS with Client Certificates (Enterprise)

For maximum security, use mutual TLS authentication.

See [SSL_TLS_SETUP.md](SSL_TLS_SETUP.md) for complete SSL/TLS configuration.

### Security Recommendations

For production deployments:

- Anonymous TCP/UDP inputs are disabled or restricted
- HTTP input with authentication is enabled
- Beats input uses SSL/TLS client certificates
- Network-level access controls are configured (firewall/Docker network)
- APISIX IP whitelisting is configured
- Credentials are stored securely (not in source code)
- SSL/TLS certificates are valid and not expired
- Regular credential rotation policy is established
- Monitoring for unauthorized access attempts is in place

---

## Viewing Logs in Kibana

### Access Kibana

Open: **http://localhost:9080/kibana**

### Create Index Pattern

1. Navigate to: **Stack Management** → **Index Patterns**
2. Click **Create index pattern**
3. Enter pattern: `mule-logs-*`
4. Select time field: `@timestamp`
5. Click **Create index pattern**

### Common Queries

**Filter by application:**
```
application:"ce-mule-base"
```

**Filter by worker:**
```
worker_id:"worker-1"
```

**Filter by environment:**
```
environment:"Production"
```

**Filter by log level:**
```
level:"ERROR"
```

**Search by correlation ID:**
```
correlationId:"abc-123-def-456"
```

**Combine filters:**
```
application:"ce-mule-base" AND level:"ERROR" AND worker_id:"worker-1"
```

### Available Log Fields

| Field | Description | Example Value |
|-------|-------------|---------------|
| `application` | Application name | `ce-mule-base` |
| `environment` | Environment | `Production`, `docker-local` |
| `worker_id` | Worker identifier | `worker-1`, `0`, `1` |
| `level` | Log level | `INFO`, `WARN`, `ERROR` |
| `message` | Log message | `Processing request` |
| `correlationId` | Mule correlation ID | `abc-123-def` |
| `loggerName` | Logger class name | `com.example.MyFlow` |
| `thread` | Thread name | `[MuleRuntime].uber.01` |
| `@timestamp` | Log timestamp | `2026-01-01T12:00:00.000Z` |

---

## Troubleshooting

### Issue: Logs Not Appearing in Kibana

**Check 1: Verify Logstash is running**
```bash
docker-compose ps logstash
```

**Check 2: Check Logstash logs**
```bash
docker-compose logs -f logstash
```

**Check 3: Test TCP connection**
```bash
# From Docker network
docker exec ce-base-mule-backend-1 nc -zv logstash 5000

# From external (if ports are exposed)
nc -zv localhost 5000
```

**Check 4: Send test data**
```bash
echo '{"application":"test-app","level":"INFO","message":"test log"}' | nc localhost 5000
```

**Check 5: Verify index exists**
```bash
curl http://localhost:9080/elasticsearch/_cat/indices?v | grep mule
```

**Check 6: Check Mule application logs**
```bash
docker logs ce-base-mule-backend-1 | grep -i logstash
```

### Issue: CloudHub Can't Reach Logstash

**Check 1: Verify ports are exposed**
```bash
# Check docker-compose.yml has ports uncommented
docker ps --filter "name=logstash"
```

**Check 2: Test from external network**
```bash
nc -zv <your-public-ip> 5000
```

**Check 3: Verify firewall allows CloudHub IPs**

Use your cloud provider's firewall to allow:
- 52.0.0.0/8
- 54.0.0.0/8

**Check 4: Check Logstash configuration**
```bash
docker-compose logs logstash | grep "Pipeline started"
```

### Issue: Authentication Failures

**Check 1: Verify token is set**
```bash
# In .env file
grep LOGSTASH_AUTH_TOKEN .env

# In CloudHub properties
echo $LOGSTASH_AUTH_TOKEN
```

**Check 2: Test authentication**
```bash
curl -X POST http://localhost:8080 \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"message":"test"}'
```

**Check 3: Check for "unauthorized" tags in logs**
```bash
curl http://localhost:9080/elasticsearch/mule-logs-*/_search?pretty \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match": {"tags": "unauthorized"}}}'
```

---

## Docker vs CloudHub Comparison

| Feature | Docker | CloudHub |
|---------|--------|----------|
| **Worker ID** | Environment variable: `WORKER_ID` | System property: `mule.worker.id` |
| **Logstash Host** | Internal: `logstash` | External: IP or domain |
| **Port Access** | Internal network | External (firewall required) |
| **Authentication** | Optional (network isolation) | Recommended (token-based) |
| **Configuration** | docker-compose.yml | cloudhub.properties |

---

## Related Documentation

- [APM.md](APM.md) - Application Performance Monitoring setup
- [SECURITY_SETUP.md](SECURITY_SETUP.md) - General security configuration
- [SSL_TLS_SETUP.md](SSL_TLS_SETUP.md) - SSL/TLS setup for production
- [RETENTION_POLICY_GUIDE.md](RETENTION_POLICY_GUIDE.md) - Log retention and lifecycle management

---

**Last Updated**: 2026-01-01
