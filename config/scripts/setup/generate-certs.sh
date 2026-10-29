#!/bin/bash
#
# Gateway (APISIX) HTTPS certificate from the platform's local CA.
# config/apisix/start.sh does the work: on start it creates certs/ca (local CA) and certs/apisix (gateway cert for
# localhost, apisix, 127.0.0.1 + every name/IP in GATEWAY_HOSTNAMES), and re-issues the gateway cert when a name
# in GATEWAY_HOSTNAMES is missing from it. This script only edits .env / certs and restarts APISIX.
# For a public certificate use config/scripts/setup/setup-letsencrypt.sh instead.
#
# Usage: ./config/scripts/setup/generate-certs.sh --domain example.com[,10.0.0.5]   add names, re-issue the cert
#        ./config/scripts/setup/generate-certs.sh --force                          new gateway cert (same CA)
#        ./config/scripts/setup/generate-certs.sh --force --new-ca                 new CA + cert (re-trust ca.crt)
set -euo pipefail
cd "$(dirname "$0")/../../.."

domain="" force=0 newca=0
while [ $# -gt 0 ]; do
    case "$1" in
        --domain) domain=$2; shift 2 ;;
        --force) force=1; shift ;;
        --new-ca) newca=1; shift ;;
        *) echo "Usage: $0 [--domain name[,name...]] [--force [--new-ca]]" >&2; exit 1 ;;
    esac
done
[ -n "$domain" ] || [ "$force" = 1 ] || { echo "Usage: $0 [--domain name[,name...]] [--force [--new-ca]]" >&2; exit 1; }
[ -f .env ] || { echo "ERROR: no .env (run ./install.sh)" >&2; exit 1; }

if [ -n "$domain" ]; then
    cur=$(sed -n 's/^GATEWAY_HOSTNAMES=//p' .env | tail -n 1 | tr -d '\r"')
    new=$(printf '%s\n' "$cur" "$domain" | tr ',' '\n' | sed '/^$/d' | awk '!seen[$0]++' | paste -sd, -)
    if grep -q '^GATEWAY_HOSTNAMES=' .env; then sed -i "s|^GATEWAY_HOSTNAMES=.*|GATEWAY_HOSTNAMES=$new|" .env
    else echo "GATEWAY_HOSTNAMES=$new" >> .env; fi
    echo "GATEWAY_HOSTNAMES=$new"
fi
if [ "$force" = 1 ]; then
    rm -f certs/apisix/apisix.crt certs/apisix/apisix.key
    [ "$newca" = 1 ] && rm -f certs/ca/ca.crt certs/ca/ca.key && echo "removed the local CA: trust the new certs/ca/ca.crt afterwards"
fi

# recreate (not restart): GATEWAY_HOSTNAMES is container env, read at creation
docker compose up -d --force-recreate --no-deps --wait apisix >/dev/null
openssl x509 -in certs/apisix/apisix.crt -noout -subject -ext subjectAltName 2>/dev/null \
    || docker compose exec -T apisix openssl x509 -in /certs/apisix/apisix.crt -noout -subject -ext subjectAltName
