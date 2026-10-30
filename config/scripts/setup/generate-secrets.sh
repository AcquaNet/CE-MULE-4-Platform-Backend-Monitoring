#!/bin/bash
#
# Create .env from .env.example with every CHANGE_ME_PLEASE replaced by its own random secret
# (32 characters, letters and digits). ./install.sh runs this when there is no .env.
#
# Careful with --force on an installed platform: several secrets only apply when their data volume is first
# created (OpenSearch admin, Keycloak admin/realm users/DB, MySQL, Grafana), and a new RM_SECRETS_KEY makes the
# Runtime Manager's stored secure properties and node tokens unreadable. See docs/SECURITY_SETUP.md.
#
# --add-missing: append the generated secrets .env.example has and .env lacks (new ones after an update); nothing else
# changes. ./install.sh runs it on every start.
#
# Usage: ./config/scripts/setup/generate-secrets.sh [--force] [--dry-run] [--add-missing]
set -euo pipefail
cd "$(dirname "$0")/../../.."

force=0 dry=0 add=0
for a in "$@"; do
    case "$a" in
        --force) force=1 ;;
        --dry-run) dry=1 ;;
        --add-missing) add=1 ;;
        *) echo "Usage: $0 [--force] [--dry-run] [--add-missing]" >&2; exit 1 ;;
    esac
done
[ -f .env.example ] || { echo "ERROR: .env.example not found" >&2; exit 1; }

secret() { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 32; }
if [ "$add" = 1 ]; then
    [ -f .env ] || { echo "ERROR: no .env (run without --add-missing to create it)" >&2; exit 1; }
    n=0
    for k in $(grep '=CHANGE_ME_PLEASE$' .env.example | cut -d= -f1); do
        if ! grep -q "^$k=" .env; then
            [ "$(tail -c 1 .env)" = "" ] || echo >> .env
            printf '%s=%s\n' "$k" "$(secret)" >> .env
            echo "added $k to .env"
            n=$((n + 1))
        fi
    done
    [ "$n" = 0 ] || chmod 600 .env
    exit 0
fi
if [ -f .env ] && [ "$force" = 0 ] && [ "$dry" = 0 ]; then
    echo ".env already exists: --force replaces it with new secrets (read the warning in this script first)" >&2
    exit 1
fi

out=$(while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
        *=CHANGE_ME_PLEASE) printf '%s=%s\n' "${line%%=*}" "$(secret)" ;;
        *) printf '%s\n' "$line" ;;
    esac
done < .env.example)

if [ "$dry" = 1 ]; then
    echo "$out" | grep -F "$(grep '=CHANGE_ME_PLEASE$' .env.example | cut -d= -f1 | sed 's/$/=/')"
    exit 0
fi
umask 077
printf '%s\n' "$out" > .env
chmod 600 .env
echo "Created .env with $(grep -c '=CHANGE_ME_PLEASE$' .env.example) generated secrets (chmod 600; never commit it)."
