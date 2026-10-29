# Multi-Tenancy Demo Plan

This document demonstrates Document-Level Security (DLS) with OpenSearch.
It uses two tenants, `acme-corp` and `globex`. Their DLS roles (`tenant_acme-corp`, `tenant_globex`) already exist:
`scripts/setup-opensearch.sh` creates them on every OpenSearch start. Only the users are missing, and there are no known
passwords: create the users first (pick the passwords yourself), and load the admin password from `.env`.

```bash
set -a; . ./.env; set +a            # OPENSEARCH_ADMIN_PASSWORD, LOG_INGEST_TOKEN, ...
ACME_PASS='<choose one>'; GLOBEX_PASS='<choose one>'
./config/scripts/tenants/manage-tenants.sh create acme-corp --user acme_user --password "$ACME_PASS"
./config/scripts/tenants/manage-tenants.sh create globex --user globex_user --password "$GLOBEX_PASS"
```

## Credentials Summary

| User | Password | Sees |
|------|----------|------|
| `admin` | `$OPENSEARCH_ADMIN_PASSWORD` (.env) | ALL logs |
| `acme_user` | `$ACME_PASS` (your choice) | Only `acme-corp` logs |
| `globex_user` | `$GLOBEX_PASS` (your choice) | Only `globex` logs |

---

## 1. Generate Logs for Each Tenant

**Important:** Logs require an `auth_token` field (= `LOG_INGEST_TOKEN` in `.env`) or Fluent Bit drops them.

### Option A: PowerShell Script (Recommended for Windows)

```powershell
# Send ACME-CORP logs
.\send-log.ps1 -TenantId "acme-corp" -Level "INFO" -Message "ACME Order processed successfully"
.\send-log.ps1 -TenantId "acme-corp" -Level "ERROR" -Message "ACME Payment gateway timeout"
.\send-log.ps1 -TenantId "acme-corp" -Level "WARN" -Message "ACME Low inventory alert"

# Send GLOBEX logs
.\send-log.ps1 -TenantId "globex" -Level "INFO" -Message "GLOBEX User login successful"
.\send-log.ps1 -TenantId "globex" -Level "ERROR" -Message "GLOBEX Database connection failed"
```

### Option B: Docker (works everywhere)

```bash
AUTH_TOKEN=$(sed -n 's/^LOG_INGEST_TOKEN=//p' .env)    # required by Fluent Bit
for ev in "acme-corp INFO ACME_Order_processed" "acme-corp ERROR ACME_Payment_failed" \
          "globex INFO GLOBEX_User_login" "globex ERROR GLOBEX_DB_timeout"; do
  set -- $ev
  docker run --rm --network ce-base-micronet alpine/curl sh -c \
    "echo '{\"application\":\"ce-mule-base\",\"log_type\":\"mule\",\"level\":\"$2\",\"message\":\"$3\",\"tenant_id\":\"$1\",\"worker_id\":\"demo\",\"auth_token\":\"$AUTH_TOKEN\"}' | nc -w 2 log-ingest 5000"
done
```

**Wait 6 seconds (`sleep 6`): the index refresh interval is 5 s.**

---

## 2. Verify as ADMIN (Sees ALL Tenants)

```bash
# Count ALL logs (admin sees everything)
curl -s -u "admin:$OPENSEARCH_ADMIN_PASSWORD" http://localhost:9080/opensearch/mule-logs-*/_count

# Search recent logs
curl -s -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "http://localhost:9080/opensearch/mule-logs-*/_search?size=5&sort=@timestamp:desc"

# Aggregation by tenant (shows all tenants)
curl -s -u "admin:$OPENSEARCH_ADMIN_PASSWORD" http://localhost:9080/opensearch/mule-logs-*/_search -H "Content-Type: application/json" -d "{\"size\":0,\"aggs\":{\"by_tenant\":{\"terms\":{\"field\":\"tenant_id\"}}}}"
```

---

## 3. Login as ACME-CORP Tenant (Sees ONLY Their Logs)

**Credentials:** `acme_user` / `$ACME_PASS` (your choice)

```bash
# Count logs (only acme-corp count)
curl -s -u "acme_user:$ACME_PASS" http://localhost:9080/opensearch/mule-logs-*/_count

# Search logs (only acme-corp appears)
curl -s -u "acme_user:$ACME_PASS" "http://localhost:9080/opensearch/mule-logs-*/_search?size=5"

# Try to find GLOBEX logs (BLOCKED - returns 0)
curl -s -u "acme_user:$ACME_PASS" http://localhost:9080/opensearch/mule-logs-*/_search -H "Content-Type: application/json" -d "{\"query\":{\"term\":{\"tenant_id\":\"globex\"}}}"
```

