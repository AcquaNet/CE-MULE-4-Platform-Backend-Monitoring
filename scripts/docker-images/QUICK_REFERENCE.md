# Docker Images Export/Import - Quick Reference Card

Quick reference for exporting and importing Docker images for offline ELK Stack + APISIX deployment.

---

## 📦 Export Images (Machine with Internet)

### Windows
```cmd
cd C:\work\Aqua\Docker ElasticSearch\scripts\docker-images
export-images.bat
```

### Linux/Mac
```bash
cd scripts/docker-images
chmod +x export-images.sh
./export-images.sh
```

**Output:** `docker-images-export/` directory with 12 `.tar` files (~3-4 GB)

---

## 💾 Transfer to Target Machine

### Option 1: USB Drive
```bash
# Copy entire docker-images-export/ folder to USB
# Transfer USB to target machine
```

### Option 2: Compressed Archive
```bash
# Linux/Mac
tar -czf elk-images.tar.gz docker-images-export/

# Windows - use 7-Zip or built-in ZIP
# Right-click folder > Send to > Compressed folder
```

### Option 3: Network Transfer
```bash
# SCP
scp -r docker-images-export/ user@target:/path/

# Or use network share/FTP/etc.
```

---

## 📥 Import Images (Target Machine without Internet)

### Windows
```cmd
cd docker-images-export
import-images.bat
```

### Linux/Mac
```bash
cd docker-images-export
chmod +x import-images.sh
./import-images.sh
```

**Result:** All 12 images loaded into Docker

---

## 🚀 Deploy Platform (After Import)

### 1. Create Networks
```bash
docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet
docker network create ce-base-network
```

### 2. Configure Environment
```bash
# Copy template
cp .env.example .env

# Generate secrets (Windows)
config\scripts\setup\generate-secrets.bat

# Generate secrets (Linux/Mac)
./config/scripts/setup/generate-secrets.sh
```

### 3. Start Services
```bash
docker-compose up -d
```

### 4. Verify
```bash
# Check status
docker-compose ps

# Wait for all services to be "healthy"
# Can take 1-2 minutes
```

---

## 🌐 Access Services

Once all services are healthy:

| Service | URL | Credentials |
|---------|-----|-------------|
| **Kibana** | http://localhost:9080/kibana | elastic / (see .env) |
| **APISIX Dashboard** | http://localhost:9000 | admin / admin |
| **Grafana** | http://localhost:9080/grafana | admin / (see .env) |
| **Prometheus** | http://localhost:9080/prometheus | - |
| **ElasticSearch API** | http://localhost:9080/elasticsearch | elastic / (see .env) |

---

## 📊 Images Included

| Component | Version | Size |
|-----------|---------|------|
| ElasticSearch | 8.11.3 | ~800 MB |
| Kibana | 8.11.3 | ~700 MB |
| Logstash | 8.11.3 | ~700 MB |
| APM Server | 8.10.4 | ~100 MB |
| APISIX | 3.7.0 | ~300 MB |
| APISIX Dashboard | 3.0.1 | ~50 MB |
| etcd | v3.5.9 | ~50 MB |
| Prometheus | v2.48.0 | ~200 MB |
| Grafana | 10.2.2 | ~300 MB |
| Alertmanager | v0.26.0 | ~50 MB |
| ES Exporter | v1.6.0 | ~20 MB |
| curl | latest | ~10 MB |

**Total: ~3-4 GB**

---

## ⚠️ Troubleshooting

### Export Issues

**"Cannot connect to Docker daemon"**
```bash
# Start Docker
# Windows: Start Docker Desktop
# Linux: sudo systemctl start docker
```

**"No space left on device"**
```bash
# Free up space
docker system prune -a

# Or export to different location
./export-images.sh /path/with/space
```

### Import Issues

**"No tar files found"**
```bash
# Verify you're in correct directory
ls *.tar  # Should show 12 files

# If missing, re-transfer from source
```

**"Failed to import"**
```bash
# Try manual import
docker load -i filename.tar

# Check Docker is running
docker ps
```

### Deployment Issues

**Services not starting**
```bash
# Check logs
docker-compose logs [service-name]

# Ensure networks exist
docker network ls | grep ce-base

# Restart services
docker-compose restart
```

**Health checks failing**
```bash
# Wait longer (2-3 minutes for all services)
watch docker-compose ps

# Check specific service
docker-compose logs elasticsearch
```

---

## 📚 Full Documentation

- **Complete Guide:** `docs/DOCKER_IMAGES_EXPORT.md`
- **Setup Guide:** `SETUP.md`
- **Technical Docs:** `CLAUDE.md`
- **Scripts README:** `scripts/docker-images/README.md`

---

## 💡 Tips

1. **Always verify imports:** Run `docker images` after import to confirm
2. **Save export manifests:** Keep `MANIFEST.txt` for version tracking
3. **Test before production:** Import and test on staging environment first
4. **Compress for transfer:** Use tar.gz or zip to reduce transfer size by ~30%
5. **Document versions:** Note which application versions match which image export

---

## 🔄 Common Workflows

### Complete Offline Package
```bash
# Export Docker images to SOTA directory
./export-images.sh ../../CE-Platform/_sota/docker-images

# Now SOTA directory contains:
# - Mule Runtime, Maven, JDK, ActiveMQ
# - Docker images
# = Complete offline installation package
```

### Weekly Backup
```bash
# Schedule weekly export for backup
# Linux cron:
0 2 * * 0 /path/to/export-images.sh /backup/images-$(date +\%Y\%m\%d)

# Windows Task Scheduler: Run export-images.bat weekly
```

### Version Upgrade
```bash
# 1. Update docker-compose.yml with new versions
# 2. Pull new images: docker-compose pull
# 3. Export: ./export-images.sh
# 4. Transfer and import on target machines
```

---

**Last Updated:** 2026-01-02
**Compatible with:** ELK Stack 8.11.3, APISIX 3.7.0
