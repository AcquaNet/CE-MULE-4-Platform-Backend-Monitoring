#!/bin/bash
#
# Create .env from .env.example with every CHANGE_ME_PLEASE replaced by its own random secret
# (32 characters, letters and digits). ./install.sh runs this when there is no .env.
#
# Careful with --force on an installed platform: several secrets only apply when their data volume is first
# created (OpenSearch admin, Keycloak admin/realm users/DB, MySQL, Grafana), and a new RM_SECRETS_KEY makes the
# Runtime Manager's stored secure properties and node tokens unreadable. See docs/SECURITY_SETUP.md.
#
# Usage: ./config/scripts/setup/generate-secrets.sh [--force] [--dry-run]
set -euo pipefail
cd "$(dirname "$0")/../../.."

force=0 dry=0
for a in "$@"; do
    case "$a" in
        --force) force=1 ;;
        --dry-run) dry=1 ;;
        *) echo "Usage: $0 [--force] [--dry-run]" >&2; exit 1 ;;
    esac
done
[ -f .env.example ] || { echo "ERROR: .env.example not found" >&2; exit 1; }
if [ -f .env ] && [ "$force" = 0 ] && [ "$dry" = 0 ]; then
    echo ".env already exists: --force replaces it with new secrets (read the warning in this script first)" >&2
    exit 1
fi

secret() { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 32; }
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
