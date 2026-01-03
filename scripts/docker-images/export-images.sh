#!/bin/bash
#
# Export all Docker images used in the ELK Stack + APISIX setup
#
# This script saves all Docker images to tar files for offline distribution.
# The exported images can be loaded on another machine using import-images.sh
#
# Usage:
#   ./export-images.sh [output-directory]
#
# Default output directory: ./docker-images-export
#

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default output directory
OUTPUT_DIR="${1:-./docker-images-export}"

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Docker Images Export Tool${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Output directory: $OUTPUT_DIR"
echo ""

# Define all images used in docker-compose.yml
declare -a IMAGES=(
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

# Function to sanitize image name for filename
sanitize_name() {
    echo "$1" | sed 's/[\/:]/_/g' | sed 's/__/_/g'
}

# Count for progress
TOTAL=${#IMAGES[@]}
CURRENT=0
EXPORTED=0
SKIPPED=0
FAILED=0

echo "Found $TOTAL images to export"
echo ""

# Export each image
for IMAGE in "${IMAGES[@]}"; do
    CURRENT=$((CURRENT + 1))
    FILENAME="$(sanitize_name "$IMAGE").tar"
    FILEPATH="$OUTPUT_DIR/$FILENAME"

    echo -e "${YELLOW}[$CURRENT/$TOTAL]${NC} Processing: $IMAGE"

    # Check if image exists locally
    if ! docker image inspect "$IMAGE" &> /dev/null; then
        echo -e "${YELLOW}  Image not found locally. Pulling...${NC}"
        if docker pull "$IMAGE"; then
            echo -e "${GREEN}  ✓ Pulled successfully${NC}"
        else
            echo -e "${RED}  ✗ Failed to pull image${NC}"
            FAILED=$((FAILED + 1))
            continue
        fi
    fi

    # Check if tar file already exists
    if [ -f "$FILEPATH" ]; then
        echo -e "${YELLOW}  File already exists. Skipping.${NC}"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Export image
    echo -e "  Exporting to: $FILENAME"
    if docker save -o "$FILEPATH" "$IMAGE"; then
        SIZE=$(du -h "$FILEPATH" | cut -f1)
        echo -e "${GREEN}  ✓ Exported successfully ($SIZE)${NC}"
        EXPORTED=$((EXPORTED + 1))
    else
        echo -e "${RED}  ✗ Failed to export${NC}"
        FAILED=$((FAILED + 1))
        rm -f "$FILEPATH"
    fi

    echo ""
done

# Generate manifest file
MANIFEST_FILE="$OUTPUT_DIR/MANIFEST.txt"
echo "Generating manifest file: $MANIFEST_FILE"
{
    echo "Docker Images Export Manifest"
    echo "============================="
    echo ""
    echo "Export Date: $(date)"
    echo "Total Images: $TOTAL"
    echo "Exported: $EXPORTED"
    echo "Skipped: $SKIPPED"
    echo "Failed: $FAILED"
    echo ""
    echo "Images:"
    echo "-------"
    for IMAGE in "${IMAGES[@]}"; do
        echo "  - $IMAGE"
    done
    echo ""
    echo "Files:"
    echo "------"
    find "$OUTPUT_DIR" -name "*.tar" -type f -exec basename {} \; | sort
    echo ""
    echo "Total Size:"
    du -sh "$OUTPUT_DIR" | cut -f1
} > "$MANIFEST_FILE"

# Generate import script
IMPORT_SCRIPT="$OUTPUT_DIR/import-images.sh"
echo "Generating import script: $IMPORT_SCRIPT"
cat > "$IMPORT_SCRIPT" << 'EOF'
#!/bin/bash
#
# Import all Docker images from exported tar files
#
# This script loads all Docker images that were exported using export-images.sh
#
# Usage:
#   ./import-images.sh
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Docker Images Import Tool${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# Find all tar files
TAR_FILES=($(find . -maxdepth 1 -name "*.tar" -type f | sort))
TOTAL=${#TAR_FILES[@]}

if [ $TOTAL -eq 0 ]; then
    echo -e "${RED}No tar files found in current directory${NC}"
    exit 1
fi

echo "Found $TOTAL image files to import"
echo ""

CURRENT=0
IMPORTED=0
FAILED=0

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
    fi

    echo ""
done

echo -e "${GREEN}================================${NC}"
echo "Import Summary:"
echo "  Total: $TOTAL"
echo "  Imported: $IMPORTED"
echo "  Failed: $FAILED"
echo -e "${GREEN}================================${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All images imported successfully!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Copy the entire project directory to your target location"
    echo "  2. Ensure networks are created:"
    echo "     docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet"
    echo "     docker network create ce-base-network"
    echo "  3. Configure environment: cp .env.example .env"
    echo "  4. Generate secrets: ./config/scripts/setup/generate-secrets.sh"
    echo "  5. Start services: docker-compose up -d"
else
    echo -e "${RED}Some images failed to import. Check the errors above.${NC}"
    exit 1
fi
EOF

chmod +x "$IMPORT_SCRIPT"

# Generate README
README_FILE="$OUTPUT_DIR/README.md"
echo "Generating README: $README_FILE"
cat > "$README_FILE" << 'EOF'
# Docker Images Export Package

This package contains all Docker images required for the ELK Stack + APISIX Gateway platform.

## Contents

- **Docker Images**: All images exported as `.tar` files
- **MANIFEST.txt**: List of all images and export details
- **import-images.sh**: Automated import script

## Total Package Size

See `MANIFEST.txt` for total size and file listing.

## Import Instructions

### Option 1: Automated Import (Recommended)

```bash
# Make import script executable
chmod +x import-images.sh

# Run import script
./import-images.sh
```

### Option 2: Manual Import

```bash
# Import all images
for tarfile in *.tar; do
    docker load -i "$tarfile"
done

# Verify images are loaded
docker images
```

## Complete Setup Guide

After importing the images, follow these steps to deploy the platform:

### 1. Transfer Complete Project

Copy the entire project directory (not just the images) to your target location:
```bash
# On source machine
cd "C:\work\Aqua\Docker ElasticSearch"
tar -czf elk-stack-complete.tar.gz --exclude=docker-images-export .

# Transfer elk-stack-complete.tar.gz to target machine

# On target machine
tar -xzf elk-stack-complete.tar.gz
cd "Docker ElasticSearch"
```

### 2. Create Docker Networks

```bash
# Create internal network with static IP range
docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet

# Create external network
docker network create ce-base-network
```

### 3. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Generate secure credentials
./config/scripts/setup/generate-secrets.sh

# Optional: Edit .env to customize settings
nano .env
```

### 4. Start Services

```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

### 5. Verify Deployment

Wait for all services to become healthy (1-2 minutes), then access:

- **Kibana**: http://localhost:9080/kibana
- **APISIX Dashboard**: http://localhost:9000 (admin/admin)
- **Grafana**: http://localhost:9080/grafana
- **Prometheus**: http://localhost:9080/prometheus

Login credentials for Kibana:
- Username: `elastic`
- Password: Check `.env` file for `ELASTIC_PASSWORD`

### 6. Optional: SSL/TLS Setup

For production deployments with HTTPS:

```bash
# Generate self-signed certificates (development)
./config/scripts/setup/generate-certs.sh

# OR setup Let's Encrypt (production)
./config/scripts/setup/setup-letsencrypt.sh --domain yourdomain.com --email admin@yourdomain.com

# Enable SSL in .env
# Set: SSL_ENABLED=true

# Restart with SSL
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d
```

## Images Included

See `MANIFEST.txt` for the complete list of images.

Core components:
- ElasticSearch 8.11.3
- Kibana 8.11.3
- Logstash 8.11.3
- APM Server 8.10.4
- Apache APISIX 3.7.0
- Prometheus 2.48.0
- Grafana 10.2.2
- And more...

## Troubleshooting

### Images not importing
```bash
# Check Docker is running
docker ps

# Check tar file integrity
tar -tzf docker.elastic.co_elasticsearch_elasticsearch_8.11.3.tar >/dev/null

# Import specific image manually
docker load -i docker.elastic.co_elasticsearch_elasticsearch_8.11.3.tar
```

### Services not starting
```bash
# Check networks exist
docker network ls | grep ce-base

# Check logs for specific service
docker-compose logs elasticsearch

# Restart specific service
docker-compose restart elasticsearch
```

### Permission errors
```bash
# Ensure scripts are executable
chmod +x config/scripts/setup/*.sh
chmod +x config/scripts/backup/*.sh

# Check volume permissions
docker-compose down -v
docker-compose up -d
```

## Support

For detailed documentation, see:
- `SETUP.md`: Main setup guide
- `CLAUDE.md`: Technical documentation
- `docs/`: Detailed guides for each component

For issues and support:
- GitHub: https://github.com/anthropics/claude-code/issues
EOF

# Generate compression script
COMPRESS_SCRIPT="$OUTPUT_DIR/create-distribution-package.sh"
echo "Generating compression script: $COMPRESS_SCRIPT"
cat > "$COMPRESS_SCRIPT" << 'EOF'
#!/bin/bash
#
# Create a compressed distribution package
#
# This script creates a single compressed archive of all Docker images
# for easy transfer and distribution.
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PACKAGE_NAME="elk-stack-docker-images-$(date +%Y%m%d).tar.gz"

echo -e "${GREEN}Creating distribution package...${NC}"
echo ""
echo "Package name: $PACKAGE_NAME"
echo ""

# Create tar.gz archive
tar -czf "../$PACKAGE_NAME" *.tar *.txt *.md *.sh

# Calculate size
SIZE=$(du -h "../$PACKAGE_NAME" | cut -f1)

echo -e "${GREEN}Package created successfully!${NC}"
echo ""
echo "File: $PACKAGE_NAME"
echo "Size: $SIZE"
echo "Location: $(cd ..; pwd)/$PACKAGE_NAME"
echo ""
echo "To distribute:"
echo "  1. Copy $PACKAGE_NAME to target machine"
echo "  2. Extract: tar -xzf $PACKAGE_NAME"
echo "  3. Run: ./import-images.sh"
EOF

chmod +x "$COMPRESS_SCRIPT"

# Summary
echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Export Summary${NC}"
echo -e "${GREEN}================================${NC}"
echo "Total Images: $TOTAL"
echo "Exported: $EXPORTED"
echo "Skipped: $SKIPPED"
echo "Failed: $FAILED"
echo ""
echo "Output directory: $OUTPUT_DIR"
echo "Total size: $(du -sh "$OUTPUT_DIR" | cut -f1)"
echo ""
echo "Generated files:"
echo "  - MANIFEST.txt (image list and details)"
echo "  - README.md (setup instructions)"
echo "  - import-images.sh (automated import script)"
echo "  - create-distribution-package.sh (create compressed archive)"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All images exported successfully!${NC}"
    echo ""
    echo "Next steps:"
    echo ""
    echo "Option 1: Transfer individual tar files"
    echo "  1. Copy the entire $OUTPUT_DIR directory to target machine"
    echo "  2. Run: cd $OUTPUT_DIR && ./import-images.sh"
    echo ""
    echo "Option 2: Create compressed package (recommended for network transfer)"
    echo "  1. Run: cd $OUTPUT_DIR && ./create-distribution-package.sh"
    echo "  2. Transfer the generated .tar.gz file"
    echo "  3. On target machine: tar -xzf elk-stack-docker-images-*.tar.gz"
    echo "  4. Run: ./import-images.sh"
else
    echo -e "${RED}✗ Some images failed to export. Check the errors above.${NC}"
    exit 1
fi
