#!/bin/bash
#
# Import all Docker images from exported tar files
#
# This script loads all Docker images that were exported using export-images.sh
#
# Usage:
#   ./import-images.sh [directory]
#
# Default directory: current directory
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

IMPORT_DIR="${1:-.}"

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Docker Images Import Tool${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Import directory: $IMPORT_DIR"
echo ""

# Change to import directory
cd "$IMPORT_DIR"

# Find all tar files
TAR_FILES=($(find . -maxdepth 1 -name "*.tar" -type f | sort))
TOTAL=${#TAR_FILES[@]}

if [ $TOTAL -eq 0 ]; then
    echo -e "${RED}No tar files found in $IMPORT_DIR${NC}"
    echo ""
    echo "Expected file pattern: *.tar"
    echo ""
    echo "Make sure you have exported images using export-images.sh first"
    exit 1
fi

echo "Found $TOTAL image files to import"
echo ""

# Ask for confirmation
read -p "Import all $TOTAL images? This may take several minutes. (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Import cancelled"
    exit 0
fi
echo ""

CURRENT=0
IMPORTED=0
FAILED=0
declare -a FAILED_FILES

# Import each tar file
for TAR_FILE in "${TAR_FILES[@]}"; do
    CURRENT=$((CURRENT + 1))
    FILENAME=$(basename "$TAR_FILE")

    echo -e "${YELLOW}[$CURRENT/$TOTAL]${NC} Importing: $FILENAME"

    if docker load -i "$TAR_FILE"; then
        echo -e "${GREEN}  ✓ Imported successfully${NC}"
        IMPORTED=$((IMPORTED + 1))
    else
        echo -e "${RED}  ✗ Failed to import${NC}"
        FAILED=$((FAILED + 1))
        FAILED_FILES+=("$FILENAME")
    fi

    echo ""
done

# Summary
echo -e "${GREEN}================================${NC}"
echo "Import Summary:"
echo "  Total: $TOTAL"
echo "  Imported: $IMPORTED"
echo "  Failed: $FAILED"
echo -e "${GREEN}================================${NC}"
echo ""

if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed files:${NC}"
    for FILE in "${FAILED_FILES[@]}"; do
        echo "  - $FILE"
    done
    echo ""
fi

# Verify imported images
echo "Verifying imported images..."
echo ""
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | grep -E "(elasticsearch|kibana|logstash|apm-server|apisix|etcd|prometheus|grafana|alertmanager|curl)" || true
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All images imported successfully!${NC}"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Ensure Docker networks are created:"
    echo "   ${YELLOW}docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet${NC}"
    echo "   ${YELLOW}docker network create ce-base-network${NC}"
    echo ""
    echo "2. Navigate to project root directory (if not already there)"
    echo ""
    echo "3. Configure environment:"
    echo "   ${YELLOW}cp .env.example .env${NC}"
    echo "   ${YELLOW}./config/scripts/setup/generate-secrets.sh${NC}"
    echo ""
    echo "4. Start services:"
    echo "   ${YELLOW}docker-compose up -d${NC}"
    echo ""
    echo "5. Check status:"
    echo "   ${YELLOW}docker-compose ps${NC}"
    echo ""
    echo "6. Access services:"
    echo "   - Kibana: http://localhost:9080/kibana"
    echo "   - APISIX Dashboard: http://localhost:9000"
    echo "   - Grafana: http://localhost:9080/grafana"
    echo "   - Prometheus: http://localhost:9080/prometheus"
else
    echo -e "${RED}✗ Some images failed to import.${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check Docker is running: docker ps"
    echo "  2. Check tar file integrity: tar -tzf [filename].tar"
    echo "  3. Try importing failed files manually: docker load -i [filename].tar"
    echo "  4. Check disk space: df -h"
    exit 1
fi
