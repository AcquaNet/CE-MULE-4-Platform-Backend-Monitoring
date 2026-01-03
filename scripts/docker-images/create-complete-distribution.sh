#!/bin/bash
#
# Create Complete ELK Stack Distribution Package
#
# This creates a complete, portable package containing:
#   1. All Docker images (in single tar file)
#   2. All configuration files
#   3. Setup scripts
#   4. Documentation
#
# Clients can customize configurations without rebuilding images.
#
# Usage:
#   ./create-complete-distribution.sh [output-directory]
#
# Default output: elk-stack-distribution
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

OUTPUT_DIR="${1:-elk-stack-distribution}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
PACKAGE_NAME="elk-stack-complete-${TIMESTAMP}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Complete ELK Stack Distribution Creator${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Creating complete distribution package..."
echo "Output directory: $OUTPUT_DIR"
echo ""

# Create output directory structure
mkdir -p "$OUTPUT_DIR/$PACKAGE_NAME"
cd "$OUTPUT_DIR/$PACKAGE_NAME"

echo -e "${BLUE}Step 1: Exporting Docker images...${NC}"
echo "This may take 10-15 minutes..."
echo ""

# Use the single archive script
if [ ! -f "../../scripts/docker-images/create-elk-single-archive.sh" ]; then
    echo -e "${RED}Error: create-elk-single-archive.sh not found${NC}"
    exit 1
fi

# Create images directory
mkdir -p images
cd ../../

# Export images
bash scripts/docker-images/create-elk-single-archive.sh "$OUTPUT_DIR/$PACKAGE_NAME/images/elk-stack-all-images.tar"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Failed to export images${NC}"
    exit 1
fi

cd "$OUTPUT_DIR/$PACKAGE_NAME"

echo ""
echo -e "${GREEN}✓ Docker images exported${NC}"
echo ""

echo -e "${BLUE}Step 2: Copying configuration files...${NC}"

# Copy essential files
mkdir -p config scripts docs certs

# Copy docker-compose files
cp ../../docker-compose.yml .
cp ../../docker-compose.ssl.yml .

# Copy environment template
cp ../../.env.example .

