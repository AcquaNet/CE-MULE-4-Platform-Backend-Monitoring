# ELK Stack Single Archive - Quick Guide

## Overview

This approach creates **ONE single tar file** containing all ELK Stack images for easy offline deployment. The images are still separate inside, maintaining proper architecture.

**File:** `elk-stack-all-images.tar` (~3-4 GB)

**Contains:**
- ElasticSearch, Kibana, Logstash, APM Server
- Apache APISIX + Dashboard
- Prometheus, Grafana, Alertmanager
- Supporting services (etcd, exporters, utilities)

---

## Why This Approach?

### ✅ Benefits

1. **Single File Transfer**
   - Only 1 file to copy instead of 12
   - Easier to manage and track
   - Simpler for offline deployment

2. **Maintains Proper Architecture**
   - Services still run in separate containers
   - Full isolation and independence
   - Can scale/restart services individually

3. **Production Ready**
   - Same architecture as multi-file approach
   - No compromises in functionality
   - Fully supported by Docker

4. **Simpler Workflow**
   - Export: 1 command
   - Transfer: 1 file
   - Import: 1 command

### ❌ Alternative Avoided: True All-in-One Container

We did NOT create a single container running all services because:
- One crash kills everything
- Can't scale individual services
- Hard to debug and maintain
- Not recommended by Docker best practices

---

## Quick Start

### Windows

#### 1. Create Archive (Machine with Internet)
```cmd
cd C:\work\Aqua\Docker ElasticSearch\scripts\docker-images
create-elk-single-archive.bat
```

**Output:**
- `elk-stack-all-images.tar` (~3-4 GB)
- `elk-stack-all-images-import.bat` (auto-import script)
- `elk-stack-all-images-manifest.txt` (image list)

#### 2. Transfer to Target Machine
Copy all 3 files to target machine via USB/network

#### 3. Import on Target Machine
```cmd
elk-stack-all-images-import.bat
```

**Or manually:**
```cmd
docker load -i elk-stack-all-images.tar
```

### Linux/Mac

#### 1. Create Archive
```bash
cd scripts/docker-images
chmod +x create-elk-single-archive.sh
./create-elk-single-archive.sh
```

#### 2. Transfer
```bash
# Option 1: Compress for faster transfer
gzip elk-stack-all-images.tar

# Option 2: Transfer directly
scp elk-stack-all-images.tar user@target:/path/
```

#### 3. Import
```bash
chmod +x elk-stack-all-images-import.sh
./elk-stack-all-images-import.sh
```

---

## Complete Deployment Workflow

### Step 1: Create Archive (Source Machine)

**Windows:**
```cmd
cd C:\work\Aqua\Docker ElasticSearch\scripts\docker-images
create-elk-single-archive.bat
```

**Linux/Mac:**
```bash
cd scripts/docker-images
./create-elk-single-archive.sh
```

**What happens:**
1. Checks if all 12 images exist locally
2. Pulls any missing images from Docker Hub
3. Combines all images into single tar file
4. Creates import script and manifest

**Time:** 5-10 minutes (depending on missing images)

### Step 2: Transfer Archive

**Size:** ~3-4 GB uncompressed, ~2-3 GB compressed

**Methods:**

**USB Drive:**
```cmd
REM Copy to USB
copy elk-stack-all-images.tar E:\
copy elk-stack-all-images-import.bat E:\
copy elk-stack-all-images-manifest.txt E:\
```

**Network (Linux/Mac):**
```bash
# SCP
scp elk-stack-all-images* user@target:/home/user/

# Rsync
rsync -avz elk-stack-all-images* user@target:/home/user/
```

**Compressed Transfer:**
```bash
# Linux/Mac
gzip elk-stack-all-images.tar
# Transfer the .tar.gz file (30% smaller)
# On target: gunzip elk-stack-all-images.tar.gz
```

### Step 3: Import Images (Target Machine)

**Windows:**
```cmd
REM Navigate to where you copied files
cd E:\

REM Run import script
elk-stack-all-images-import.bat

REM Or manually
docker load -i elk-stack-all-images.tar
```

**Linux/Mac:**
```bash
# Using import script
chmod +x elk-stack-all-images-import.sh
./elk-stack-all-images-import.sh

# Or manually
docker load -i elk-stack-all-images.tar
```

**Verify import:**
```bash
docker images | grep -E "elasticsearch|kibana|logstash|apisix"
```

**Time:** 5-10 minutes

### Step 4: Deploy Platform

#### Create Networks
```bash
docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet
docker network create ce-base-network
```

