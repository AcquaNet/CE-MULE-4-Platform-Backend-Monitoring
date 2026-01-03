# Docker Images Export/Import Scripts

Scripts for exporting and importing all Docker images used in the ELK Stack + APISIX Gateway platform.

## Overview

These scripts allow you to:
- Export all Docker images to tar files for offline distribution
- Import the images on another machine without internet access
- Create compressed distribution packages for easy transfer

This is particularly useful for:
- Air-gapped environments
- Restricted network environments
- Offline installations
- Backup and disaster recovery
- Consistent deployments across multiple environments

## Scripts

### `export-images.sh`

Exports all Docker images used in the platform to tar files.

**Usage:**
```bash
./export-images.sh [output-directory]
```

**Features:**
- Automatically pulls missing images
- Skips already exported images
- Generates manifest file with export details
- Creates automated import script
- Generates README with setup instructions
- Creates compression script for distribution

**Example:**
```bash
# Export to default directory (./docker-images-export)
./export-images.sh

# Export to custom directory
./export-images.sh /mnt/usb/elk-images

# Export to SOTA directory for inclusion in offline package
./export-images.sh ../../CE-Platform/_sota/docker-images
```

### `import-images.sh`

Imports all Docker images from tar files.

**Usage:**
```bash
./import-images.sh [directory]
```

**Features:**
- Automatically finds all .tar files
- Confirms before importing
- Shows progress for each image
- Verifies imported images
- Provides next steps after import

**Example:**
```bash
# Import from current directory
./import-images.sh

# Import from specific directory
./import-images.sh ./docker-images-export
```

## Complete Workflow

### 1. Export Images (Source Machine)

```bash
# Navigate to scripts directory
cd "C:\work\Aqua\Docker ElasticSearch\scripts\docker-images"

# Export all images
./export-images.sh

# Create compressed package for transfer
cd docker-images-export
./create-distribution-package.sh
```

This creates `elk-stack-docker-images-YYYYMMDD.tar.gz` in the parent directory.

### 2. Transfer Package

Transfer the `.tar.gz` file to your target machine using:
- USB drive
- Secure file transfer (SCP, SFTP)
- Network share
- Physical media

### 3. Import Images (Target Machine)

```bash
# Extract package
tar -xzf elk-stack-docker-images-20260102.tar.gz
cd docker-images-export

# Import all images
./import-images.sh

# Verify images
docker images | grep -E "(elasticsearch|kibana|logstash|apisix|prometheus|grafana)"
```

### 4. Deploy Platform

After importing images, follow the setup guide:

```bash
# Navigate to project root
cd "C:\work\Aqua\Docker ElasticSearch"

# Create networks
docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet
docker network create ce-base-network

# Configure environment
cp .env.example .env
./config/scripts/setup/generate-secrets.sh

# Start services
docker-compose up -d

# Verify deployment
docker-compose ps
```

## Images Included

The export includes all images from `docker-compose.yml` and `docker-compose.ssl.yml`:

### ELK Stack Core (8.11.3)
- `docker.elastic.co/elasticsearch/elasticsearch:8.11.3`
- `docker.elastic.co/kibana/kibana:8.11.3`
- `docker.elastic.co/logstash/logstash:8.11.3`
- `docker.elastic.co/apm/apm-server:8.10.4`

### APISIX Gateway
- `apache/apisix:3.7.0-debian`
- `apache/apisix-dashboard:3.0.1-alpine`
- `quay.io/coreos/etcd:v3.5.9`

### Monitoring Stack
- `prom/prometheus:v2.48.0`
- `grafana/grafana:10.2.2`
- `prom/alertmanager:v0.26.0`
- `quay.io/prometheuscommunity/elasticsearch-exporter:v1.6.0`

### Utility Images
- `curlimages/curl:latest`

## Disk Space Requirements

