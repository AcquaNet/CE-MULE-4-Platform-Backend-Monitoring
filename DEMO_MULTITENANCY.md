# Multi-Tenancy Demo Plan

This document demonstrates Document-Level Security (DLS) with OpenSearch.
Two tenants are pre-configured: `acme-corp` and `globex`.

## Credentials Summary

| User | Password | Sees |
|------|----------|------|
| `admin` | `admin` | ALL logs |
| `acme_user` | `AcmePass123!` | Only `acme-corp` logs |
| `globex_user` | `GlobexPass123!` | Only `globex` logs |

---

## 1. Generate Logs for Each Tenant

**Important:** Logs require `auth_token` field for Logstash to accept them.

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

### Option B: Docker with Alpine/Curl (Works everywhere)

```bash
# Auth token (required by Logstash)
AUTH_TOKEN="8fcrQrMcOyWbn6nJdoFzkTpXQGyOHMJw7qcfUotk2v8="

# Send ACME-CORP INFO log
docker run --rm --network ce-base-micronet alpine/curl sh -c \
  "echo '{\"application\":\"ce-mule-base\",\"log_type\":\"mule\",\"level\":\"INFO\",\"message\":\"ACME Order processed\",\"tenant_id\":\"acme-corp\",\"worker_id\":\"demo\",\"auth_token\":\"$AUTH_TOKEN\"}' | nc -w 2 logstash 5000"

# Send ACME-CORP ERROR log
docker run --rm --network ce-base-micronet alpine/curl sh -c \
  "echo '{\"application\":\"ce-mule-base\",\"log_type\":\"mule\",\"level\":\"ERROR\",\"message\":\"ACME Payment failed\",\"tenant_id\":\"acme-corp\",\"worker_id\":\"demo\",\"auth_token\":\"$AUTH_TOKEN\"}' | nc -w 2 logstash 5000"

# Send GLOBEX INFO log
docker run --rm --network ce-base-micronet alpine/curl sh -c \
  "echo '{\"application\":\"ce-mule-base\",\"log_type\":\"mule\",\"level\":\"INFO\",\"message\":\"GLOBEX User login\",\"tenant_id\":\"globex\",\"worker_id\":\"demo\",\"auth_token\":\"$AUTH_TOKEN\"}' | nc -w 2 logstash 5000"

# Send GLOBEX ERROR log
docker run --rm --network ce-base-micronet alpine/curl sh -c \
  "echo '{\"application\":\"ce-mule-base\",\"log_type\":\"mule\",\"level\":\"ERROR\",\"message\":\"GLOBEX DB timeout\",\"tenant_id\":\"globex\",\"worker_id\":\"demo\",\"auth_token\":\"$AUTH_TOKEN\"}' | nc -w 2 logstash 5000"
```

**Wait 2-3 seconds for Logstash to process and index.**

---

## 2. Verify as ADMIN (Sees ALL Tenants)

```bash
# Count ALL logs (admin sees everything)
curl -s -u admin:admin http://localhost:9080/opensearch/mule-logs-*/_count

# Search recent logs
curl -s -u admin:admin "http://localhost:9080/opensearch/mule-logs-*/_search?size=5&sort=@timestamp:desc"

# Aggregation by tenant (shows all tenants)
curl -s -u admin:admin http://localhost:9080/opensearch/mule-logs-*/_search -H "Content-Type: application/json" -d "{\"size\":0,\"aggs\":{\"by_tenant\":{\"terms\":{\"field\":\"tenant_id.keyword\"}}}}"
```

---

## 3. Login as ACME-CORP Tenant (Sees ONLY Their Logs)

**Credentials:** `acme_user` / `AcmePass123!`

```bash
# Count logs (only acme-corp count)
curl -s -u acme_user:AcmePass123! http://localhost:9080/opensearch/mule-logs-*/_count

# Search logs (only acme-corp appears)
curl -s -u acme_user:AcmePass123! "http://localhost:9080/opensearch/mule-logs-*/_search?size=5"

# Try to find GLOBEX logs (BLOCKED - returns 0)
curl -s -u acme_user:AcmePass123! http://localhost:9080/opensearch/mule-logs-*/_search -H "Content-Type: application/json" -d "{\"query\":{\"term\":{\"tenant_id.keyword\":\"globex\"}}}"
```

**Expected:** Search for "globex" returns `"hits":{"total":{"value":0}}`

---

## 4. Login as GLOBEX Tenant (CANNOT See ACME Logs)

**Credentials:** `globex_user` / `GlobexPass123!`

```bash
# Count logs (only globex count)
curl -s -u globex_user:GlobexPass123! http://localhost:9080/opensearch/mule-logs-*/_count

# Search logs (only globex appears)
curl -s -u globex_user:GlobexPass123! "http://localhost:9080/opensearch/mule-logs-*/_search?size=5"

# Try to find ACME logs (BLOCKED - returns 0)
curl -s -u globex_user:GlobexPass123! http://localhost:9080/opensearch/mule-logs-*/_search -H "Content-Type: application/json" -d "{\"query\":{\"term\":{\"tenant_id.keyword\":\"acme-corp\"}}}"
```

**Expected:** Search for "acme-corp" returns `"hits":{"total":{"value":0}}`

---

## 5. Quick Side-by-Side Comparison

```bash
echo "=== ADMIN (all tenants) ===" && curl -s -u admin:admin http://localhost:9080/opensearch/mule-logs-*/_count
echo "=== ACME_USER (only acme-corp) ===" && curl -s -u acme_user:AcmePass123! http://localhost:9080/opensearch/mule-logs-*/_count
echo "=== GLOBEX_USER (only globex) ===" && curl -s -u globex_user:GlobexPass123! http://localhost:9080/opensearch/mule-logs-*/_count
```

