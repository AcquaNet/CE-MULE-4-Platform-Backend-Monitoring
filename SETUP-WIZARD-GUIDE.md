# ELK Stack Setup Wizard - User Guide

## Overview

The interactive setup wizard guides you through complete configuration of the ELK Stack, asking questions and automatically configuring all settings based on your answers.

**Time:** 5-10 minutes
**Skill Level:** Beginner-friendly

---

## Quick Start

### Windows
```cmd
setup-wizard.bat
```

### Linux/Mac
```bash
chmod +x setup-wizard.sh
./setup-wizard.sh
```

---

## What the Wizard Configures

### ✓ Checked Automatically
- Docker installation and status
- docker-compose availability
- Network prerequisites

### ⚙️ Configured Through Questions
1. **Basic Settings** - Deployment mode, environment, domain
2. **Security** - Passwords, authentication
3. **SSL/TLS** - HTTPS configuration
4. **Resources** - Memory allocation
5. **Services** - Which components to enable
6. **Backups** - Automatic backup configuration
7. **Log Retention** - How long to keep logs
8. **Network** - Port mappings, external access
9. **Review** - Confirm all settings
10. **Apply** - Create configuration files
11. **Start** - Launch services

---

## Step-by-Step Walkthrough

### Step 1: Basic Configuration

**Questions:**
- **Deployment mode:** Development / Production / Testing
- **Environment name:** dev / staging / prod
- **Domain:** Your domain or localhost

**Purpose:**
- Sets resource defaults based on mode
- Tags deployment for identification
- Configures access URLs

**Example:**
```
Select deployment mode:
  1. Development (single node, lower resources)
  2. Production (optimized, higher resources)
  3. Testing (minimal resources)
Enter choice [1-3]: 2

Environment name [dev]: prod
Domain or hostname [localhost]: elk.company.com
```

**Result:**
- Production mode selected (4GB ES, 2GB Logstash)
- Environment tagged as "prod"
- Services accessible at elk.company.com

---

### Step 2: Security Configuration

**Questions:**
- **Generate passwords?** Yes (recommended) / No

**What Gets Generated:**
- ElasticSearch password (elastic user)
- Kibana system password
- Logstash authentication token
- APM Server secret token
- Grafana admin password
- APISIX admin API key
- Encryption keys for Kibana and Grafana

**Example:**
```
Generate secure random passwords? (Y/n): Y
✓ Passwords generated successfully
⚠ Passwords will be saved in .env file
```

**Result:**
- All passwords auto-generated (25-64 characters)
- Saved to .env file
- You can view/change them in .env later

**Security Note:** Keep .env file secure - it contains all credentials!

---

### Step 3: SSL/TLS Configuration

**Questions:**
- **Enable SSL/TLS?** Yes / No
- **Certificate type:** Self-signed / Let's Encrypt / Custom
- **Force HTTPS?** Yes / No

**Certificate Types:**

#### Self-Signed (Development)
```
Enable SSL/TLS (HTTPS)? (y/N): y
Select SSL certificate type:
  1. Self-signed (for development/testing)
  2. Let's Encrypt (for production with public domain)
  3. Custom certificates (I'll provide my own)
Enter choice [1-3]: 1
Certificate validity (days) [3650]: 3650
Force HTTPS (redirect HTTP to HTTPS)? (Y/n): y
```

**Result:**
- Certificates generated automatically
- Valid for 10 years
- HTTP redirects to HTTPS

#### Let's Encrypt (Production)
```
Enter choice [1-3]: 2
Email for Let's Encrypt [admin@elk.company.com]: ops@company.com
Use Let's Encrypt staging server (for testing)? (y/N): n
```

**Requirements:**
- Public domain name (not localhost)
- DNS points to your server
- Port 80 accessible (for verification)

#### Custom Certificates
```
Enter choice [1-3]: 3
ℹ Place your certificates in:
  - certs/apisix/apisix.crt
  - certs/apisix/apisix.key
  - certs/ca/ca.crt
```

**When to Use:**
- Corporate CA certificates
- Existing wildcard certificates
- Specific compliance requirements

---

### Step 4: Resource Allocation

