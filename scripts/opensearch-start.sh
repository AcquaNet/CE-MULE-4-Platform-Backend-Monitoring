#!/bin/bash
# OpenSearch entrypoint (docker-compose.yml): security without the demo installer.
# The demo config ships fixed, public certificates (kirk/esnode: anyone holding them is superadmin or a cluster node)
# and users with published passwords. Instead, on first start: a self-signed node certificate made here (keytool,
# the image has no openssl) and one internal user, admin, with OPENSEARCH_ADMIN_PASSWORD.
# No admin certificate (admin_dn) at all: everything goes through the REST API as admin.
set -e
OS=/usr/share/opensearch
CFG=$OS/config
STORE=$OS/data/.certs        # persisted in the data volume; the security plugin only reads files under config/
: "${OPENSEARCH_INITIAL_ADMIN_PASSWORD:?OPENSEARCH_INITIAL_ADMIN_PASSWORD not set}"

if [ ! -f "$STORE/node.p12" ]; then
    mkdir -p "$STORE" && chmod 700 "$STORE"
    head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$STORE/pass"
    pw=$(cat "$STORE/pass")
    # one self-signed cert for transport + HTTP; the truststore holds just that cert (single node)
    keytool -genkeypair -alias node -keyalg RSA -keysize 2048 -validity 3650 -dname "CN=opensearch" \
        -ext san=dns:opensearch,dns:localhost,ip:127.0.0.1 -ext eku=serverAuth,clientAuth \
        -ext ku=digitalSignature,keyEncipherment -storetype PKCS12 -keystore "$STORE/node.p12" -storepass "$pw"
    keytool -exportcert -alias node -keystore "$STORE/node.p12" -storepass "$pw" -file "$STORE/node.crt"
    keytool -importcert -noprompt -alias node -file "$STORE/node.crt" -storetype PKCS12 \
        -keystore "$STORE/trust.p12" -storepass "$pw"
fi
pw=$(cat "$STORE/pass")
mkdir -p "$CFG/certs" "$OS/data/snapshots"   # snapshots: inside the data volume (the only dir uid 1000 can write)
cp "$STORE/node.p12" "$STORE/trust.p12" "$CFG/certs/"

cat > "$CFG/opensearch.yml" <<EOF
cluster.name: docker-cluster
network.host: 0.0.0.0
plugins.security.ssl.transport.keystore_type: PKCS12
plugins.security.ssl.transport.keystore_filepath: certs/node.p12
plugins.security.ssl.transport.keystore_password: $pw
plugins.security.ssl.transport.keystore_keypassword: $pw
plugins.security.ssl.transport.truststore_type: PKCS12
plugins.security.ssl.transport.truststore_filepath: certs/trust.p12
plugins.security.ssl.transport.truststore_password: $pw
plugins.security.ssl.transport.enforce_hostname_verification: false
plugins.security.ssl.http.enabled: true
plugins.security.ssl.http.keystore_type: PKCS12
plugins.security.ssl.http.keystore_filepath: certs/node.p12
plugins.security.ssl.http.keystore_password: $pw
plugins.security.ssl.http.keystore_keypassword: $pw
plugins.security.ssl.http.truststore_type: PKCS12
plugins.security.ssl.http.truststore_filepath: certs/trust.p12
plugins.security.ssl.http.truststore_password: $pw
plugins.security.nodes_dn: ["CN=opensearch"]
plugins.security.allow_default_init_securityindex: true
plugins.security.restapi.roles_enabled: ["all_access", "security_rest_api_access"]
plugins.security.enable_snapshot_restore_privilege: true
plugins.security.check_snapshot_restore_write_privileges: true
plugins.security.system_indices.enabled: true
# setup-opensearch.sh writes the auth config (Keycloak openid domain) through the REST API on every start
plugins.security.unsupported.restapi.allow_securityconfig_modification: true
# a role without DLS (all_access) beats a DLS role: realm admins also carry role user (tenant DLS)
plugins.security.dfm_empty_overrides_all: true
path.repo: ["/usr/share/opensearch/data/snapshots"]
# single node: a replica can never be placed (cluster yellow); also covers system indices the plugins create
# (.opendistro-job-scheduler-lock, ...), which admin may not change afterwards
cluster.default_number_of_replicas: 0
plugins.index_state_management.history.number_of_replicas: 0
EOF
chmod 600 "$CFG/opensearch.yml"

# read only when the security index is first created (empty data volume): admin is the only user
hash=$(OPENSEARCH_JAVA_HOME=$OS/jdk bash $OS/plugins/opensearch-security/tools/hash.sh -p "$OPENSEARCH_INITIAL_ADMIN_PASSWORD" | tail -n 1)
cat > "$CFG/opensearch-security/internal_users.yml" <<EOF
_meta:
  type: "internalusers"
  config_version: 2
admin:
  hash: "$hash"
  reserved: true
  backend_roles: ["admin"]
  description: "admin (OPENSEARCH_ADMIN_PASSWORD)"
EOF

# index templates + tenant roles once the cluster answers (idempotent, every start)
bash $OS/setup-opensearch.sh &
exec $OS/opensearch-docker-entrypoint.sh opensearch
