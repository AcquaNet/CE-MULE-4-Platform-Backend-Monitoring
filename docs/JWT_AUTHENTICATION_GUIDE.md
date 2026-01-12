# JWT Authentication & Rate Limiting Guide

## Overview

Your Mule platform now has enterprise-grade security with:
- **JWT Authentication** via Keycloak (OpenID Connect)
- **Rate Limiting** (100 req/min per user, max 20 concurrent connections)
- **Connection Limiting** to protect Mule workers from overload

## Architecture

```
External Client
      ↓
APISIX Gateway (9080/9443)
   ├── Keycloak Auth Check (JWT validation)
   ├── Rate Limiting (100 req/min)
   ├── Connection Limiting (20 concurrent)
   └── Load Balancing
      ↓
   Mule Workers (2 instances)
```

## Quick Start

### 1. Access Keycloak Admin Console

```bash
# Via APISIX
http://localhost:9080/auth

# Login credentials
Username: admin
Password: admin
```

### 2. Get an Access Token

**Option A: Using Password Grant (User Credentials)**

```bash
# Login as 'admin' user
curl -X POST http://localhost:9080/auth/realms/mule/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=mule-api-gateway" \
  -d "client_secret=mule-gateway-secret-12345" \
  -d "username=admin" \
  -d "password=admin123" \
  -d "grant_type=password"
```

**Option B: Using Client Credentials Grant (Service-to-Service)**

```bash
curl -X POST http://localhost:9080/auth/realms/mule/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=mule-api-gateway" \
  -d "client_secret=mule-gateway-secret-12345" \
  -d "grant_type=client_credentials"
```

**Save the access_token from the response:**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICI...",
  "expires_in": 3600,
  "refresh_expires_in": 1800,
  "token_type": "Bearer",
  "not-before-policy": 0,
  "scope": "openid profile email"
}
```

### 3. Test API Access

**Without Token (Should Fail with 401 Unauthorized):**

```bash
curl -v http://localhost:9080/api/v1/status
# Expected: 401 Unauthorized
```

**With Valid Token (Should Succeed):**

```bash
TOKEN="<your-access-token-here>"

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:9080/api/v1/status

# Expected: {"status":"OK","version":"1.0.10","environment":"local-docker"}
```

### 4. Test Rate Limiting

```bash
# This script tests rate limiting by sending 110 requests rapidly
# You should see rejections after 100 requests

TOKEN="<your-access-token-here>"

for i in {1..110}; do
  echo "Request #$i:"
  curl -s -H "Authorization: Bearer $TOKEN" \
    -w "\nHTTP Status: %{http_code}\n" \
    http://localhost:9080/api/v1/status
  sleep 0.1
done
```

After request #100, you should see:

```json
{
  "error_msg": "Rate limit exceeded. Maximum 100 requests per minute."
}
HTTP Status: 429
```

## Keycloak Configuration

### Pre-configured Users

| Username | Password | Roles | Description |
|----------|----------|-------|-------------|
| admin | admin123 | user, admin | Full access |
| developer | dev123 | user | Standard access |

### Pre-configured Client

- **Client ID**: `mule-api-gateway`
- **Client Secret**: `mule-gateway-secret-12345`
- **Grant Types**: Authorization Code, Client Credentials, Password
- **Access Token Lifespan**: 3600 seconds (1 hour)
- **Redirect URIs**: `http://localhost:9080/*`

## Rate Limiting Configuration

Current limits configured in `config/apisix/apisix.yaml`:

```yaml
# Rate limiting: 100 requests per minute per IP address
limit-count:
  count: 100
  time_window: 60
  key_type: "var"
  key: "remote_addr"
  rejected_code: 429
  rejected_msg: "Rate limit exceeded. Maximum 100 requests per minute."

# Connection limit: max 20 concurrent connections per IP
limit-conn:
  conn: 20
  burst: 10
  default_conn_delay: 0.1
  key_type: "var"
  key: "remote_addr"
  rejected_code: 503
```

**Note**: Rate limiting is configured in APISIX data plane mode via YAML. Production deployments should verify rate limiting enforcement and may need to use APISIX control plane mode for full Admin API functionality if dynamic rate limit adjustments are required.

### Adjusting Rate Limits

To change limits, edit `config/apisix/apisix.yaml` and reload APISIX:

```bash
cd "/c/work/Aqua/Docker ElasticSearch"

# Edit the file (change count: 100 to your desired value)
nano config/apisix/apisix.yaml

# Find the limit-count section and update:
#   count: 100          # Maximum requests
#   time_window: 60     # Time window in seconds

# Reload APISIX
docker-compose exec apisix apisix reload
```

## Troubleshooting

### Issue: "HTTPS required" error