**Questions:**
- **Customize memory?** Yes / No
- **ElasticSearch memory:** (e.g., 2g, 4g)
- **Logstash memory:** (e.g., 1g, 2g)
- **Prometheus retention:** (e.g., 30d, 90d)

**Defaults by Mode:**

| Mode | ElasticSearch | Logstash | Use Case |
|------|---------------|----------|----------|
| Development | 2g | 1g | Local development |
| Production | 4g | 2g | Production workloads |
| Testing | 1g | 512m | CI/CD, testing |

**Example:**
```
Current default memory allocations (based on Production mode):
  - ElasticSearch: 4g
  - Logstash: 2g

Customize memory allocations? (y/N): y

Note: Use format like 1g, 2g, 512m, etc.
ElasticSearch memory (heap size) [4g]: 8g
Logstash memory (heap size) [2g]: 4g

Prometheus data retention period [30d]: 90d
```

**Guidelines:**
- ElasticSearch: 50% of system RAM, max 32GB
- Logstash: Based on pipeline complexity
- Prometheus: Based on metric retention needs

---

### Step 5: Service Selection

**Questions:**
- **Enable monitoring?** (Prometheus + Grafana)
- **Enable ES exporter?** (ElasticSearch metrics)
- **Enable alerting?** (Alertmanager)
- **Alert email:** notification address
- **SMTP settings:** mail server configuration

**Example:**
```
Enable monitoring (Prometheus + Grafana)? (Y/n): y
ℹ Prometheus and Grafana will be started

  Enable ElasticSearch metrics exporter? (Y/n): y

Enable alerting (Alertmanager)? (y/N): y
Email for alert notifications [admin@elk.company.com]: alerts@company.com

  SMTP server host [smtp.gmail.com]: smtp.sendgrid.net
  SMTP server port [587]: 587
  From email address [alerts@company.com]: noreply@company.com
  SMTP username [alerts@company.com]: apikey
  SMTP password: **********
```

**What You Get:**

