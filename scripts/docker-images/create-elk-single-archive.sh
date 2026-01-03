#!/bin/bash
#
# Create a single tar archive containing all ELK Stack Docker images
#
# This script combines all ELK stack images into a single tar file,
# making it easier to transfer and import on target machines.
#
# Usage:
#   ./create-elk-single-archive.sh [output-file]
#
# Default output: elk-stack-all-images.tar
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

OUTPUT_FILE="${1:-elk-stack-all-images.tar}"

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}ELK Stack Single Archive Creator${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Output file: $OUTPUT_FILE"
echo ""

# Define ELK stack images (excluding Mule-related images)
declare -a ELK_IMAGES=(
    # ELK Stack Core
    "docker.elastic.co/elasticsearch/elasticsearch:8.11.3"
    "docker.elastic.co/kibana/kibana:8.11.3"
    "docker.elastic.co/logstash/logstash:8.11.3"
    "docker.elastic.co/apm/apm-server:8.10.4"

    # APISIX Gateway
    "apache/apisix:3.7.0-debian"
    "apache/apisix-dashboard:3.0.1-alpine"
    "quay.io/coreos/etcd:v3.5.9"

    # Monitoring Stack
    "prom/prometheus:v2.48.0"
    "grafana/grafana:10.2.2"
    "prom/alertmanager:v0.26.0"
    "quay.io/prometheuscommunity/elasticsearch-exporter:v1.6.0"

    # Utility Images
    "curlimages/curl:latest"
)

TOTAL=${#ELK_IMAGES[@]}
echo "Images to include: $TOTAL"
echo ""

# Check if all images exist locally
echo -e "${YELLOW}Checking for missing images...${NC}"
MISSING=0
MISSING_IMAGES=()

for IMAGE in "${ELK_IMAGES[@]}"; do
    if ! docker image inspect "$IMAGE" &> /dev/null; then
        echo "  Missing: $IMAGE"
        MISSING=$((MISSING + 1))
        MISSING_IMAGES+=("$IMAGE")
    fi
done

# Pull missing images if needed
if [ $MISSING -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}Found $MISSING missing images. Pulling...${NC}"
    echo ""

    for IMAGE in "${MISSING_IMAGES[@]}"; do
        echo "Pulling: $IMAGE"
        if ! docker pull "$IMAGE"; then
            echo -e "${RED}Failed to pull $IMAGE${NC}"
            exit 1
        fi
    done
    echo ""
fi

echo -e "${GREEN}All images are available locally${NC}"
echo ""

# Create single tar file with all images
echo -e "${YELLOW}Creating single archive with all images...${NC}"
echo "This may take several minutes..."
echo ""

# Use docker save with all images at once
if docker save -o "$OUTPUT_FILE" "${ELK_IMAGES[@]}"; then
    SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
    echo ""
    echo -e "${GREEN}✓ Archive created successfully!${NC}"
    echo ""
    echo "File: $OUTPUT_FILE"
    echo "Size: $SIZE"
    echo ""

    # Create companion import script
    IMPORT_SCRIPT="${OUTPUT_FILE%.tar}-import.sh"
    cat > "$IMPORT_SCRIPT" << 'EOF'
#!/bin/bash
#
# Import ELK Stack images from single archive
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ARCHIVE_FILE="$(dirname "$0")/elk-stack-all-images.tar"

if [ ! -f "$ARCHIVE_FILE" ]; then
    echo "Error: Archive file not found: $ARCHIVE_FILE"
    exit 1
fi

echo -e "${GREEN}Importing ELK Stack images...${NC}"
echo ""
echo "Archive: $ARCHIVE_FILE"
echo "Size: $(du -h "$ARCHIVE_FILE" | cut -f1)"
echo ""

if docker load -i "$ARCHIVE_FILE"; then
    echo ""
    echo -e "${GREEN}✓ All images imported successfully!${NC}"
    echo ""
    echo "Imported images:"
    docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | \
        grep -E "(elasticsearch|kibana|logstash|apm-server|apisix|etcd|prometheus|grafana|alertmanager|curl)" || true
    echo ""
    echo "Next steps:"
    echo "  1. Create networks:"
    echo "     docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet"
    echo "     docker network create ce-base-network"
    echo ""
    echo "  2. Configure environment:"
    echo "     cp .env.example .env"
    echo "     ./config/scripts/setup/generate-secrets.sh"
    echo ""
    echo "  3. Start services:"
    echo "     docker-compose up -d"
else
    echo -e "${RED}✗ Import failed${NC}"
    exit 1
fi
EOF

    chmod +x "$IMPORT_SCRIPT"

    echo "Created import script: $IMPORT_SCRIPT"
    echo ""

    # Create manifest
    MANIFEST_FILE="${OUTPUT_FILE%.tar}-manifest.txt"
    {
        echo "ELK Stack Single Archive Manifest"
        echo "=================================="
        echo ""
        echo "Created: $(date)"
        echo "Archive: $OUTPUT_FILE"
        echo "Size: $SIZE"
        echo "Total Images: $TOTAL"
        echo ""
        echo "Images Included:"
        echo "----------------"
        for IMAGE in "${ELK_IMAGES[@]}"; do
            echo "  - $IMAGE"
        done
        echo ""
        echo "Import Instructions:"
        echo "-------------------"
        echo "1. Transfer this archive to target machine"
        echo "2. Run: docker load -i $OUTPUT_FILE"
        echo "3. Or use: ./$IMPORT_SCRIPT"
        echo ""
        echo "Components Included:"
        echo "-------------------"
        echo "- ElasticSearch 8.11.3"
        echo "- Kibana 8.11.3"
        echo "- Logstash 8.11.3"
        echo "- APM Server 8.10.4"
        echo "- Apache APISIX 3.7.0"
        echo "- APISIX Dashboard 3.0.1"
        echo "- etcd v3.5.9"
        echo "- Prometheus v2.48.0"
        echo "- Grafana 10.2.2"
        echo "- Alertmanager v0.26.0"
        echo "- ElasticSearch Exporter v1.6.0"
        echo "- curl (latest)"
    } > "$MANIFEST_FILE"

    echo "Created manifest: $MANIFEST_FILE"
    echo ""

    # Optional: Create compressed version
    read -p "Create compressed archive? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo -e "${YELLOW}Compressing archive...${NC}"
        gzip -k "$OUTPUT_FILE"
        COMPRESSED_SIZE=$(du -h "${OUTPUT_FILE}.gz" | cut -f1)
        echo -e "${GREEN}✓ Compressed archive created${NC}"
        echo "File: ${OUTPUT_FILE}.gz"
        echo "Size: $COMPRESSED_SIZE"
        echo ""
    fi

    echo "Summary:"
    echo "--------"
    echo "Archive file: $OUTPUT_FILE ($SIZE)"
    echo "Import script: $IMPORT_SCRIPT"
    echo "Manifest: $MANIFEST_FILE"
    echo ""
    echo "To transfer and import:"
    echo "  1. Copy files to target machine:"
    echo "     - $OUTPUT_FILE"
    echo "     - $IMPORT_SCRIPT"
    echo "     - $MANIFEST_FILE"
    echo ""
    echo "  2. On target machine, run:"
    echo "     chmod +x $IMPORT_SCRIPT"
    echo "     ./$IMPORT_SCRIPT"

else
    echo -e "${RED}✗ Failed to create archive${NC}"
    exit 1
fi