Approximate sizes:
- ElasticSearch: ~800 MB
- Kibana: ~700 MB
- Logstash: ~700 MB
- APISIX: ~300 MB
- Prometheus: ~200 MB
- Grafana: ~300 MB
- Others: ~500 MB

**Total**: ~3-4 GB uncompressed, ~2-3 GB compressed

Ensure you have sufficient disk space on both source and target machines.

## Advanced Usage

### Export Specific Images

To export only specific images, edit the `IMAGES` array in `export-images.sh`:

```bash
declare -a IMAGES=(
    "docker.elastic.co/elasticsearch/elasticsearch:8.11.3"
    "docker.elastic.co/kibana/kibana:8.11.3"
    # Add or remove images as needed
)
```

### Update to Newer Versions

To export newer versions:

1. Update image versions in `docker-compose.yml`
2. Pull new images: `docker-compose pull`
3. Run export script: `./export-images.sh`

### Verify Image Integrity

After export, verify tar files:

```bash
cd docker-images-export

# Check tar file integrity
for tarfile in *.tar; do
    echo "Checking $tarfile..."
    tar -tzf "$tarfile" >/dev/null && echo "OK" || echo "CORRUPT"
done
```

### Manual Import (Alternative)

If the import script fails, import manually:

```bash
# Import all images
for tarfile in *.tar; do
    echo "Loading $tarfile..."
    docker load -i "$tarfile"
done

# Verify
docker images
```

## Troubleshooting

### Export Issues

**Problem**: "Image not found" error during export
```bash
# Pull the image manually
docker pull docker.elastic.co/elasticsearch/elasticsearch:8.11.3

# Re-run export
./export-images.sh
```

**Problem**: "No space left on device"
```bash
# Check available disk space
df -h

# Export to a different location with more space
./export-images.sh /path/to/larger/disk
```

### Import Issues

**Problem**: "Cannot connect to Docker daemon"
```bash
# Start Docker service
sudo systemctl start docker  # Linux
# or start Docker Desktop     # Windows/Mac

# Verify Docker is running
docker ps
```

**Problem**: Import fails with "permission denied"
```bash
# Run with sudo (Linux)
sudo ./import-images.sh

# Or fix permissions
sudo chmod +x import-images.sh
```

**Problem**: Tar file corruption
```bash
# Verify file integrity
tar -tzf problematic-file.tar

# If corrupt, re-export on source machine
# and transfer again
```

## Integration with SOTA Components

The exported images can be included in the SOTA (`CE-Platform/_sota`) directory for a complete offline installation package:

```bash
# Export to SOTA directory
./export-images.sh ../../CE-Platform/_sota/docker-images

# The SOTA directory now contains:
# - Mule Runtime
# - Maven
# - JDK
# - ActiveMQ
# - Docker images (new)
```

This creates a fully self-contained offline installation package.

## Automation

### Automated Export (Cron Job)

Create a weekly export for backup:

```bash
# Add to crontab (Linux)
0 2 * * 0 /path/to/export-images.sh /backup/docker-images-$(date +\%Y\%m\%d)

# This exports images every Sunday at 2 AM
```

### CI/CD Integration

Include in your deployment pipeline:

```yaml
# Example GitLab CI
export-images:
  stage: prepare
  script:
    - ./scripts/docker-images/export-images.sh ./artifacts
    - cd artifacts && ./create-distribution-package.sh
  artifacts:
    paths:
      - elk-stack-docker-images-*.tar.gz
    expire_in: 30 days
```

## See Also

- `../../SETUP.md` - Main setup guide
- `../../CLAUDE.md` - Technical documentation
- `../../docs/BACKUP_SETUP.md` - Backup and restore guide
- `../../CE-Platform/_sota/` - SOTA offline components

## Support

For issues or questions:
- Check `../../docs/setup/07-troubleshooting.md`
- Review Docker logs: `docker-compose logs`
- GitHub Issues: https://github.com/anthropics/claude-code/issues
