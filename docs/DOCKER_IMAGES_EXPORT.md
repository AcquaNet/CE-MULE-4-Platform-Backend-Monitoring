# Docker Images Export and Import Guide

Complete guide for exporting and importing Docker images for offline deployment of the ELK Stack + APISIX Gateway platform.

## Overview

This guide shows you how to export all Docker images required by the platform, making it easy to deploy in:
- **Air-gapped environments** (no internet access)
- **Restricted networks** (limited outbound connectivity)
- **Offline installations** (standalone deployments)
- **Backup scenarios** (disaster recovery)
- **Consistent deployments** (version control)

## Quick Start

### Export Images (Source Machine with Internet)

**Windows:**
```cmd
cd C:\work\Aqua\Docker ElasticSearch\scripts\docker-images
export-images.bat
```

**Linux/Mac:**
```bash
cd scripts/docker-images
chmod +x export-images.sh
./export-images.sh
```

### Import Images (Target Machine without Internet)

**Windows:**
```cmd
cd docker-images-export
import-images.bat
```

**Linux/Mac:**
```bash
cd docker-images-export
chmod +x import-images.sh
./import-images.sh
```

## Detailed Instructions

### Step 1: Export Docker Images

On a machine with internet access and Docker installed:

#### Windows

```cmd
REM Navigate to scripts directory
cd C:\work\Aqua\Docker ElasticSearch\scripts\docker-images

REM Run export script
export-images.bat

REM Optional: Export to custom location
export-images.bat E:\backup\docker-images

REM Optional: Export to SOTA directory
export-images.bat ..\..\CE-Platform\_sota\docker-images
```

#### Linux/Mac

```bash
# Navigate to scripts directory
cd scripts/docker-images

# Make script executable
chmod +x export-images.sh

# Run export script
./export-images.sh

# Optional: Export to custom location
./export-images.sh /mnt/backup/docker-images

# Optional: Export to SOTA directory
./export-images.sh ../../CE-Platform/_sota/docker-images
```

#### What Happens During Export

1. **Image Check**: Script checks if each image exists locally
2. **Pull Missing**: Downloads any missing images from Docker Hub
3. **Export to TAR**: Saves each image as a `.tar` file
4. **Generate Manifest**: Creates `MANIFEST.txt` with export details
5. **Create Import Script**: Generates automated import script
6. **Generate README**: Creates setup instructions

**Output Directory Structure:**
```
docker-images-export/
├── docker.elastic.co_elasticsearch_elasticsearch_8.11.3.tar
├── docker.elastic.co_kibana_kibana_8.11.3.tar
├── docker.elastic.co_logstash_logstash_8.11.3.tar
├── docker.elastic.co_apm_apm-server_8.10.4.tar
├── apache_apisix_3.7.0-debian.tar
├── apache_apisix-dashboard_3.0.1-alpine.tar
├── quay.io_coreos_etcd_v3.5.9.tar
├── prom_prometheus_v2.48.0.tar
├── grafana_grafana_10.2.2.tar
├── prom_alertmanager_v0.26.0.tar
├── quay.io_prometheuscommunity_elasticsearch-exporter_v1.6.0.tar
├── curlimages_curl_latest.tar
├── MANIFEST.txt
├── README.md (Linux/Mac)
├── README.txt (Windows)
├── import-images.sh (Linux/Mac)
└── import-images.bat (Windows)
```

### Step 2: Transfer Images

Transfer the `docker-images-export` directory to your target machine.

#### Option 1: USB Drive

**Windows:**
```cmd
REM Copy to USB drive
xcopy docker-images-export E:\docker-images-export\ /E /I /H

REM On target machine, copy from USB
xcopy E:\docker-images-export C:\docker-images-export\ /E /I /H
```

**Linux/Mac:**
```bash
# Copy to USB drive
cp -r docker-images-export /media/usb/

# On target machine, copy from USB
cp -r /media/usb/docker-images-export ~/
```

#### Option 2: Compressed Archive