#### Configure Environment
```bash
# Copy template
cp .env.example .env

# Generate secrets
# Windows:
config\scripts\setup\generate-secrets.bat

# Linux/Mac:
./config/scripts/setup/generate-secrets.sh
```

#### Start Services
```bash
docker-compose up -d
```

#### Verify Deployment
```bash
# Check status (wait for all "healthy")
docker-compose ps

# Check logs
docker-compose logs -f
```

**Time:** 2-3 minutes to start, 1-2 minutes to become healthy

---

## What Gets Included

### ELK Stack Core (4 images)
| Image | Size | Purpose |
|-------|------|---------|
| elasticsearch:8.11.3 | ~800 MB | Search and analytics |
| kibana:8.11.3 | ~700 MB | Web UI and visualization |
| logstash:8.11.3 | ~700 MB | Data processing pipeline |
| apm-server:8.10.4 | ~100 MB | Application monitoring |

### API Gateway (3 images)
| Image | Size | Purpose |
|-------|------|---------|
| apisix:3.7.0 | ~300 MB | API gateway |
| apisix-dashboard:3.0.1 | ~50 MB | APISIX web UI |
| etcd:v3.5.9 | ~50 MB | Configuration storage |

### Monitoring (4 images)
| Image | Size | Purpose |
|-------|------|---------|
| prometheus:v2.48.0 | ~200 MB | Metrics collection |
| grafana:10.2.2 | ~300 MB | Dashboards |
| alertmanager:v0.26.0 | ~50 MB | Alerting |
| elasticsearch-exporter:v1.6.0 | ~20 MB | ES metrics |

### Utilities (1 image)
| Image | Size | Purpose |
|-------|------|---------|
| curl:latest | ~10 MB | Setup scripts |

**Total:** 12 images, ~3-4 GB

### What's NOT Included (Separate)

- **Mule Runtime** - Application-specific, managed separately
- **ActiveMQ** - Message broker, separate deployment
- **MySQL** - Database, separate deployment

**Reason:** These are application-specific and may vary by deployment

---

## Comparison: Single Archive vs Individual Files

### Single Archive Approach (Recommended for You)

**Created file:** `elk-stack-all-images.tar`

✅ **Pros:**
- Single file to manage and transfer
- Faster to copy (no multi-file overhead)
- Atomic operation (all or nothing)
- Easier to version and track
- Simpler offline deployment

❌ **Cons:**
- Larger single file (need 3-4 GB contiguous space)
- Can't selectively import images
- Takes longer to create (~10 min vs ~5 min per image)

### Individual Files Approach

**Created files:** 12 separate tar files

✅ **Pros:**
- Can import selectively
- Smaller individual files
- Faster if only some images needed
- Can resume partial transfer

❌ **Cons:**
- 12 files to manage and transfer
- Higher chance of missing files
- More complex tracking

---

## Performance Comparison

| Operation | Single Archive | Individual Files |
|-----------|----------------|------------------|
| **Create** | 5-10 min | 5-10 min |
| **Transfer (USB)** | 3-5 min | 5-10 min |
| **Transfer (Network 100Mbps)** | 5-7 min | 7-12 min |
| **Import** | 5-10 min | 5-10 min |
| **Total Time** | **15-25 min** | **20-35 min** |

**Winner:** Single Archive (faster, simpler)

---

## Storage Requirements

### Source Machine (Creation)
- Docker images (cached): ~3-4 GB
- Archive file: ~3-4 GB
- **Total: 7-8 GB**

### Transfer Media
- Uncompressed: 3-4 GB
- Compressed (gzip): 2-3 GB
- **Recommended:** 8+ GB USB drive

### Target Machine (Import)
- Archive file: ~3-4 GB (can delete after import)
- Docker images: ~3-4 GB
- Runtime data: ~1-2 GB
- **Total: 8-10 GB**

**Recommended:** 20+ GB free space

---

## Advanced Usage

### Compress for Transfer

**Linux/Mac:**
```bash
# Create compressed archive
./create-elk-single-archive.sh
gzip elk-stack-all-images.tar

# Results in elk-stack-all-images.tar.gz (~2-3 GB, 30% smaller)

# On target machine:
gunzip elk-stack-all-images.tar.gz
docker load -i elk-stack-all-images.tar
```

**Windows:**
```cmd
REM Use 7-Zip or built-in compression
REM Right-click file > Send to > Compressed folder
```

### Custom Output Location

```bash
# Linux/Mac
./create-elk-single-archive.sh /mnt/usb/elk-stack.tar

# Windows
create-elk-single-archive.bat E:\backup\elk-stack.tar
```

### Integration with SOTA

