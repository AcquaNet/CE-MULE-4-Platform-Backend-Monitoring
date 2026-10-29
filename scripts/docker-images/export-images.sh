#!/bin/bash
#
# Export every image the platform runs (all compose profiles) plus the Mule runtime images the Runtime Manager
# built (ce-mule-runtime:*), into one tar for a server without internet. Missing images are pulled or built first.
# On the offline server: scripts/docker-images/import-images.sh <tar>, then NO_BUILD=1 ./install.sh
#
# Usage: scripts/docker-images/export-images.sh [output.tar]   (default: platform-images.tar)
#        scripts/docker-images/export-images.sh --list         (only print the image list)
set -euo pipefail
cd "$(dirname "$0")/../.."

images() {
    { docker compose --profile "*" config --images
      docker images --format '{{.Repository}}:{{.Tag}}' ce-mule-runtime; } | sort -u
}

if [ "${1:-}" = "--list" ]; then images; exit 0; fi
out=${1:-platform-images.tar}

docker compose --profile "*" pull --ignore-buildable --quiet   # registry images not pulled yet
docker compose --profile "*" build --quiet                     # ce-fluent-bit, runtime manager, activemq
[ -n "$(docker images -q ce-mule-runtime)" ] \
    || echo "WARNING: no ce-mule-runtime image: start the platform once (the Runtime Manager builds it) and export again" >&2

list=$(images)
echo "Saving $(echo "$list" | wc -l) images to $out (a few GB, takes a while):"
echo "$list" | sed 's/^/  /'
# shellcheck disable=SC2086
docker save -o "$out" $list
echo "Done: $(du -h "$out" | cut -f1) $out"