**Solution**: The realm may still require SSL. Update via Keycloak admin console:
1. Go to http://localhost:9080/auth
2. Select "mule" realm
3. Go to Realm Settings → Login
4. Set "Require SSL" to "none"
5. Click Save

### Issue: Token validation fails

**Symptoms**: 401 Unauthorized even with valid token

**Solutions**:
1. Check if Keycloak is healthy:
   ```bash
   docker-compose ps keycloak
   ```

2. Verify discovery endpoint:
   ```bash
   curl http://localhost:9080/auth/realms/mule/.well-known/openid-configuration
   ```

3. Check APISIX logs:
   ```bash
   docker-compose logs apisix --tail 50 | grep -i "openid\|jwt\|auth"
   ```

### Issue: Rate limiting not working

**Check if rate limiting is enabled:**

```bash
# Send multiple requests quickly
for i in {1..10}; do
  curl -H "Authorization: Bearer $TOKEN" \
    http://localhost:9080/api/v1/status &
done
wait
```

**Check APISIX error logs:**

```bash
docker-compose logs apisix --tail 100 | grep -i "limit"
```

## Advanced: Custom Claims and Roles

### Accessing User Info in Mule

After successful authentication, APISIX adds headers to the request:

- `X-Consumer-Username`: The authenticated username
- `X-Userinfo`: JWT claims (base64 encoded)

To access these in your Mule flows:

```xml
<set-variable variableName="username"
              value="#[attributes.headers.'X-Consumer-Username']"/>
```

### Adding Custom Roles

1. Go to Keycloak Admin Console
2. Select "mule" realm
3. Go to Roles → Add Role
4. Assign roles to users in Users → Select User → Role Mappings

### Role-Based Access Control in APISIX

You can add role-based authorization by updating the route configuration:

```yaml
# In config/apisix/apisix.yaml
plugins:
  openid-connect:
    # ...existing config...
    scope: "openid profile email roles"
    access_token_in_authorization_header: true

  # Add after openid-connect
  serverless-post-function:
    phase: "access"
    functions:
      - |
        return function(conf, ctx)
          local jwt = require("resty.jwt")
          local auth_header = core.request.header(ctx, "Authorization")
          if not auth_header then
            return 401, {message="Missing authorization header"}
          end

          local token = string.sub(auth_header, 8)  -- Remove "Bearer "
          local jwt_obj = jwt:load_jwt(token)

          if not jwt_obj.valid then
            return 401, {message="Invalid JWT"}
          end

          local roles = jwt_obj.payload.roles or {}
          local has_admin = false
          for _, role in ipairs(roles) do
            if role == "admin" then
              has_admin = true
              break
            end
          end

          if not has_admin then
            return 403, {message="Forbidden: Admin role required"}
          end
        end
```

## Monitoring Authentication

### View Authentication Metrics in Prometheus

```bash
# Access Prometheus
http://localhost:9080/prometheus

# Queries:
# - Total requests with auth: apisix_http_status{route="mule-api-v1"}
# - Rate limit rejections: apisix_http_status{code="429"}
# - Auth failures: apisix_http_status{code="401"}
```

### View in Grafana

```bash
# Access Grafana
http://localhost:9080/grafana

# Default credentials: admin / (check GRAFANA_ADMIN_PASSWORD in .env)

# Create dashboard with:
# - Request rate by user
# - Authentication success/failure rate
# - Rate limit hits
```

## Security Best Practices

### Production Deployment Checklist

- [ ] Change Keycloak admin password
- [ ] Change client secret (`mule-gateway-secret-12345`)
- [ ] Enable HTTPS (SSL/TLS) on APISIX
- [ ] Set `sslRequired: "external"` in Keycloak realm
- [ ] Rotate JWT signing keys regularly
- [ ] Implement token revocation list
- [ ] Enable audit logging in Keycloak
- [ ] Set up alerts for:
  - High rate limit rejection rate
  - Authentication failure spikes
  - Unusual access patterns

### Changing Client Secret

1. Generate new secret:
   ```bash
   openssl rand -hex 32
   ```

2. Update in Keycloak:
   - Admin Console → Clients → mule-api-gateway
   - Credentials tab → Regenerate Secret

3. Update in `config/apisix/apisix.yaml`:
   ```yaml
   client_secret: "<new-secret-here>"
   ```

4. Reload APISIX:
   ```bash
   docker-compose exec apisix apisix reload
   ```

## References

- [Apache APISIX OpenID Connect Plugin](https://apisix.apache.org/docs/apisix/plugins/openid-connect/)
- [Apache APISIX Rate Limiting](https://apisix.apache.org/docs/apisix/plugins/limit-req/)
- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [OAuth 2.0 Grant Types](https://oauth.net/2/grant-types/)
