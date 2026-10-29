#!/bin/sh
# APISIX entrypoint wrapper (standalone mode).
#
# config/apisix/apisix.yaml (routes, upstreams, plugin_configs) is the ONLY route source.
# This script builds the live conf/apisix.yaml from it plus the TLS cert in certs/apisix,
# then re-renders whenever either changes, so APISIX hot-reloads edits, git pulls,
# Runtime Manager deployments and cert renewals without a restart. With no cert yet (fresh
# clone) it creates a local CA + localhost cert first, so HTTPS on 9443 always works.
# Mounts: config/apisix -> /apisix-src (dir, not file: a single-file bind goes stale
# when git/editors replace the file), certs -> /certs (read-write: the first-start cert).

SRC=/apisix-src/apisix.yaml
OUT=/usr/local/apisix/conf/apisix.yaml
CERT=/certs/apisix/apisix.crt
KEY=/certs/apisix/apisix.key

# Fresh clone: a local CA (certs/ca, trust ca.crt or curl --cacert it) and a localhost cert signed by
# it. config/scripts/setup/generate-certs.sh adds names (GATEWAY_HOSTNAMES); Let's Encrypt replaces it.
ensure_cert() {
    if [ -f "$CERT" ] && [ -f "$KEY" ]; then
        # GATEWAY_HOSTNAMES changed: re-issue the leaf from the same local CA (only a generated cert, never a replaced one)
        missing=""
        for h in $(echo "${GATEWAY_HOSTNAMES:-}" | tr ',' ' '); do
            openssl x509 -in "$CERT" -noout -ext subjectAltName 2>/dev/null | grep -qE "(DNS|IP Address):$h(,|$)" || missing="$missing $h"
        done
        if [ -z "$missing" ] || ! openssl x509 -in "$CERT" -noout -issuer 2>/dev/null | grep -q "CE Platform Local CA" \
            || [ ! -f /certs/ca/ca.key ]; then
            return
        fi
        echo "gateway certificate lacks$missing (GATEWAY_HOSTNAMES): re-issuing it from the local CA"
        rm -f "$CERT" "$KEY"
    fi
    mkdir -p /certs/ca /certs/apisix || return
    if [ -f /certs/ca/ca.key ]; then echo "issuing the gateway certificate from the local CA (certs/ca)"
    else echo "no gateway certificate yet: creating a local CA (certs/ca) and a certificate signed by it"; fi
    # explicit config: `req -x509` would otherwise add its default CA extensions too, and a duplicated
    # basicConstraints makes OpenSSL 3 (Linux clients) reject the whole chain
    printf '[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=CE Platform Local CA\n[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n' > /tmp/ca.cnf
    printf '[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=localhost\n' > /tmp/leaf.cnf
    # digitalSignature is required: Chrome rejects RSA server certs without it (ERR_SSL_KEY_USAGE_INCOMPATIBLE)
    # GATEWAY_HOSTNAMES: extra names/IPs (comma-separated) the platform is reached at, e.g. by worker nodes
    san="DNS:localhost,DNS:apisix,IP:127.0.0.1"
    for h in $(echo "${GATEWAY_HOSTNAMES:-}" | tr ',' ' '); do
        case "$h" in *[!0-9.]*) san="$san,DNS:$h" ;; *) san="$san,IP:$h" ;; esac
    done
    printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n' "$san" > /tmp/san.ext
    if [ ! -f /certs/ca/ca.key ]; then
        openssl req -x509 -newkey rsa:4096 -nodes -days 3650 -config /tmp/ca.cnf -extensions ca \
            -keyout /certs/ca/ca.key -out /certs/ca/ca.crt 2>/dev/null || return
        chmod 600 /certs/ca/ca.key
    fi
    openssl req -newkey rsa:2048 -nodes -config /tmp/leaf.cnf -keyout "$KEY" -out /tmp/apisix.csr 2>/dev/null &&
        openssl x509 -req -in /tmp/apisix.csr -CA /certs/ca/ca.crt -CAkey /certs/ca/ca.key -CAcreateserial \
            -days 825 -extfile /tmp/san.ext -out "$CERT" 2>/dev/null
    chmod 644 "$KEY" "$CERT" 2>/dev/null
    rm -f /tmp/ca.cnf /tmp/leaf.cnf /tmp/san.ext /tmp/apisix.csr /certs/ca/ca.srl
}