**Windows (ZIP):**
```cmd
REM Right-click docker-images-export folder
REM Select "Send to" > "Compressed (zipped) folder"
REM Transfer elk-stack-images.zip to target machine
REM Extract on target machine
```

**Linux/Mac (tar.gz):**
```bash
# Create compressed archive
cd docker-images-export
tar -czf ../elk-stack-images.tar.gz .

# Transfer to target machine via SCP
scp elk-stack-images.tar.gz user@target-machine:/path/

# On target machine, extract
mkdir docker-images-export
cd docker-images-export
tar -xzf ../elk-stack-images.tar.gz
```

#### Option 3: Network Transfer

**Windows (Network Share):**
```cmd
REM Copy to network share
xcopy docker-images-export \\server\share\docker-images\ /E /I /H
```

**Linux/Mac (SCP):**
```bash
# Transfer directory via SCP
scp -r docker-images-export user@target-machine:/path/

# Or use rsync
rsync -avz docker-images-export/ user@target-machine:/path/docker-images-export/
```

### Step 3: Import Docker Images

On the target machine (offline/air-gapped):

#### Windows

```cmd
REM Navigate to exported images directory
cd C:\docker-images-export

REM Run import script
import-images.bat

REM Verify import
docker images
```

#### Linux/Mac

```bash
# Navigate to exported images directory
cd docker-images-export

# Make script executable
chmod +x import-images.sh

# Run import script
./import-images.sh

# Verify import
docker images
```

#### Manual Import (If Scripts Fail)

**Windows:**
```cmd
cd docker-images-export
for %f in (*.tar) do docker load -i "%f"
```

**Linux/Mac:**
```bash
cd docker-images-export
for tarfile in *.tar; do
    docker load -i "$tarfile"
done
```

### Step 4: Deploy Platform

After importing images, deploy the platform:

#### 1. Create Docker Networks

```bash
# Create internal network with static IPs
docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet

# Create external network
docker network create ce-base-network
```

#### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Generate secure credentials
# Windows:
config\scripts\setup\generate-secrets.bat

# Linux/Mac:
./config/scripts/setup/generate-secrets.sh
```

#### 3. Start Services

```bash
# Start all services
docker-compose up -d

# Check status (wait for all services to be healthy)
docker-compose ps

