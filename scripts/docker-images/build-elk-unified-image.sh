#!/bin/bash
#
# Build a single unified Docker image containing all ELK Stack components
#
# This creates one large Docker image that includes all ELK stack services.
# The image uses supervisord to manage multiple processes.
#
# WARNING: This is NOT recommended for production use. Multi-container
# architecture with docker-compose is preferred. This is primarily for
# offline/air-gapped deployments where simplicity is prioritized.
#
# Usage:
#   ./build-elk-unified-image.sh [image-name] [tag]
#
# Defaults:
#   image-name: elk-stack-unified
#   tag: latest
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

IMAGE_NAME="${1:-elk-stack-unified}"
IMAGE_TAG="${2:-latest}"
FULL_IMAGE_NAME="$IMAGE_NAME:$IMAGE_TAG"

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}ELK Stack Unified Image Builder${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Image name: $FULL_IMAGE_NAME"
echo ""

# Check if Dockerfile exists
if [ ! -f "../../Dockerfile.elk-unified" ]; then
    echo -e "${RED}Error: Dockerfile.elk-unified not found${NC}"
    echo "Please ensure you're running this from scripts/docker-images/ directory"
    exit 1
fi

echo -e "${YELLOW}Building unified image...${NC}"
echo "This may take 10-20 minutes depending on your system."
echo ""

# Build the image
cd ../..
docker build -f Dockerfile.elk-unified -t "$FULL_IMAGE_NAME" .

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Image built successfully!${NC}"
    echo ""
    echo "Image details:"
    docker images "$IMAGE_NAME" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
    echo ""
    echo "To save the image:"
    echo "  docker save -o elk-stack-unified.tar $FULL_IMAGE_NAME"
    echo ""
    echo "To run the image:"
    echo "  docker run -d -p 9080:9080 -p 9443:9443 -p 5601:5601 -p 9200:9200 \\"
    echo "    --name elk-stack $FULL_IMAGE_NAME"
    echo ""
    echo "To export for offline deployment:"
    echo "  docker save -o elk-stack-unified.tar $FULL_IMAGE_NAME"
    echo "  gzip elk-stack-unified.tar"
else
    echo -e "${RED}✗ Build failed${NC}"
    exit 1
fi