With Monitoring:
- Prometheus (http://localhost:9080/prometheus)
- Grafana (http://localhost:9080/grafana)
- Pre-configured dashboards
- Metrics from all services

With Alerting:
- Email notifications for:
  - Service down
  - High memory usage
  - Disk space low
  - ElasticSearch cluster issues

---

### Step 6: Backup Configuration

**Questions:**
- **Enable backups?** Yes / No
- **Backup type:** Daily / Full / Weekly
- **Retention:** Days to keep
- **Location:** Local / Network / Cloud

**Backup Types:**

| Type | What Backs Up | When | Use Case |
|------|---------------|------|----------|
| Daily | Only today's indices | Every day 2 AM | Rolling backups |
| Full | All indices | Every day 2 AM | Complete backups |
| Weekly | All indices | Sunday 2 AM | Minimal storage |

**Example:**
```
Enable automatic backups? (y/N): y

Select backup type:
  1. Daily (only today's indices)
  2. Full (all indices)
  3. Weekly (all indices, once per week)
Enter choice [1-3]: 1

Keep backups for (days) [30]: 30
Maximum number of backups to keep [30]: 30

Backup storage location:
  1. Local (Docker volume)
  2. Network share (NFS/CIFS)
  3. Cloud (S3-compatible)
Enter choice [1-3]: 1
```

**Result:**
- Daily snapshots at 2 AM
- Keeps last 30 days
- Stored in Docker volume
- Auto-cleanup of old backups

---

### Step 7: Log Retention

**Questions:**
- **Retention period:** Days to keep logs
- **Rollover size:** When to create new index

**Example:**
```
Log retention period (days) [730]: 365
Index rollover size [1gb]: 5gb

ℹ Logs older than 365 days will be automatically deleted
```

**How It Works:**
- ElasticSearch deletes logs older than retention
- New index created daily or when size exceeded
- Applies to both mule-logs-* and logstash-* indices

**Recommendations:**

| Use Case | Retention | Rollover |
|----------|-----------|----------|
| Development | 30 days | 1gb |
| Production | 365 days | 5gb |
| Compliance | 2555 days (7 years) | 10gb |

---

### Step 8: Network Configuration

**Questions:**
- **Customize ports?** Yes / No
- **APISIX ports:** HTTP, HTTPS, Dashboard
- **External Logstash access?** TCP, Beats

**Default Ports:**
```
APISIX HTTP:       9080
APISIX HTTPS:      9443
APISIX Dashboard:  9000
APM Server:        8200
```

**External Logstash:**
```
Enable external Logstash TCP input (port 5000)? (y/N): y
Enable external Logstash Beats input (port 5044)? (y/N): y
```

**Use Cases:**
- CloudHub deployments need external Logstash
- Internal-only deployments keep Logstash internal
- Load balancer in front may need different ports

---

### Step 9: Review Configuration

**Shows Complete Summary:**
```
========================================
Configuration Summary
========================================

Basic Settings:
  Deployment Mode: Production
  Environment: prod
  Domain: elk.company.com

Security:
  SSL/TLS: true
  SSL Type: Let's Encrypt
  Force HTTPS: true
  Passwords: Auto-generated

Resources:
  ElasticSearch Memory: 8g
  Logstash Memory: 4g
  Prometheus Retention: 90d

Services:
  Monitoring: true
  Alerting: true
  ElasticSearch Exporter: true

Backup:
  Enabled: true
  Type: Daily
  Retention: 30 days
  Location: Local

Logs:
  Retention: 365 days
  Rollover Size: 5gb

Network:
  APISIX HTTP Port: 9080
  APISIX HTTPS Port: 9443
  External Logstash TCP: true
  External Logstash Beats: true

Proceed with this configuration? (Y/n):
```

**Options:**
- **Y** - Continue with setup
- **N** - Start over or cancel

---

### Step 10: Apply Configuration

**What Happens:**
1. Creates .env file with all settings
2. Generates SSL certificates (if selected)
3. Creates Docker networks
4. Configures backup system
5. Sets up alerting (if enabled)
6. Prepares log retention policies

**Console Output:**
```
========================================
Applying Configuration
========================================

ℹ Creating .env file...
✓ .env file created

ℹ Generating self-signed certificates...
✓ Certificates generated

ℹ Creating Docker networks...
✓ Networks ready

ℹ Configuring backup system...
✓ Backup configuration ready

✓ Configuration applied successfully
```

**Files Created:**
- `.env` - Main configuration
- `certs/` - SSL certificates
- Docker networks created

---

### Step 11: Start Services

**Questions:**
- **Start now?** Yes / No

**If Yes:**
```
========================================
Starting Services
========================================

ℹ Starting services...

Creating network "ce-base-micronet" ... done
Creating elasticsearch ... done
Creating kibana ... done
Creating logstash ... done
Creating apisix ... done
Creating prometheus ... done
Creating grafana ... done

✓ Services started!
ℹ Waiting for services to become healthy (this may take 2-3 minutes)...

NAME            STATE    STATUS
elasticsearch   running  healthy
kibana          running  healthy
logstash        running  healthy
apisix          running  healthy
prometheus      running  healthy
grafana         running  healthy
```

**If No:**
```
ℹ Services not started

To start services later, run:
  docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d
```

---

### Final Summary

**Shows Access Information:**
```
========================================
Setup Complete!
========================================

Your ELK Stack has been configured successfully!

Access your services:
  • Kibana:           https://elk.company.com:9443/kibana
  • APISIX Dashboard: https://elk.company.com:9000
  • Grafana:          https://elk.company.com:9443/grafana
  • Prometheus:       https://elk.company.com:9443/prometheus

Login Credentials:
  • Kibana:     elastic / (see .env file for ELASTIC_PASSWORD)
  • Grafana:    admin / (see .env file for GRAFANA_ADMIN_PASSWORD)
  • APISIX:     admin / admin

Important Files:
  • Configuration: .env
  • Passwords: .env (keep secure!)
  • SSL Certificates: certs/

Useful Commands:
  • Check status:  docker-compose ps
  • View logs:     docker-compose logs -f
  • Stop services: docker-compose down
  • Restart:       docker-compose restart

Backups:
  • Configured: Daily backups
  • Retention: 30 days
  • Manual backup: ./config/scripts/backup/backup.sh

ℹ For detailed documentation, see README.md and docs/

✓ Happy logging! 📊
```

---

## Common Scenarios

### Scenario 1: Development Setup

**Goal:** Quick local development environment

**Choices:**
```
Deployment mode: 1 (Development)
Environment: dev
Domain: localhost
SSL: No
Customize memory: No (use defaults)
Monitoring: Yes
Alerting: No
Backups: No
Log retention: 30 days
External Logstash: No
```

**Result:**
- Fast setup (< 2 minutes)
- HTTP only (no SSL overhead)
- Minimal resources
- Basic monitoring
- Accessible at http://localhost:9080

---

### Scenario 2: Production Deployment

**Goal:** Secure, robust production environment

**Choices:**
```
Deployment mode: 2 (Production)
Environment: prod
Domain: elk.company.com
SSL: Yes - Let's Encrypt
Force HTTPS: Yes
Customize memory: Yes (8g ES, 4g Logstash)
Monitoring: Yes
ElasticSearch exporter: Yes
Alerting: Yes (with email)
Backups: Yes - Daily, 30 days retention
Log retention: 365 days
External Logstash: Yes (if needed for CloudHub)
```

**Result:**
- Secure HTTPS with valid certificates
- High performance
- Complete monitoring and alerting
- Automatic backups
- Production-ready

---

### Scenario 3: Testing/CI Environment

**Goal:** Minimal resources for automated testing

**Choices:**
```
Deployment mode: 3 (Testing)
Environment: test
Domain: localhost
SSL: No
Customize memory: No
Monitoring: No
Backups: No
Log retention: 7 days
```

**Result:**
- Minimal resource usage
- Fast startup
- Auto-cleanup after 7 days
- Suitable for CI/CD pipelines

---

## After Setup

### View Passwords

```bash
cat .env | grep PASSWORD
```

**Output:**
```
ELASTIC_PASSWORD=a3k9j2h8g4f7d5s1w0e6r8t9
KIBANA_PASSWORD=p4l9m2n8b6v5c3x1z0q7w3e5
GRAFANA_ADMIN_PASSWORD=k8j9h7g6f5d4s3a2w1e0r9t8
```

### Change Configuration Later

Edit `.env` file:
```bash
nano .env
```

Apply changes:
```bash
docker-compose restart
```

### Re-run Wizard

```bash
./setup-wizard.sh
```

Wizard will detect existing `.env` and ask if you want to overwrite.

---

## Troubleshooting

### Wizard Won't Start

**Problem:** Permission denied
```bash
chmod +x setup-wizard.sh
./setup-wizard.sh
```

**Problem:** Docker not running
```
Start Docker Desktop first, then run wizard
```

### Certificate Generation Fails

**Problem:** openssl not installed

**Linux:**
```bash
sudo apt-get install openssl
```

**Mac:**
```bash
brew install openssl
```

**Windows:**
```
Included with Git Bash or WSL
```

### Services Don't Start

**Check logs:**
```bash
docker-compose logs -f
```

**Common issues:**
- Not enough memory (increase in .env)
- Ports already in use (change in .env)
- Networks not created (re-run wizard)

### Can't Access Services

**Check firewall:**
```bash
# Allow port 9080 (HTTP)
sudo ufw allow 9080

# Allow port 9443 (HTTPS)
sudo ufw allow 9443
```

**Check services are healthy:**
```bash
docker-compose ps
```

All should show "healthy" status.

---

## Tips

### ✓ Use Recommended Defaults

For most settings, the defaults are optimized. Only customize if needed.

### ✓ Enable Monitoring

Always enable Prometheus + Grafana - they're lightweight and very useful.

### ✓ Start with Self-Signed SSL

Test with self-signed first, then switch to Let's Encrypt for production.

### ✓ Review Before Applying

Carefully review the summary in Step 9 - easier to fix there than after.

### ✓ Save .env File

Back up .env file - it contains all your passwords and configuration.

---

## Next Steps

After wizard completes:

1. **Wait 2-3 minutes** for all services to become healthy
2. **Access Kibana** at configured URL
3. **Login** with credentials from .env
4. **Configure data views** (auto-created for mule-logs-*)
5. **View logs** in Discover
6. **Create dashboards** in Kibana
7. **Set up alerts** in Prometheus/Grafana

---

## Support

- **Stuck?** Check troubleshooting section
- **Questions?** See full documentation in `docs/`
- **Issues?** Review logs with `docker-compose logs`

---

**Created for:** ELK Stack v8.11.3
**Last Updated:** 2026-01-02