# GATEWAY_AUTH=off (lite install without the Keycloak `auth` profile): drop every
# openid-connect plugin block (and the token-checking serverless-post-function after it) so /api/* is served
# without auth instead of failing.
auth_filter() {
    if [ "${GATEWAY_AUTH:-on}" = "off" ]; then
        awk 'skip && /^ *$/ {next}
             skip { match($0, /^ */); if (RLENGTH > ind) next; skip = 0 }
             /^ *(openid-connect|serverless-post-function):/ { match($0, /^ */); ind = RLENGTH; skip = 1; next }
             { print }' | sed 's/^\( *plugin_config_id: \)"sso-admin"/\1"ops-basic"/'   # SSO'd ops UIs -> basic-auth
    else
        cat
    fi
}

sans() {
    names=$(openssl x509 -in "$CERT" -noout -ext subjectAltName 2>/dev/null | grep -o 'DNS:[^,]*' | cut -c5- | sort -u)
    [ -n "$names" ] || names=localhost
    printf '%s\n' $names | sed 's/.*/"&"/' | paste -sd, -
}

# key of the /otlp consumer; unset -> a random one, so the route stays closed rather than open
OTLP_KEY=${OTLP_INGEST_TOKEN:-$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')}
# Keycloak mule-api-gateway client secret (the realm import gets the same value)
GW_SECRET=${MULE_GATEWAY_CLIENT_SECRET:-$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')}
# basic-auth password of consumer ops (/jaeger, /prometheus, /activemq with GATEWAY_AUTH=off)
OPS_PW=${GATEWAY_OPS_PASSWORD:-$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')}
# single sign-on: Keycloak gateway-sso client secret and the session cookie key (random = sign-in lost on restart)
SSO_SECRET=${GATEWAY_SSO_CLIENT_SECRET:-$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')}
SESSION_SECRET=${GATEWAY_SESSION_SECRET:-$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')}
# /activemq signs in to the ActiveMQ console as admin
AMQ_BASIC=$(printf 'admin:%s' "${ACTIVEMQ_ADMIN_PASSWORD:-}" | base64 -w0)

render() {
    [ "${GATEWAY_AUTH:-on}" = "off" ] && echo "WARN: GATEWAY_AUTH=off, /api/* routes have NO authentication" >&2
    {
        grep -v '^#END' "$SRC" | auth_filter | sed -e "s|\${OTLP_INGEST_TOKEN}|$OTLP_KEY|g" -e "s|\${MULE_GATEWAY_CLIENT_SECRET}|$GW_SECRET|g" -e "s|\${GATEWAY_OPS_PASSWORD}|$OPS_PW|g" \
            -e "s|\${GATEWAY_SSO_CLIENT_SECRET}|$SSO_SECRET|g" -e "s|\${GATEWAY_SESSION_SECRET}|$SESSION_SECRET|g" \
            -e "s|\${ACTIVEMQ_BASIC_AUTH}|$AMQ_BASIC|g"
        if [ -f "$CERT" ] && [ -f "$KEY" ]; then
            echo 'ssls:'
            echo '  - id: "default"'
            # every DNS name in the cert (localhost/apisix + GATEWAY_HOSTNAMES, or a Let's Encrypt domain);
            # clients sending no SNI (plain IPs) get it via ssl.fallback_sni
            echo "    snis: [$(sans)]"
            echo '    cert: |'
            sed 's/^/      /' "$CERT"
            echo '    key: |'
            sed 's/^/      /' "$KEY"
        else
            echo "WARN: $CERT not found, HTTPS on 9443 disabled (run config/scripts/setup/generate-certs.sh)" >&2
        fi
        echo '#END'
    } > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"   # atomic: APISIX never reads a half-written file
    echo "apisix.yaml rendered"
}

sig() { cat "$SRC" "$CERT" "$KEY" 2>/dev/null | cksum; }

ensure_cert
render
last=$(sig)
# ponytail: 2s polling, no inotify in the image; fine for a config file
(
    while sleep 2; do
        now=$(sig)
        [ "$now" != "$last" ] && render && last=$now
    done
) &

# Same as the image's /docker-entrypoint.sh standalone branch, minus its `sed -i` on
# config.yaml (mounted read-only here, sed would abort the container).
/usr/bin/apisix init
# a hard stop (Docker/WSL killed) leaves nginx's unix sockets behind and the restart fails to bind them
rm -f /usr/local/apisix/logs/*.sock
exec /usr/local/openresty/bin/openresty -p /usr/local/apisix -g 'daemon off;'