**Expected:** Search for "globex" returns `"hits":{"total":{"value":0}}`

---

## 4. Login as GLOBEX Tenant (CANNOT See ACME Logs)

**Credentials:** `globex_user` / `$GLOBEX_PASS` (your choice)

```bash
# Count logs (only globex count)
curl -s -u "globex_user:$GLOBEX_PASS" http://localhost:9080/opensearch/mule-logs-*/_count

# Search logs (only globex appears)
curl -s -u "globex_user:$GLOBEX_PASS" "http://localhost:9080/opensearch/mule-logs-*/_search?size=5"

# Try to find ACME logs (BLOCKED - returns 0)
curl -s -u "globex_user:$GLOBEX_PASS" http://localhost:9080/opensearch/mule-logs-*/_search -H "Content-Type: application/json" -d "{\"query\":{\"term\":{\"tenant_id\":\"acme-corp\"}}}"
```

**Expected:** Search for "acme-corp" returns `"hits":{"total":{"value":0}}`

---

## 5. Quick Side-by-Side Comparison

```bash
echo "=== ADMIN (all tenants) ===" && curl -s -u "admin:$OPENSEARCH_ADMIN_PASSWORD" http://localhost:9080/opensearch/mule-logs-*/_count
echo "=== ACME_USER (only acme-corp) ===" && curl -s -u "acme_user:$ACME_PASS" http://localhost:9080/opensearch/mule-logs-*/_count
echo "=== GLOBEX_USER (only globex) ===" && curl -s -u "globex_user:$GLOBEX_PASS" http://localhost:9080/opensearch/mule-logs-*/_count
```

**DLS is working when:** Admin count > acme_user count AND Admin count > globex_user count

---

## 6. OpenSearch Dashboards (Web UI)

**URL:** https://localhost:9443/dashboards/ (Keycloak sign-in; `http://localhost:9080` can't sign in). The
OpenSearch users above are for the REST API; a Keycloak user sees the logs of its `tenant_id` attribute.

### Steps to Verify:
1. Open https://localhost:9443/dashboards/
2. Sign in as Keycloak `admin` / `$KEYCLOAK_REALM_ADMIN_PASSWORD` (realm role `admin`: all logs)
3. Go to **Discover** > Select `mule-logs-*` index
4. Note the total document count
5. Sign out (https://localhost:9443/logout and Dashboards' own sign-out), sign in as `developer` / `$KEYCLOAK_REALM_DEV_PASSWORD`
6. Go to **Discover** > Same index shows FEWER documents
7. All visible documents have `tenant_id: demo` (for `acme-corp`, use a Keycloak user with `tenant_id=acme-corp`)

---

## 7. How DLS Works

Each `tenant_<id>` role has a DLS filter `{"term": {"tenant_id": "<id>"}}` applied to every search. Details:
[docs/MULTITENANCY_SETUP.md](docs/MULTITENANCY_SETUP.md).

---

## 8. Mule API Integration

When Mule workers are running, the tenant of the generated logs comes only from the verified token's `tenant_id`
claim: APISIX drops any `X-Tenant-ID` the client sends and sets it from the token. The tenant is the Keycloak user
attribute `tenant_id` (set by an admin, read-only for the user); the token must also carry the client role
`api-access` of `mule-api-gateway`.

```bash
# Token for a Keycloak user whose tenant_id attribute is acme-corp (or globex)
TOKEN=$(curl -sk -X POST https://localhost:9443/auth/realms/mule/protocol/openid-connect/token \
  -d grant_type=password -d client_id=mule-api-gateway -d "client_secret=$MULE_GATEWAY_CLIENT_SECRET" \
  -d username=<user> -d "password=<password>" | jq -r .access_token)

# API call tagged with the user's tenant (generates logs with that tenant_id)
curl -H "Authorization: Bearer $TOKEN" http://localhost:9080/api/v1/status
```

---

## Summary

| Feature | Status |
|---------|--------|
| Document-Level Security | included in OpenSearch (security plugin) |
| Tenant Isolation | Complete - no cross-tenant visibility |
| Authentication Required | Yes (`auth_token` in logs) |
| UI Support | OpenSearch Dashboards respects DLS |
| API Support | curl with Basic Auth |

**Key URLs:**
- OpenSearch API: `http://localhost:9080/opensearch`
- Dashboards UI: `https://localhost:9443/dashboards/` (Keycloak sign-in)
- Log ingestion (Fluent Bit) TCP: `localhost:9100` (via APISIX stream proxy)
