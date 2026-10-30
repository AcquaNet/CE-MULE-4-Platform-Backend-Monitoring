#!/bin/bash
# Self-check of generate-secrets.sh --add-missing (no stack needed): bash config/scripts/setup/test_generate_secrets.sh
# On an existing .env it adds only the generated secrets that are missing, keeps every existing value, and a second run
# changes nothing.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
t=$(mktemp -d)
trap 'rm -rf "$t"' EXIT
mkdir -p "$t/config/scripts/setup"
cp "$here/generate-secrets.sh" "$t/config/scripts/setup/"
cp "$here/../../../.env.example" "$t/"
printf 'RM_PASSWORD=keep-me\nCOMPOSE_PROFILES=logging' > "$t/.env"   # no final newline on purpose
cd "$t"
bash config/scripts/setup/generate-secrets.sh --add-missing > out.txt
grep -qx 'RM_PASSWORD=keep-me' .env || { echo "FAIL: existing value changed"; exit 1; }
grep -qx 'COMPOSE_PROFILES=logging' .env || { echo "FAIL: last line without newline got merged"; exit 1; }
for k in $(grep '=CHANGE_ME_PLEASE$' .env.example | cut -d= -f1); do
    [ "$k" = RM_PASSWORD ] && continue
    grep -Eq "^$k=[A-Za-z0-9]{32}$" .env || { echo "FAIL: $k not added as a 32-char secret"; exit 1; }
done
grep -q 'added LOG_ARCHIVER_TOKEN' out.txt || { echo "FAIL: no report of LOG_ARCHIVER_TOKEN"; exit 1; }
before=$(md5sum .env)
bash config/scripts/setup/generate-secrets.sh --add-missing > out2.txt
[ "$before" = "$(md5sum .env)" ] && [ ! -s out2.txt ] || { echo "FAIL: second run changed .env"; exit 1; }
echo "test_generate_secrets: ok"