**DLS is working when:** Admin count > acme_user count AND Admin count > globex_user count

---

## 6. OpenSearch Dashboards (Web UI)

**URL:** http://localhost:9080/dashboards

| User | Password | What They See |
|------|----------|---------------|
| `admin` | `admin` | ALL data from all tenants |
| `acme_user` | `AcmePass123!` | ONLY acme-corp logs |
| `globex_user` | `GlobexPass123!` | ONLY globex logs |

### Steps to Verify:
1. Open http://localhost:9080/dashboards
2. Login as `admin` / `admin`
3. Go to **Discover** > Select `mule-logs-*` index
4. Note the total document count
5. Logout and login as `acme_user` / `AcmePass123!`
6. Go to **Discover** > Same index shows FEWER documents
7. All visible documents have `tenant_id: acme-corp`

---

## 7. Full Demo Script (Copy-Paste Ready)

```bash
# ============================================
# STEP 1: Generate logs for both tenants
# ============================================
AUTH_TOKEN="8fcrQrMcOyWbn6nJdoFzkTpXQGyOHMJw7qcfUotk2v8="

echo "Sending ACME logs..."
docker run --rm --network ce-base-micronet alpine/curl sh -c "echo '{\"application\":\"demo\",\"log_type\":\"mule\",\"level\":\"INFO\",\"message\":\"ACME demo log 1\",\"tenant_id\":\"acme-corp\",\"auth_token\":\"$AUTH_TOKEN\"}' | nc -w 2 logstash 5000"
docker run --rm --network ce-base-micronet alpine/curl sh -c "echo '{\"application\":\"demo\",\"log_type\":\"mule\",\"level\":\"ERROR\",\"message\":\"ACME demo log 2\",\"tenant_id\":\"acme-corp\",\"auth_token\":\"$AUTH_TOKEN\"}' | nc -w 2 logstash 5000"

echo "Sending GLOBEX logs..."
docker run --rm --network ce-base-micronet alpine/curl sh -c "echo '{\"application\":\"demo\",\"log_type\":\"mule\",\"level\":\"INFO\",\"message\":\"GLOBEX demo log 1\",\"tenant_id\":\"globex\",\"auth_token\":\"$AUTH_TOKEN\"}' | nc -w 2 logstash 5000"
docker run --rm --network ce-base-micronet alpine/curl sh -c "echo '{\"application\":\"demo\",\"log_type\":\"mule\",\"level\":\"ERROR\",\"message\":\"GLOBEX demo log 2\",\"tenant_id\":\"globex\",\"auth_token\":\"$AUTH_TOKEN\"}' | nc -w 2 logstash 5000"

echo "Waiting for indexing..."
sleep 3

# ============================================
# STEP 2: Compare counts
# ============================================
echo ""
echo "=== ADMIN sees ALL ==="
curl -s -u admin:admin http://localhost:9080/opensearch/mule-logs-*/_count

echo ""
echo "=== ACME_USER sees only acme-corp ==="
curl -s -u acme_user:AcmePass123! http://localhost:9080/opensearch/mule-logs-*/_count

echo ""
echo "=== GLOBEX_USER sees only globex ==="
curl -s -u globex_user:GlobexPass123! http://localhost:9080/opensearch/mule-logs-*/_count

# ============================================
# STEP 3: Verify isolation
# ============================================
echo ""
echo "=== ACME_USER searching for GLOBEX logs (should be 0) ==="
curl -s -u acme_user:AcmePass123! http://localhost:9080/opensearch/mule-logs-*/_search -H "Content-Type: application/json" -d '{"query":{"term":{"tenant_id.keyword":"globex"}}}'

echo ""
echo "=== GLOBEX_USER searching for ACME logs (should be 0) ==="
curl -s -u globex_user:GlobexPass123! http://localhost:9080/opensearch/mule-logs-*/_search -H "Content-Type: application/json" -d '{"query":{"term":{"tenant_id.keyword":"acme-corp"}}}'
```

---

## 8. How DLS Works

Each tenant role has a Document-Level Security query filter:

**Role `tenant_acme-corp`:**
```json
{
  "index_permissions": [{
    "index_patterns": ["mule-logs-*", "logstash-*"],
    "dls": "{\"term\": {\"tenant_id\": \"acme-corp\"}}",
    "allowed_actions": ["read", "search"]
  }]
}
```

This query is **automatically applied** to every search, making it impossible to see other tenants' data.

---

## 9. Mule API Integration

When Mule workers are running, the `X-Tenant-ID` header tags all generated logs:

```bash
# API call tagged as acme-corp (generates logs with tenant_id=acme-corp)
curl -H "X-Tenant-ID: acme-corp" http://localhost:9080/api/v1/status

# API call tagged as globex (generates logs with tenant_id=globex)
curl -H "X-Tenant-ID: globex" http://localhost:9080/api/v1/status
```

---

## Summary

| Feature | Status |
|---------|--------|
| Document-Level Security | **FREE** with OpenSearch |
| Tenant Isolation | Complete - no cross-tenant visibility |
| Authentication Required | Yes (`auth_token` in logs) |
| UI Support | OpenSearch Dashboards respects DLS |
| API Support | curl with Basic Auth |

**Key URLs:**
- OpenSearch API: `http://localhost:9080/opensearch`
- Dashboards UI: `http://localhost:9080/dashboards`
- Logstash TCP: `localhost:9100` (via APISIX stream proxy)
