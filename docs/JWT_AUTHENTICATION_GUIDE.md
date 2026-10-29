# JWT Authentication and Rate Limits

`/api/*` and every per-app route set in the Runtime Manager are protected at the gateway by Keycloak (realm `mule`)
tokens. This needs the `auth` profile and `GATEWAY_AUTH=on` (the default).

```
client --Bearer token--> APISIX
   1. openid-connect: verifies the token (Keycloak JWKS)             -> 401 if missing/invalid
   2. token check: azp = mule-api-gateway AND client role api-access -> 403 otherwise
   3. client X-Tenant-ID, X-ID-Token, X-Userinfo, X-Access-Token removed; X-Tenant-ID set from the tenant_id claim
   4. limit-count 100/min per IP (429); on /api/* also limit-conn 20 + burst 10 per IP (503)
   --> round-robin to the app's pool workers
```

All of this is defined in `config/apisix/apisix.yaml`: routes `mule-api-v1` and `mule-api-all`, and the
plugin config `mule-api-auth` for per-app routes.

## Get a token

The client `mule-api-gateway` allows only the password grant (no browser flow, no redirect URIs). It has no service account, so the client-credentials
grant does not work: services use a Keycloak user that has the role.

```bash
set -a; . ./.env; set +a
TOKEN=$(curl -sk https://localhost:9443/auth/realms/mule/protocol/openid-connect/token \
  -d grant_type=password -d client_id=mule-api-gateway -d "client_secret=$MULE_GATEWAY_CLIENT_SECRET" \
  -d username=admin -d "password=$KEYCLOAK_REALM_ADMIN_PASSWORD" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')

curl -sk -H "Authorization: Bearer $TOKEN" https://localhost:9443/api/v1/status   # 200
curl -sk https://localhost:9443/api/v1/status                                       # 401
```

A token from any other client (e.g. `admin-cli`, `dashboards`) is rejected with 403, even for the same user.
Tokens live 3600 s.

## Realm contents (`config/keycloak/realms/mule-realm.json`)

| Item | Value |
|------|-------|
| Client `mule-api-gateway` | confidential, secret `MULE_GATEWAY_CLIENT_SECRET`; client role `api-access` |
| Client `runtime-manager` | Runtime Manager sign-in (secret `RM_OIDC_CLIENT_SECRET`, realm role `admin` required) |
| Client `dashboards` | OpenSearch Dashboards sign-in (secret `DASHBOARDS_OIDC_CLIENT_SECRET`; token claim `roles`) |
| Client `gateway-sso` | APISIX gateway SSO: home page, `/jaeger`, `/prometheus`, `/activemq` (secret `GATEWAY_SSO_CLIENT_SECRET`) |
| Client `grafana` | Grafana sign-in (secret `GRAFANA_OIDC_CLIENT_SECRET`, realm role `admin` required) |
| User `admin` | password `KEYCLOAK_REALM_ADMIN_PASSWORD`; realm roles `user`, `admin`; `api-access`; `realm-admin`; `tenant_id=default` |
| User `developer` | password `KEYCLOAK_REALM_DEV_PASSWORD`; realm role `user`; `api-access`; `tenant_id=demo` |
| Groups | `tenants/tenant-default`, `tenants/tenant-demo` (attribute `tenant_id`) |

The realm, clients, users and secrets are imported only into an **empty** Keycloak database (new clients reach an
existing install only by re-import, partial import or the admin console). After that, manage them as realm user
`admin` (`realm-admin`) at `https://localhost:9443/auth/admin/mule/console/`. The master realm (`KEYCLOAK_ADMIN_USER` /
`KEYCLOAK_ADMIN_PASSWORD`) answers on 9080 only, 404 on 9443: its console is http://localhost:9080/auth/admin/master/console/.

To give a user API access, open Users > the user > Role mapping > Assign role > filter by clients >
`mule-api-gateway` `api-access`. Set their tenant with the `tenant_id` attribute or a `tenants/...` group. Users
cannot change `tenant_id` themselves: the realm user profile declares it single-valued, viewable by users and
editable only by admins, because the gateway trusts that claim.

## The tenant in Mule

APISIX always sets `X-Tenant-ID` from the token, and a header sent by the client is dropped. The Mule app reads it
into the log context (`tenant_id` in every log line) and into the root span (`tenant.id`). For a token without a
`tenant_id` claim the app gets no `X-Tenant-ID` and falls back to its default (`unknown`). See
[MULTITENANCY_SETUP.md](MULTITENANCY_SETUP.md).

## Changing limits

Edit `limit-count` / `limit-conn` under the routes (and `plugin_configs` > `mule-api-auth` for per-app routes)
in `config/apisix/apisix.yaml` and save. APISIX hot-reloads it within about 2 s. The limits are keyed on
`remote_addr`, so all clients behind one NAT or proxy share a single budget.

## Rotating the client secret

1. Admin console > Clients > `mule-api-gateway` > Credentials > Regenerate.
2. Put the new value in `MULE_GATEWAY_CLIENT_SECRET` in `.env`.
3. Run `docker compose up -d`. This recreates APISIX, which renders the secret into its config.

## Problems

| Symptom | Check |
|---------|-------|
| 401 with a fresh token | Is Keycloak healthy? (`docker compose ps keycloak`; the first start in production mode takes minutes) |
| 403 | `azp` of the token (decode its middle part) and `resource_access.mule-api-gateway.roles` |
| 429 | 100 requests/min per IP exceeded |
| Token request fails although the password is right | Brute-force lockout (10 failures, 60 s growing to 15 min); clear it in the realm admin console |
| Everything 401 on a lite install | Without the `auth` profile, set `GATEWAY_AUTH=off` |
| APISIX auth errors | `docker compose logs apisix --tail 100 \| grep -i "openid\|auth"` |
