#!/bin/bash
#
# Load the images exported by export-images.sh on a server without internet, then install without rebuilding.
#
# Usage: scripts/docker-images/import-images.sh [platform-images.tar]
set -euo pipefail
tar=${1:-platform-images.tar}
[ -f "$tar" ] || { echo "ERROR: $tar not found" >&2; exit 1; }
docker load -i "$tar"
echo
echo "Images loaded. Install with the loaded images (no rebuild, no downloads):"
echo "  NO_BUILD=1 ./install.sh"
