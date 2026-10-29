# Multi-Tenancy

Each log event carries a `tenant_id`. OpenSearch Document-Level Security (DLS) roles restrict tenant users to
their own documents, in the REST API and in Dashboards alike. The DLS feature is part of the OpenSearch security
plugin and needs no extra license.

## How the tenant is set

```
Keycloak user: attribute tenant_id (set by an admin, read-only for the user; or via a tenants/<group>)
   -> access token claim tenant_id (client mule-api-gateway)
APISIX: drops any client X-Tenant-ID, sets X-Tenant-ID from the verified claim
Mule app: puts it in the log context (ThreadContext tenant_id) and on the root span (tenant.id)
log4j2 "logs" appender: tenant_id = $${ctx:tenant_id:-unknown}
Fluent Bit: cleans it (lowercase, letters/digits/_/-), missing -> unknown, raw value in tenant_id_original
OpenSearch: tenant_id (keyword) in mule-logs-* / logstash-*
DLS role tenant_<id>: {"term": {"tenant_id": "<id>"}}
```

A caller cannot pick a tenant: the header comes only from the token (gateway checks:
[JWT_AUTHENTICATION_GUIDE.md](JWT_AUTHENTICATION_GUIDE.md)), and users cannot edit `tenant_id`
(realm user profile in `mule-realm.json`: `tenant_id` is single-valued, users can view it, only admins edit it). An
admin sets it in the admin console (`https://localhost:9443/auth/admin/mule/console/`). Use the Users > Attributes tab, or add the user
to a group under `tenants` that carries the attribute. The seeded groups are `tenant-default` and `tenant-demo`.

Logs that other systems send directly to Fluent Bit (CloudHub, scripts) set `tenant_id` in the event themselves.
Anyone holding `LOG_INGEST_TOKEN` can do that.

## Roles and users in OpenSearch

`scripts/setup-opensearch.sh` runs on every OpenSearch start. It creates the index templates and the DLS roles
`tenant_acme-corp` and `tenant_globex` (plus `tenant_viewer_template`, which has no DLS filter). OpenSearch has one
built-in user, `admin` / `OPENSEARCH_ADMIN_PASSWORD`, and no tenant users until you add them.

`config/scripts/tenants/manage-tenants.sh` reads `.env` itself and talks to OpenSearch at
`http://localhost:9080/opensearch`:

```bash
./config/scripts/tenants/manage-tenants.sh create acme-corp                                   # role tenant_acme-corp
./config/scripts/tenants/manage-tenants.sh create acme-corp --user acme_user --password '<choose>'   # + user with that role
./config/scripts/tenants/manage-tenants.sh list
./config/scripts/tenants/manage-tenants.sh verify acme-corp
./config/scripts/tenants/manage-tenants.sh info acme-corp
./config/scripts/tenants/manage-tenants.sh delete acme-corp [--force]                         # role + its users
```

Tenant ids are lowercase letters, digits, `_` and `-`, so they match what Fluent Bit stores. Leave out
`--password` to get a generated one. `create` also adds a Keycloak group `tenants/tenant-<id>` when it can reach
Keycloak's admin API at `KEYCLOAK_URL` (default `http://localhost:9080`: the master realm is served on 9080 only). If not, it skips that step, and you create the group in the admin
console.

A tenant role looks like this:

```json
{
  "cluster_permissions": ["cluster_composite_ops_ro"],
  "index_permissions": [{
    "index_patterns": ["mule-logs-*", "logstash-*"],
    "dls": "{\"term\": {\"tenant_id\": \"acme-corp\"}}",
    "allowed_actions": ["read"]
  }]
}
```

## Keycloak (SSO) users

Dashboards signs in with Keycloak, and OpenSearch accepts the Keycloak ID token (openid auth domain, written by
`scripts/setup-opensearch.sh`, only tokens issued to client `dashboards`: `required_audience`; basic auth for internal
users stays). The token's `roles` claim gives the backend roles: `admin` -> `all_access`; `user` -> `kibana_user` plus
`sso_tenant_logs` (DLS `{"term": {"tenant_id": "${attr.jwt.tenant_id}"}}`, Global Dashboards tenant read-only). A Keycloak user therefore sees only the logs of its own
`tenant_id` attribute, with no OpenSearch user per tenant. `manage-tenants.sh --user` is still the way to get internal users for direct API access.

## Check isolation

```bash
set -a; . ./.env; set +a
OS=http://localhost:9080/opensearch
curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "$OS/mule-logs-*/_count"          # everything
curl -sk -u "acme_user:<password>" "$OS/mule-logs-*/_count"                      # only acme-corp
curl -sk -u "acme_user:<password>" "$OS/mule-logs-*/_search" -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"tenant_id":"globex"}}}'                                 # 0 hits
```

In Dashboards (`https://localhost:9443/dashboards/`, Keycloak sign-in), a non-admin user sees only their tenant's
documents in Discover. For a
full walkthrough with two tenants, see [DEMO_MULTITENANCY.md](../DEMO_MULTITENANCY.md).

## Problems

| Symptom | Check |
|---------|-------|
| Logs have `tenant_id: unknown` | The token has no `tenant_id` claim (the user has no attribute or group), the event was sent without one, or the app doesn't call its tenant extraction |
| `tenant_id_original` is present | The sent value had other characters or was the wrong length; the cleaned value is in `tenant_id` |
| A tenant user sees nothing | The role's DLS value must equal the stored `tenant_id` exactly (lowercase); check `manage-tenants.sh info <id>` |
| A tenant user sees other tenants | The user also has a broader role (e.g. `all_access`); check `$OS/_plugins/_security/api/internalusers/<user>` as admin |