```bash
# Create archive in SOTA directory
./create-elk-single-archive.sh ../../CE-Platform/_sota/elk-stack-all-images.tar

# SOTA directory now contains:
# - Mule Runtime
# - Maven, JDK, ActiveMQ
# - elk-stack-all-images.tar (ELK Stack)
# = Complete offline package
```

### Automated Backup

**Linux Cron:**
```bash
# Weekly backup every Sunday at 2 AM
0 2 * * 0 /path/to/create-elk-single-archive.sh /backup/elk-$(date +\%Y\%m\%d).tar
```

**Windows Task Scheduler:**
```cmd
schtasks /create /tn "ELK Backup" ^
  /tr "C:\path\to\create-elk-single-archive.bat E:\backup\elk-%date%.tar" ^
  /sc weekly /d SUN /st 02:00
```

---

## Troubleshooting

### Creation Issues

**Problem:** "Cannot connect to Docker daemon"
```bash
# Start Docker
# Windows: Start Docker Desktop
# Linux: sudo systemctl start docker
docker ps  # Verify
```

**Problem:** "No space left on device"
```bash
# Free up space
docker system prune -a

# Or create archive on different drive
./create-elk-single-archive.sh /mnt/external/elk-stack.tar
```

**Problem:** "Failed to pull image"
```bash
# Check internet
ping docker.io

# Pull manually
docker pull docker.elastic.co/elasticsearch/elasticsearch:8.11.3

# Retry
./create-elk-single-archive.sh
```

### Transfer Issues

**Problem:** File corrupted during transfer
```bash
# Check file integrity with checksums

# On source:
sha256sum elk-stack-all-images.tar > checksum.txt

# Transfer both files

# On target:
sha256sum -c checksum.txt
# Should show "OK"
```

**Problem:** Not enough space on USB
```bash
# Compress first
gzip elk-stack-all-images.tar  # Reduces to ~2-3 GB
```

### Import Issues

**Problem:** "Invalid tar header"
```bash
# File is corrupted, re-transfer
# Verify checksum before import
```

**Problem:** Import takes too long / hangs
```bash
# Check Docker disk space
docker system df

# Clean up if needed
docker system prune

# Try again
docker load -i elk-stack-all-images.tar
```

**Problem:** Some images not imported
```bash
# List what was imported
docker images

# Check which images should be there
cat elk-stack-all-images-manifest.txt

# If missing, check tar contents
tar -tzf elk-stack-all-images.tar | head
```

---

## Best Practices

### 1. Always Create Checksums
```bash
# After creation
sha256sum elk-stack-all-images.tar > elk-stack-all-images.sha256

# After transfer, verify
sha256sum -c elk-stack-all-images.sha256
```

### 2. Document Versions
Keep manifest file with archive - it contains:
- Creation date
- All image versions
- Import instructions

### 3. Test Before Production
```bash
# Always test import on staging first
docker load -i elk-stack-all-images.tar
docker-compose up -d
# Test all services
# Only then deploy to production
```

### 4. Keep Multiple Versions
```bash
# Archive with date
./create-elk-single-archive.sh elk-stack-2026-01-02.tar

# Keep last 3 versions for rollback
```

### 5. Compress for Long-term Storage
```bash
# Compress for archival
gzip elk-stack-all-images.tar

# Store compressed version
# Uncompress when needed
```

---

## FAQ

**Q: Is this production-ready?**
A: Yes! Services still run in separate containers with full isolation.

**Q: Can I scale services?**
A: Yes! Use `docker-compose up -d --scale service=N`

**Q: Can I update individual services?**
A: Yes! Replace individual images and restart: `docker-compose pull service && docker-compose restart service`

**Q: How is this different from individual tar files?**
A: Same images, just packaged as 1 file instead of 12. Same result after import.

**Q: Does this include Mule?**
A: No, Mule is separate. This is only the ELK stack infrastructure.

**Q: Can I add more images to the archive?**
A: Yes! Edit the `IMAGES` array in the script and add your image names.

**Q: What about security?**
A: Images are official from Docker Hub. Scan with `docker scout` or `trivy` before exporting.

**Q: Can I use this in CI/CD?**
A: Yes! Script can be automated in build pipelines.

---

## Support

- **Quick Reference:** `QUICK_REFERENCE.md`
- **Full Documentation:** `docs/DOCKER_IMAGES_EXPORT.md`
- **Setup Guide:** `SETUP.md`
- **Technical Docs:** `CLAUDE.md`

---

**Last Updated:** 2026-01-02
**Version:** 1.0
**Compatible with:** ELK Stack 8.11.3, APISIX 3.7.0