# View logs
docker-compose logs -f
```

#### 4. Verify Deployment

Access the following URLs (after all services are healthy):

- **Kibana**: http://localhost:9080/kibana
  - Username: `elastic`
  - Password: Check `.env` file for `ELASTIC_PASSWORD`

- **APISIX Dashboard**: http://localhost:9000
  - Username: `admin`
  - Password: `admin` (change in production!)

- **Grafana**: http://localhost:9080/grafana
  - Username: `admin`
  - Password: Check `.env` file for `GRAFANA_ADMIN_PASSWORD`

- **Prometheus**: http://localhost:9080/prometheus

- **ElasticSearch Health**:
  ```bash
  curl http://localhost:9080/elasticsearch/_cluster/health?pretty
  ```

## Image Details

### Images Included

| Image | Version | Size (approx) | Purpose |
|-------|---------|---------------|---------|
| elasticsearch | 8.11.3 | ~800 MB | Search and analytics engine |
| kibana | 8.11.3 | ~700 MB | ElasticSearch web interface |
| logstash | 8.11.3 | ~700 MB | Data processing pipeline |
| apm-server | 8.10.4 | ~100 MB | Application performance monitoring |
| apisix | 3.7.0-debian | ~300 MB | API gateway and load balancer |
| apisix-dashboard | 3.0.1-alpine | ~50 MB | APISIX web interface |
| etcd | v3.5.9 | ~50 MB | APISIX configuration storage |
| prometheus | v2.48.0 | ~200 MB | Metrics collection |
| grafana | 10.2.2 | ~300 MB | Metrics visualization |
| alertmanager | v0.26.0 | ~50 MB | Alert notifications |
| elasticsearch-exporter | v1.6.0 | ~20 MB | ElasticSearch metrics for Prometheus |
| curl | latest | ~10 MB | Utility for setup scripts |

**Total Size**: ~3-4 GB uncompressed, ~2-3 GB compressed

### Disk Space Requirements

**Source Machine (Export):**
- Docker images: ~3-4 GB
- Exported tar files: ~3-4 GB
- **Total**: ~7-8 GB

**Target Machine (Import):**
- Imported tar files: ~3-4 GB (can be deleted after import)
- Docker images: ~3-4 GB
- Runtime data: ~1-2 GB (logs, indices, etc.)
- **Total**: ~7-10 GB

**Recommended**: 20+ GB free disk space on both machines

## Advanced Usage

### Selective Image Export

To export only specific images, edit the `IMAGES` array in the export script:

**export-images.sh (Linux/Mac):**
```bash
declare -a IMAGES=(
    "docker.elastic.co/elasticsearch/elasticsearch:8.11.3"
    "docker.elastic.co/kibana/kibana:8.11.3"
    # Add only the images you need
)
```

**export-images.bat (Windows):**
```cmd
set "IMAGES[0]=docker.elastic.co/elasticsearch/elasticsearch:8.11.3"
set "IMAGES[1]=docker.elastic.co/kibana/kibana:8.11.3"
REM Add only the images you need
REM Update TOTAL variable accordingly
```

### Version Upgrade

To export newer versions:

1. Update versions in `docker-compose.yml`:
   ```yaml
   services:
     elasticsearch:
       image: docker.elastic.co/elasticsearch/elasticsearch:8.12.0
   ```

2. Update image versions in export script

3. Pull new images:
   ```bash
   docker-compose pull
   ```

4. Run export:
   ```bash
   ./export-images.sh
   ```

### Automation

#### Scheduled Export (Backup)

**Windows (Task Scheduler):**
```cmd
REM Create scheduled task for weekly export
schtasks /create /tn "Docker Images Backup" /tr "C:\work\Aqua\Docker ElasticSearch\scripts\docker-images\export-images.bat E:\backup\docker-images-%date:~-4,4%%date:~-7,2%%date:~-10,2%" /sc weekly /d SUN /st 02:00
```

**Linux (Cron):**
```bash
# Add to crontab
crontab -e

# Add this line (runs every Sunday at 2 AM)
0 2 * * 0 /path/to/scripts/docker-images/export-images.sh /backup/docker-images-$(date +\%Y\%m\%d)
```

### Integration with SOTA

Include exported images in the SOTA offline package:

```bash
# Export to SOTA directory
./export-images.sh ../../CE-Platform/_sota/docker-images

# The SOTA directory now contains:
# - Mule Runtime (mule-standalone-4.4.0.tar.gz)
# - Maven (apache-maven-3.6.3-bin.tar.gz)
# - JDK (OpenJDK8U-jdk_x64_linux_hotspot_8u362b09.tar.gz)
# - ActiveMQ (apache-activemq-5.15.3-bin.tar.gz)
# - Docker Images (docker-images/)
#
# This creates a complete offline installation package
```

## Troubleshooting

### Export Issues

#### Problem: "Cannot connect to Docker daemon"

**Solution:**
```bash
# Windows: Start Docker Desktop
# Linux: Start Docker service
sudo systemctl start docker

# Verify Docker is running
docker ps
```

#### Problem: "No space left on device"

**Solution:**
```bash
# Check disk space
df -h  # Linux/Mac
dir    # Windows

# Free up space
docker system prune -a

# Export to different location with more space
./export-images.sh /path/to/larger/disk
```

#### Problem: "Failed to pull image"

**Solution:**
```bash
# Check internet connection
ping docker.io

# Check Docker Hub status
curl https://status.docker.com/

# Pull image manually
docker pull docker.elastic.co/elasticsearch/elasticsearch:8.11.3