# Copy entire config directory
cp -r ../../config/* config/

# Copy scripts directory
cp -r ../../scripts/* scripts/

# Copy documentation
cp ../../README.md .
cp ../../SETUP.md .
cp ../../CLAUDE.md .
cp -r ../../docs/* docs/

# Copy certificate structure (empty, will be generated)
mkdir -p certs/ca certs/apisix certs/apm-server certs/extra

# Create .gitkeep files in cert directories
touch certs/ca/.gitkeep
touch certs/apisix/.gitkeep
touch certs/apm-server/.gitkeep

echo -e "${GREEN}✓ Configuration files copied${NC}"
echo ""

echo -e "${BLUE}Step 3: Creating deployment scripts...${NC}"

# Create Windows deployment script
cat > deploy.bat << 'EOFWIN'
@echo off
REM ========================================
REM ELK Stack - Complete Deployment Script
REM ========================================
REM
REM This script deploys the complete ELK Stack on Windows.
REM

setlocal

echo ========================================
echo ELK Stack Deployment
echo ========================================
echo.

REM Check if Docker is running
docker ps >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not running
    echo Please start Docker Desktop and try again
    exit /b 1
)

echo Step 1: Loading Docker images...
echo This may take 5-10 minutes...
echo.

if exist "images\elk-stack-all-images.tar" (
    docker load -i images\elk-stack-all-images.tar
    if errorlevel 1 (
        echo ERROR: Failed to load Docker images
        exit /b 1
    )
    echo Images loaded successfully!
) else (
    echo ERROR: Image file not found: images\elk-stack-all-images.tar
    exit /b 1
)
echo.

echo Step 2: Creating Docker networks...
docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet 2>nul
if errorlevel 1 (
    echo Network ce-base-micronet already exists
) else (
    echo Network ce-base-micronet created
)

docker network create ce-base-network 2>nul
if errorlevel 1 (
    echo Network ce-base-network already exists
) else (
    echo Network ce-base-network created
)
echo.

echo Step 3: Configuring environment...
if not exist ".env" (
    echo Copying environment template...
    copy .env.example .env
    echo.
    echo Generating secure passwords...
    if exist "config\scripts\setup\generate-secrets.bat" (
        call config\scripts\setup\generate-secrets.bat
    ) else (
        echo WARNING: generate-secrets.bat not found
        echo You will need to configure .env manually
    )
) else (
    echo .env file already exists, skipping...
)
echo.

echo Step 4: Starting services...
docker-compose up -d

if errorlevel 1 (
    echo ERROR: Failed to start services
    echo Check the logs with: docker-compose logs
    exit /b 1
)
echo.

echo ========================================
echo Deployment Complete!
echo ========================================
echo.
echo Services are starting up...
echo This may take 2-3 minutes for all services to become healthy.
echo.
echo Access your services at:
echo   - Kibana:           http://localhost:9080/kibana
echo   - APISIX Dashboard: http://localhost:9000
echo   - Grafana:          http://localhost:9080/grafana
echo   - Prometheus:       http://localhost:9080/prometheus
echo.
echo Login credentials (from .env file):
echo   - Kibana:     elastic / [check ELASTIC_PASSWORD in .env]
echo   - Grafana:    admin / [check GRAFANA_ADMIN_PASSWORD in .env]
echo   - APISIX:     admin / admin
echo.
echo To check status:    docker-compose ps
echo To view logs:       docker-compose logs -f
echo To stop services:   docker-compose down
echo.

endlocal
EOFWIN

# Create Linux/Mac deployment script
cat > deploy.sh << 'EOFSH'
#!/bin/bash
#
# ELK Stack - Complete Deployment Script
#
# This script deploys the complete ELK Stack on Linux/Mac.
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}ELK Stack Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if Docker is running
if ! docker ps >/dev/null 2>&1; then
    echo -e "${RED}ERROR: Docker is not running${NC}"
    echo "Please start Docker and try again"
    exit 1
fi

echo -e "${YELLOW}Step 1: Loading Docker images...${NC}"
echo "This may take 5-10 minutes..."
echo ""

if [ -f "images/elk-stack-all-images.tar" ]; then
    docker load -i images/elk-stack-all-images.tar
    echo -e "${GREEN}✓ Images loaded successfully!${NC}"
else
    echo -e "${RED}ERROR: Image file not found: images/elk-stack-all-images.tar${NC}"
    exit 1
fi
echo ""

echo -e "${YELLOW}Step 2: Creating Docker networks...${NC}"
docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet 2>/dev/null && \
    echo "✓ Network ce-base-micronet created" || \
    echo "  Network ce-base-micronet already exists"

docker network create ce-base-network 2>/dev/null && \
    echo "✓ Network ce-base-network created" || \
    echo "  Network ce-base-network already exists"
echo ""

echo -e "${YELLOW}Step 3: Configuring environment...${NC}"
if [ ! -f ".env" ]; then
    echo "Copying environment template..."
    cp .env.example .env
    echo ""
    echo "Generating secure passwords..."
    if [ -f "config/scripts/setup/generate-secrets.sh" ]; then
        chmod +x config/scripts/setup/generate-secrets.sh
        bash config/scripts/setup/generate-secrets.sh
    else
        echo -e "${YELLOW}WARNING: generate-secrets.sh not found${NC}"
        echo "You will need to configure .env manually"
    fi
else
    echo ".env file already exists, skipping..."
fi
echo ""

echo -e "${YELLOW}Step 4: Starting services...${NC}"
docker-compose up -d

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Services are starting up..."
echo "This may take 2-3 minutes for all services to become healthy."
echo ""
echo "Access your services at:"
echo "  - Kibana:           http://localhost:9080/kibana"
echo "  - APISIX Dashboard: http://localhost:9000"
echo "  - Grafana:          http://localhost:9080/grafana"
echo "  - Prometheus:       http://localhost:9080/prometheus"
echo ""
echo "Login credentials (from .env file):"
echo "  - Kibana:     elastic / [check ELASTIC_PASSWORD in .env]"
echo "  - Grafana:    admin / [check GRAFANA_ADMIN_PASSWORD in .env]"
echo "  - APISIX:     admin / admin"
echo ""
echo "To check status:    docker-compose ps"
echo "To view logs:       docker-compose logs -f"
echo "To stop services:   docker-compose down"
echo ""
EOFSH

chmod +x deploy.sh

echo -e "${GREEN}✓ Deployment scripts created${NC}"
echo ""

echo -e "${BLUE}Step 4: Creating README and documentation...${NC}"

# Create distribution README
cat > DISTRIBUTION-README.md << 'EOFREADME'
# ELK Stack - Complete Distribution Package

## Contents

This package contains everything needed to deploy the ELK Stack in offline/air-gapped environments:

### 1. Docker Images (`images/`)
- **elk-stack-all-images.tar** (~3-4 GB)
  - ElasticSearch 8.11.3
  - Kibana 8.11.3
  - Logstash 8.11.3
  - APM Server 8.10.4
  - Apache APISIX 3.7.0 + Dashboard
  - etcd, Prometheus, Grafana, Alertmanager
  - Supporting utilities

### 2. Configuration Files (`config/`)
- **apisix/** - API Gateway configuration
- **logstash/** - Log processing pipelines
- **prometheus/** - Metrics and alerting rules
- **grafana/** - Dashboard provisioning
- **scripts/** - Setup and maintenance scripts

**✅ Clients can modify these without rebuilding images!**

### 3. Deployment Files
- **docker-compose.yml** - Service orchestration
- **docker-compose.ssl.yml** - SSL/TLS configuration
- **.env.example** - Environment variable template

### 4. Scripts
- **deploy.sh** (Linux/Mac) - Automated deployment
- **deploy.bat** (Windows) - Automated deployment
- **config/scripts/** - Setup and maintenance scripts

### 5. Documentation
- **README.md** - Project overview
- **SETUP.md** - Setup guide
- **CLAUDE.md** - Technical documentation
- **docs/** - Detailed guides

---

## Quick Start

### Windows

1. **Run deployment script:**
   ```cmd
   deploy.bat
   ```

2. **Wait 2-3 minutes** for services to start

3. **Access services:**
   - Kibana: http://localhost:9080/kibana

### Linux/Mac

1. **Run deployment script:**
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```

2. **Wait 2-3 minutes** for services to start

3. **Access services:**
   - Kibana: http://localhost:9080/kibana

---

## Customization (NO Image Rebuild Required!)

### Change Logstash Pipeline

1. Edit: `config/logstash/pipeline/logstash.conf`
2. Restart: `docker-compose restart logstash`

✅ No rebuild needed - config is mounted as volume!

### Change APISIX Routes

1. Edit: `config/apisix/apisix.yaml`
2. Restart: `docker-compose restart apisix`

✅ No rebuild needed!

### Change Prometheus Scrape Targets

1. Edit: `config/prometheus/prometheus.yml`
2. Restart: `docker-compose restart prometheus`

✅ No rebuild needed!

### Change Grafana Dashboards

1. Add JSON to: `config/grafana/provisioning/dashboards/`
2. Restart: `docker-compose restart grafana`

✅ No rebuild needed!

### Change Environment Variables

1. Edit: `.env`
2. Restart: `docker-compose restart`

✅ No rebuild needed!

---

## What Requires Image Rebuild?

**Almost nothing!** The only things that require image rebuilds:

❌ Changing the ElasticSearch/Kibana/Logstash **versions**
❌ Installing additional ElasticSearch **plugins**
❌ Modifying the base **Dockerfile**

Everything else is configuration mounted as volumes!

---

## Configuration Files Reference

### Can Be Changed Without Rebuild:

| File | Purpose | Restart Required |
|------|---------|------------------|
| `.env` | Passwords, settings | Yes |
| `docker-compose.yml` | Service definitions | Yes |
| `config/apisix/apisix.yaml` | API routes | apisix only |
| `config/apisix/config/config.yaml` | APISIX settings | apisix only |
| `config/logstash/pipeline/logstash.conf` | Log pipeline | logstash only |
| `config/logstash/config/logstash.yml` | Logstash settings | logstash only |
| `config/prometheus/prometheus.yml` | Scrape config | prometheus only |
| `config/prometheus/rules/*.yml` | Alert rules | prometheus only |
| `config/grafana/provisioning/**` | Dashboards/datasources | grafana only |
| `certs/**` | SSL certificates | Related services |

### Cannot Be Changed (Part of Images):

| Component | What's Baked In |
|-----------|----------------|
| ElasticSearch | Version 8.11.3, base config |
| Kibana | Version 8.11.3, base config |
| Logstash | Version 8.11.3, plugins |
| APISIX | Version 3.7.0, nginx config |

---

## SSL/TLS Configuration

### Generate Certificates

**Self-signed (Development):**
```bash
./config/scripts/setup/generate-certs.sh
```

**Let's Encrypt (Production):**
```bash
./config/scripts/setup/setup-letsencrypt.sh --domain yourdomain.com --email admin@yourdomain.com
```

### Enable SSL

1. Edit `.env`:
   ```
   SSL_ENABLED=true
   ```

2. Restart with SSL:
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d
   ```

✅ No image rebuild needed!

---

## Advanced Configuration

### Add Custom Logstash Filter

**Edit:** `config/logstash/pipeline/logstash.conf`

```ruby
filter {
  # Add your custom filter here
  if [type] == "my-custom-type" {
    mutate {
      add_field => { "custom_field" => "custom_value" }
    }
  }
}
```

**Apply:**
```bash
docker-compose restart logstash
```

### Add Custom APISIX Route

**Edit:** `config/apisix/apisix.yaml`

```yaml
routes:
  - uri: /my-service/*
    upstream:
      nodes:
        "my-service:8080": 1
```

**Apply:**
```bash
docker-compose restart apisix
```

### Change Resource Limits

**Edit:** `docker-compose.yml`

```yaml
services:
  elasticsearch:
    environment:
      - ES_JAVA_OPTS=-Xms4g -Xmx4g  # Increase from 2g to 4g
```

**Apply:**
```bash
docker-compose up -d
```

---

## Troubleshooting

### Services Not Starting

```bash
# Check logs
docker-compose logs -f [service-name]

# Check network
docker network ls | grep ce-base

# Recreate networks
docker network rm ce-base-micronet ce-base-network
./deploy.sh
```

### Configuration Not Applied

```bash
# Verify file was changed
cat config/logstash/pipeline/logstash.conf

# Restart specific service
docker-compose restart logstash

# Or restart all
docker-compose restart
```

### Out of Memory Errors

Edit `.env` or `docker-compose.yml`:
```bash
# Reduce memory
ES_JAVA_OPTS=-Xms1g -Xmx1g
```

---

## Support

- **Setup Guide:** `SETUP.md`
- **Technical Docs:** `CLAUDE.md`
- **Detailed Guides:** `docs/`

---

## Package Information

- **Created:** [Auto-generated timestamp]
- **ELK Version:** 8.11.3
- **APISIX Version:** 3.7.0
- **Total Size:** ~4-5 GB (3-4 GB images + 1 GB configs/docs)
EOFREADME

echo -e "${GREEN}✓ Documentation created${NC}"
echo ""

echo -e "${BLUE}Step 5: Creating manifest...${NC}"

# Create manifest file
cat > MANIFEST.txt << EOFMANIFEST
ELK Stack Complete Distribution Package
========================================

Created: $(date)
Package: $PACKAGE_NAME

Contents:
---------

1. Docker Images (images/)
   - elk-stack-all-images.tar (~3-4 GB)
   - Contains 12 images (ElasticSearch, Kibana, Logstash, etc.)

2. Configuration Files (config/)
   - apisix/          - API Gateway configuration
   - logstash/        - Log processing pipelines
   - prometheus/      - Metrics and alerts
   - grafana/         - Dashboards
   - scripts/         - Setup scripts

3. Deployment Files
   - docker-compose.yml
   - docker-compose.ssl.yml
   - .env.example

4. Scripts
   - deploy.sh        - Linux/Mac deployment
   - deploy.bat       - Windows deployment

5. Documentation
   - DISTRIBUTION-README.md  - This package guide
   - README.md               - Project overview
   - SETUP.md                - Setup guide
   - CLAUDE.md               - Technical docs
   - docs/                   - Detailed guides

Total Size: $(du -sh . 2>/dev/null | cut -f1 || echo "calculating...")

Key Features:
-------------
✓ Complete offline deployment
✓ All configurations included
✓ Clients can customize without rebuilding images
✓ Automated deployment scripts
✓ Full documentation

Images Included:
----------------
- ElasticSearch 8.11.3
- Kibana 8.11.3
- Logstash 8.11.3
- APM Server 8.10.4
- Apache APISIX 3.7.0
- APISIX Dashboard 3.0.1
- etcd v3.5.9
- Prometheus v2.48.0
- Grafana 10.2.2
- Alertmanager v0.26.0
- ElasticSearch Exporter v1.6.0
- curl (latest)

Quick Start:
------------
Windows: deploy.bat
Linux:   ./deploy.sh

Customization:
--------------
All configuration files can be modified without rebuilding images.
See DISTRIBUTION-README.md for details.
EOFMANIFEST

echo -e "${GREEN}✓ Manifest created${NC}"
echo ""

cd ../..

echo -e "${BLUE}Step 6: Creating compressed archive (optional)...${NC}"
read -p "Create compressed archive? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Compressing package..."
    tar -czf "${PACKAGE_NAME}.tar.gz" -C "$OUTPUT_DIR" "$PACKAGE_NAME"

    SIZE=$(du -h "${PACKAGE_NAME}.tar.gz" | cut -f1)
    echo -e "${GREEN}✓ Compressed archive created: ${PACKAGE_NAME}.tar.gz ($SIZE)${NC}"
    echo ""
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Distribution Package Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Package location: $OUTPUT_DIR/$PACKAGE_NAME"
echo ""
echo "Contents:"
echo "  - Docker images:     images/elk-stack-all-images.tar"
echo "  - Configurations:    config/"
echo "  - Deploy scripts:    deploy.sh, deploy.bat"
echo "  - Documentation:     DISTRIBUTION-README.md"
echo ""
echo "To deploy:"
echo "  Windows: cd $OUTPUT_DIR/$PACKAGE_NAME && deploy.bat"
echo "  Linux:   cd $OUTPUT_DIR/$PACKAGE_NAME && ./deploy.sh"
echo ""
echo -e "${YELLOW}Key Feature: Clients can modify all configs without rebuilding images!${NC}"
echo ""