# Re-run export
./export-images.sh
```

### Import Issues

#### Problem: "No tar files found"

**Solution:**
```bash
# Verify you're in correct directory
ls *.tar  # Linux/Mac
dir *.tar # Windows

# If files are missing, re-transfer from source machine
```

#### Problem: "Failed to import" or corruption errors

**Solution:**
```bash
# Verify tar file integrity
tar -tzf problematic-file.tar  # Linux/Mac

# If corrupt, re-export on source machine
# Delete corrupt file
rm problematic-file.tar

# Re-export specific image on source machine
docker save -o new-file.tar image:tag

# Transfer to target machine and import
docker load -i new-file.tar
```

#### Problem: "Permission denied"

**Solution:**
```bash
# Linux: Run with sudo
sudo ./import-images.sh

# Or fix script permissions
chmod +x import-images.sh

# Windows: Run as Administrator
# Right-click Command Prompt > Run as Administrator
```

### Deployment Issues

#### Problem: Networks not found

**Solution:**
```bash
# Create networks manually
docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet
docker network create ce-base-network

# Verify networks exist
docker network ls
```

#### Problem: Services failing to start

**Solution:**
```bash
# Check service logs
docker-compose logs [service-name]

# Common fixes:
# 1. Ensure networks exist
# 2. Verify .env file is configured
# 3. Check port conflicts
# 4. Verify images are loaded: docker images

# Restart services
docker-compose restart

# Or full restart
docker-compose down
docker-compose up -d
```

#### Problem: Health checks failing

**Solution:**
```bash
# Wait longer (some services take 2-3 minutes)
watch docker-compose ps

# Check specific service health
docker inspect --format='{{.State.Health.Status}}' elasticsearch

# View health check logs
docker inspect --format='{{json .State.Health}}' elasticsearch | jq

# If stuck, restart service
docker-compose restart [service-name]
```

## Best Practices

### 1. Version Control

- Keep exported images versioned by date
- Store in version-controlled location
- Document which application versions correspond to each image export

### 2. Validation

Always validate exports:
```bash
# After export, verify file sizes
du -sh docker-images-export/*.tar

# Test import on a test machine before production
```

### 3. Documentation

Include with your export package:
- Export date and source
- Image versions
- Any custom configurations
- Known issues or workarounds

### 4. Storage

- Store exports on reliable media (not cloud storage for air-gapped)
- Keep multiple copies
- Use compression for transfer, uncompressed for storage
- Test recovery periodically

### 5. Security

- Scan images for vulnerabilities before export
- Keep exports in secure locations
- Document any security patches needed
- Update regularly

## Alternative Methods

### Docker Save/Load All Images

Export all images in one file:
```bash
# Export all images to single tar
docker save -o all-images.tar $(docker images -q)

# Import on target machine
docker load -i all-images.tar
```

**Pros**: Single file, simple
**Cons**: Very large file, all-or-nothing import

### Docker Registry (Private)

For controlled environments with limited internet:

1. Set up private Docker registry
2. Push images to registry
3. Pull from registry on target machines

See: https://docs.docker.com/registry/deploying/

### Image Scanning Before Export

Scan for vulnerabilities:
```bash
# Using Docker Scout
docker scout cves docker.elastic.co/elasticsearch/elasticsearch:8.11.3

# Using Trivy
trivy image docker.elastic.co/elasticsearch/elasticsearch:8.11.3
```

## See Also

- **Main Setup Guide**: `../SETUP.md`
- **Technical Documentation**: `../CLAUDE.md`
- **SOTA Components**: `../CE-Platform/_sota/`
- **Backup Guide**: `BACKUP_SETUP.md`
- **SSL/TLS Setup**: `SSL_TLS_SETUP.md`
- **Troubleshooting**: `setup/07-troubleshooting.md`

## Support

For issues or questions:
- Review troubleshooting section above
- Check Docker logs: `docker-compose logs`
- Verify images: `docker images`
- GitHub Issues: https://github.com/anthropics/claude-code/issues
