# SSL/TLS Setup Guide

Complete guide to securing the ELK Stack platform with SSL/TLS encryption.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Quick Start](#quick-start)
3. [Prerequisites](#prerequisites)
4. [Development Setup (Self-Signed Certificates)](#development-setup-self-signed-certificates)
5. [Production Setup (Let's Encrypt)](#production-setup-lets-encrypt)
6. [Production Setup (Commercial CA)](#production-setup-commercial-ca)
7. [Service-Specific Configuration](#service-specific-configuration)
8. [Inter-Service Communication](#inter-service-communication)
9. [Docker Compose SSL Profiles](#docker-compose-ssl-profiles)
10. [Certificate Management](#certificate-management)
11. [Troubleshooting](#troubleshooting)
12. [Security Best Practices](#security-best-practices)
13. [Migration from HTTP to HTTPS](#migration-from-http-to-https)
14. [Testing and Verification](#testing-and-verification)
15. [Performance Considerations](#performance-considerations)

---

## Introduction

### What is SSL/TLS?

**SSL (Secure Sockets Layer)** and **TLS (Transport Layer Security)** are cryptographic protocols that provide secure communication over a network. TLS is the successor to SSL, though the term "SSL" is still commonly used.

**Key Benefits:**
- **Encryption**: Protects data in transit from eavesdropping
- **Authentication**: Verifies the identity of services
- **Integrity**: Ensures data hasn't been tampered with during transmission

### SSL Architecture: Termination at Gateway

This platform uses **SSL termination at the APISIX gateway** for simplified SSL management:

```
External Client (HTTPS)
        ↓
  APISIX Gateway (port 9443)
  [SSL/TLS Termination]
        ↓
Internal Services (HTTP on trusted Docker network)
  - ElasticSearch
  - Kibana
  - Logstash
  - Prometheus
  - Grafana
  - Alertmanager
```

**Active SSL Certificates:**
- **APISIX Gateway** (`certs/apisix/`) - Terminates SSL for all external traffic
- **APM Server** (`certs/apm-server/`) - Direct HTTPS endpoint (port 8200 exposed for CloudHub)
- **CA Certificate** (`certs/ca/`) - Certificate Authority for signing

**Optional SSL Certificates** (`certs/extra/`):
- ElasticSearch, Kibana, Logstash, Prometheus, Grafana, Alertmanager
- Only needed for compliance requirements (HIPAA, PCI-DSS, zero-trust architecture)
- See [Optional: End-to-End Encryption](#optional-end-to-end-encryption) section

### Why SSL/TLS is Important

For the ELK Stack platform, SSL/TLS provides:

1. **Data Protection**: ElasticSearch credentials, log data, and API keys are encrypted
2. **Compliance**: Required for GDPR, HIPAA, PCI-DSS, and other regulations
3. **Trust**: Browsers show "secure" indicators instead of warnings
4. **Defense in Depth**: Additional security layer beyond authentication

### When to Use SSL/TLS

| Environment | SSL/TLS Required? | Certificate Type | Architecture |
|-------------|-------------------|------------------|--------------|
| **Development** | Optional | Self-signed | SSL termination at gateway |
| **Testing/QA** | Recommended | Self-signed or Let's Encrypt | SSL termination at gateway |
| **Production (Internal)** | Highly Recommended | Self-signed or Internal CA | SSL termination at gateway |
| **Production (Public)** | **Required** | Let's Encrypt or Commercial CA | SSL termination at gateway |
| **HIPAA/PCI-DSS** | **Required** | Commercial CA | End-to-end encryption (see Optional section) |

---

## Quick Start

Choose your deployment path:

### Path 1: Development (Self-Signed Certificates)

**Best for:** Local development, internal testing, air-gapped environments

```bash
# 1. Generate active certificates (APISIX + APM Server only)
./config/scripts/setup/generate-certs.sh --active-only

# 2. Enable SSL in .env
echo "SSL_ENABLED=true" >> .env

# 3. Start with SSL configuration
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d

# 4. Test HTTPS access
curl -k https://localhost:9443/apisix/status
curl -k https://localhost:8200/
```

**Time Required:** 3 minutes

**Note:** This generates only the required certificates for SSL termination at the gateway. For end-to-end encryption, run without `--active-only`.

### Path 2: Production (Let's Encrypt - Free)

**Best for:** Public-facing deployments with domain names

```bash
# 1. Ensure domain points to your server
# 2. Run Let's Encrypt setup
./config/scripts/setup/setup-letsencrypt.sh \
  --domain your-domain.com \
  --email admin@your-domain.com

# 3. Enable SSL in .env
echo "SSL_ENABLED=true" >> .env
echo "SSL_DOMAIN=your-domain.com" >> .env

# 4. Start with SSL configuration
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d

# 5. Test HTTPS access
curl https://your-domain.com:9443/apisix/status
```

**Time Required:** 10 minutes

**Requirements:**
- Domain name pointing to server IP
- Ports 80 and 443 accessible from internet
- Valid email address

### Path 3: Production (Commercial CA)

**Best for:** Enterprise deployments, strict compliance requirements

```bash
# 1. Obtain certificates from commercial CA (DigiCert, GlobalSign, etc.)
# 2. Place APISIX certificates in certs/apisix/
# 3. Place APM Server certificates in certs/apm-server/
# 4. Enable SSL in .env
echo "SSL_ENABLED=true" >> .env

# 5. Start with SSL configuration
docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d

# 6. Test HTTPS access
curl https://your-domain.com:9443/apisix/status
```

**Time Required:** 20 minutes (plus CA processing time)

**Requirements:**
- Valid certificates from CA for APISIX gateway
- Valid certificates from CA for APM Server (if used)
- Intermediate certificates (chain)
- Private keys

**Note:** Only APISIX and APM Server need certificates. Internal services communicate over HTTP on the trusted Docker network.

---

## Prerequisites

### System Requirements

- **Operating System**: Linux, macOS, or Windows with WSL2
- **Docker**: Version 20.10 or later
- **Docker Compose**: Version 1.29 or later
- **Disk Space**: 500 MB for certificates and backups

### Required Tools

**For Self-Signed Certificates:**
```bash
# Check OpenSSL is installed
openssl version
# OpenSSL 1.1.1 or later required
```

**For Let's Encrypt:**
```bash
# certbot will be installed via Docker if not present
# OR install manually:
# Ubuntu/Debian
sudo apt-get install certbot

# CentOS/RHEL
sudo yum install certbot

# macOS
brew install certbot
```

### Network Requirements

**For Self-Signed:**
- No external network access required

**For Let's Encrypt:**
- Domain name pointing to server IP (A record)
- Ports 80 and 443 open to internet
- No firewall blocking ACME challenge requests

**For Commercial CA:**
- Ability to prove domain ownership (varies by CA)
- May require domain validation via DNS or email

### Before You Begin

Ensure the following are in place:

- Strong passwords configured (see `SECURITY_SETUP.md`)
- `.env` file created with secure credentials
- Firewall configured to allow only necessary traffic
- Backup plan for certificates and keys
- Password manager ready for storing certificate passphrases

---

## Development Setup (Self-Signed Certificates)

Self-signed certificates are perfect for development, testing, and internal deployments where browsers/clients can trust the custom CA.

### SSL Termination at Gateway (Default)

By default, the platform uses SSL termination at the APISIX gateway:
- **External traffic**: Encrypted HTTPS (port 9443)
- **Internal services**: Unencrypted HTTP on trusted Docker network
- **APM Server**: HTTPS (port 8200) for direct CloudHub connections

This approach provides:
- ✅ Simple configuration (only 2 services need certificates)
- ✅ Better performance (less encryption overhead)
- ✅ Easier certificate management
- ✅ Secure external access
- ✅ Trusted internal network

### Step 1: Generate Certificates

**Option A: Active Certificates Only (Recommended)**

Generate only the required certificates for SSL termination:

```bash
./config/scripts/setup/generate-certs.sh --active-only
```

This creates:
- `certs/ca/` - Certificate Authority
- `certs/apisix/` - APISIX gateway certificates
- `certs/apm-server/` - APM Server certificates

**Option B: All Certificates (For Compliance)**

Generate certificates for all services including optional end-to-end encryption:

```bash
./config/scripts/setup/generate-certs.sh
```

This creates all certificates above plus optional ones in `certs/extra/` for:
- ElasticSearch, Kibana, Logstash, Prometheus, Grafana, Alertmanager

See [Optional: End-to-End Encryption](#optional-end-to-end-encryption) for when to use this option.

**Advanced Options:**

```bash
# Custom domain name (default: localhost)
./config/scripts/setup/generate-certs.sh --domain dev.example.internal

# Custom validity period (default: 3650 days = 10 years)
./config/scripts/setup/generate-certs.sh --days 730  # 2 years

# Force overwrite existing certificates
./config/scripts/setup/generate-certs.sh --force

# Generate only CA certificate (no service certs)
./config/scripts/setup/generate-certs.sh --ca-only

# Generate only active certificates (APISIX + APM Server + CA)
./config/scripts/setup/generate-certs.sh --active-only
```

### Step 2: Understanding Generated Certificates

**With `--active-only` (Recommended):**

The script creates certificates only for SSL termination:

```
certs/
├── ca/
│   ├── ca.crt                    # Certificate Authority certificate
│   └── ca.key                    # CA private key (PROTECT THIS!)
├── apisix/
│   ├── apisix.crt                # APISIX gateway certificate
│   ├── apisix.key                # APISIX private key
│   ├── apisix.csr                # Certificate signing request
│   └── apisix.cnf                # OpenSSL configuration
└── apm-server/
    ├── apm-server.crt            # APM Server certificate
    ├── apm-server.key            # APM Server private key
    ├── apm-server.csr            # Certificate signing request
    └── apm-server.cnf            # OpenSSL configuration
```

**Without `--active-only` (For Compliance):**

The script creates all certificates including optional end-to-end encryption:

```
certs/
├── ca/                           # Certificate Authority (ACTIVE)
│   ├── ca.crt
│   └── ca.key
├── apisix/                       # APISIX Gateway (ACTIVE)
│   ├── apisix.crt
│   ├── apisix.key
│   ├── apisix.csr
│   └── apisix.cnf
├── apm-server/                   # APM Server (ACTIVE)
│   ├── apm-server.crt
│   ├── apm-server.key
│   ├── apm-server.csr
│   └── apm-server.cnf
└── extra/                        # Optional end-to-end encryption
    ├── elasticsearch/
    │   ├── elasticsearch.crt
    │   ├── elasticsearch.key
    │   ├── elasticsearch.p12     # PKCS#12 bundle (password: changeit)
    │   ├── elasticsearch.csr
    │   └── elasticsearch.cnf
    ├── kibana/
    │   ├── kibana.crt
    │   ├── kibana.key
    │   ├── kibana.csr
    │   └── kibana.cnf
    ├── logstash/
    │   ├── logstash.crt
    │   ├── logstash.key
    │   ├── logstash.csr
    │   └── logstash.cnf
    │   ├── prometheus.crt
    │   ├── prometheus.key
    │   ├── prometheus.csr
    │   └── prometheus.cnf
    ├── grafana/
    │   ├── grafana.crt
    │   ├── grafana.key
    │   ├── grafana.csr
    │   └── grafana.cnf
    └── alertmanager/
        ├── alertmanager.crt
        ├── alertmanager.key
        ├── alertmanager.csr
        └── alertmanager.cnf
```

**Certificate Details:**

**Active Certificates (SSL Termination):**

| Component | Common Name | Subject Alternative Names | Port |
|-----------|-------------|---------------------------|------|
| APISIX | apisix | apisix, localhost, your-domain, 127.0.0.1, 172.42.0.20 | 9443 (HTTPS) |
| APM Server | apm-server | apm-server, localhost, your-domain, 127.0.0.1, 172.42.0.13 | 8200 (HTTPS) |

**Optional Certificates (End-to-End Encryption in `certs/extra/`):**

| Component | Common Name | Subject Alternative Names | Internal Port |
|-----------|-------------|---------------------------|---------------|
| ElasticSearch | elasticsearch | elasticsearch, localhost, your-domain, 127.0.0.1, 172.42.0.10 | 9200 (HTTP) |
| Kibana | kibana | kibana, localhost, your-domain, 127.0.0.1, 172.42.0.12 | 5601 (HTTP) |
| Logstash | logstash | logstash, localhost, your-domain, 127.0.0.1, 172.42.0.11 | 9600 (HTTP) |
| Prometheus | prometheus | prometheus, localhost, your-domain, 127.0.0.1, 172.42.0.23 | 9090 (HTTP) |
| Grafana | grafana | grafana, localhost, your-domain, 127.0.0.1, 172.42.0.24 | 3000 (HTTP) |
| Alertmanager | alertmanager | alertmanager, localhost, your-domain, 127.0.0.1, 172.42.0.25 | 9093 (HTTP) |

**File Permissions:**
- `.key` files: `600` (read/write for owner only)
- `.crt` files: `644` (readable by all, writable by owner)
- Directories: `755` (readable/executable by all)

### Step 3: Configure Environment Variables

Edit your `.env` file:

```bash
# SSL/TLS Configuration
SSL_ENABLED=true
SSL_DOMAIN=localhost

# SSL Certificate Paths (relative to project root)
SSL_CERT_PATH=./certs
CA_CERT_PATH=./certs/ca/ca.crt

# ElasticSearch SSL
XPACK_SECURITY_ENABLED=true
XPACK_SECURITY_HTTP_SSL_ENABLED=true
XPACK_SECURITY_TRANSPORT_SSL_ENABLED=true

# Certificate verification (set to 'none' for self-signed, 'certificate' for CA-signed)
SSL_VERIFICATION_MODE=certificate
```

### Step 4: Update Docker Compose Configuration

Add SSL volume mounts to `docker-compose.yml`:

```yaml
services:
  elasticsearch:
    environment:
      - xpack.security.http.ssl.enabled=true
      - xpack.security.http.ssl.key=/usr/share/elasticsearch/config/certificates/elasticsearch.key
      - xpack.security.http.ssl.certificate=/usr/share/elasticsearch/config/certificates/elasticsearch.crt
      - xpack.security.http.ssl.certificate_authorities=/usr/share/elasticsearch/config/certificates/ca.crt
      - xpack.security.transport.ssl.enabled=true
      - xpack.security.transport.ssl.key=/usr/share/elasticsearch/config/certificates/elasticsearch.key
      - xpack.security.transport.ssl.certificate=/usr/share/elasticsearch/config/certificates/elasticsearch.crt
      - xpack.security.transport.ssl.certificate_authorities=/usr/share/elasticsearch/config/certificates/ca.crt
      - xpack.security.transport.ssl.verification_mode=certificate
    volumes:
      - ./certs/elasticsearch:/usr/share/elasticsearch/config/certificates:ro
      - ./certs/ca:/usr/share/elasticsearch/config/ca-certificates:ro
    ports:
      - "9443:9200"  # HTTPS port (mapped from 9200)
```

**Note:** Full SSL configuration examples are provided in the [Service-Specific Configuration](#service-specific-configuration) section.

### Step 5: Start Services with SSL

```bash
# Start all services with SSL profile
docker-compose --profile ssl up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f
```

### Step 6: Test HTTPS Access

```bash
# Test ElasticSearch HTTPS (self-signed, use -k to skip verification)
curl -k -u elastic:${ELASTIC_PASSWORD} \
  https://localhost:9443/_cluster/health?pretty

# Test via APISIX gateway
curl -k https://localhost:9443/elasticsearch/_cluster/health?pretty

# Test Kibana HTTPS
curl -k https://localhost:5601/api/status

# Test Prometheus HTTPS
curl -k https://localhost:9091/metrics
```

### Step 7: Trust the CA Certificate (Optional)

To avoid browser warnings and `-k` flag in curl, trust the CA certificate:

**Linux (Ubuntu/Debian):**
```bash
sudo cp certs/ca/ca.crt /usr/local/share/ca-certificates/elk-stack-ca.crt
sudo update-ca-certificates
```

**Linux (CentOS/RHEL):**
```bash
sudo cp certs/ca/ca.crt /etc/pki/ca-trust/source/anchors/elk-stack-ca.crt
sudo update-ca-trust
```

**macOS:**
```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain certs/ca/ca.crt
```

**Windows:**
1. Double-click `certs/ca/ca.crt`
2. Click "Install Certificate"
3. Select "Local Machine"
4. Choose "Place all certificates in the following store"
5. Select "Trusted Root Certification Authorities"
6. Click "Finish"

**Browser (Firefox):**
1. Firefox → Settings → Privacy & Security
2. Scroll to "Certificates" → View Certificates
3. Authorities tab → Import
4. Select `certs/ca/ca.crt`
5. Check "Trust this CA to identify websites"
6. Click OK

### Step 8: Verify Certificate Installation

```bash
# Test without -k flag (should work if CA is trusted)
curl -u elastic:${ELASTIC_PASSWORD} \
  https://localhost:9443/_cluster/health?pretty

# View certificate details
openssl s_client -connect localhost:9443 -showcerts

# Check certificate expiration
echo | openssl s_client -connect localhost:9443 2>/dev/null | \
  openssl x509 -noout -dates
```

---

## Production Setup (Let's Encrypt)

Let's Encrypt provides free, automated SSL certificates trusted by all major browsers. Perfect for public-facing deployments.

### Prerequisites

Before starting, ensure:

1. **Domain Name**: You own a domain name (e.g., `elk.example.com`)
2. **DNS Configuration**: Domain's A record points to your server's public IP
3. **Port Access**: Ports 80 and 443 are open and accessible from internet
4. **Email Address**: Valid email for certificate expiration notifications

### Step 1: Verify Domain Configuration

```bash
# Check DNS resolution
dig +short elk.example.com
# Should return your server's public IP

# Check your public IP
curl ifconfig.me

# Verify port 80 is accessible
curl http://elk.example.com
```

### Step 2: Run Let's Encrypt Setup Script

**Method 1: Standalone Mode (Recommended for Initial Setup)**

Requires temporarily stopping APISIX to use port 80:

```bash
./config/scripts/setup/setup-letsencrypt.sh \
  --domain elk.example.com \
  --email admin@example.com \
  --standalone
```

**Method 2: Webroot Mode (Works with Running Web Server)**

If you have a web server running that can serve ACME challenge files:

```bash
./config/scripts/setup/setup-letsencrypt.sh \
  --domain elk.example.com \
  --email admin@example.com \
  --webroot /var/www/html
```

**Method 3: Staging Mode (For Testing)**

Test with Let's Encrypt staging server (doesn't count against rate limits):

```bash
./config/scripts/setup/setup-letsencrypt.sh \
  --domain elk.example.com \
  --email admin@example.com \
  --staging
```

### Step 3: Understanding Let's Encrypt Certificates

After successful setup, certificates are stored in:

```
letsencrypt/
├── config/
│   └── live/
│       └── elk.example.com/
│           ├── fullchain.pem     # Full certificate chain
│           ├── privkey.pem       # Private key
│           ├── cert.pem          # Domain certificate only
│           └── chain.pem         # Intermediate certificates
├── work/                         # Working directory
├── logs/                         # Certbot logs
└── webroot/                      # ACME challenge directory
```

These are automatically copied to:

```
certs/
├── apisix/
│   ├── apisix.crt               # Copy of fullchain.pem
│   ├── apisix.key               # Copy of privkey.pem
│   └── ca.crt                   # Copy of chain.pem
├── elasticsearch/               # Same certificates
├── kibana/                      # Same certificates
└── logstash/                    # Same certificates
```

### Step 4: Configure Environment Variables

Update `.env` file:

```bash
# SSL/TLS Configuration
SSL_ENABLED=true
SSL_DOMAIN=elk.example.com

# Let's Encrypt email
LETSENCRYPT_EMAIL=admin@example.com

# ElasticSearch SSL
XPACK_SECURITY_ENABLED=true
XPACK_SECURITY_HTTP_SSL_ENABLED=true
XPACK_SECURITY_TRANSPORT_SSL_ENABLED=true

# Use full verification for production
SSL_VERIFICATION_MODE=full
```

### Step 5: Configure Docker Compose for Let's Encrypt

Services use the same certificate (wildcard or SAN):

```yaml
services:
  elasticsearch:
    environment:
      - xpack.security.http.ssl.enabled=true
      - xpack.security.http.ssl.key=/usr/share/elasticsearch/config/certificates/elasticsearch.key
      - xpack.security.http.ssl.certificate=/usr/share/elasticsearch/config/certificates/elasticsearch.crt
      - xpack.security.http.ssl.certificate_authorities=/usr/share/elasticsearch/config/certificates/ca.crt
      - xpack.security.http.ssl.verification_mode=full
    volumes:
      - ./certs/elasticsearch:/usr/share/elasticsearch/config/certificates:ro
```

### Step 6: Set Up Automatic Renewal

Let's Encrypt certificates expire after 90 days. Set up automatic renewal:

```bash
# Add to crontab (runs daily at 3 AM)
crontab -e

# Add this line:
0 3 * * * /path/to/Docker\ ElasticSearc./config/scripts/setup/renew-letsencrypt.sh >> /var/log/letsencrypt-renewal.log 2>&1
```

**Manual Renewal Test:**

```bash
# Test renewal without actually renewing
./config/scripts/setup/renew-letsencrypt.sh --dry-run

# Force renewal
./config/scripts/setup/renew-letsencrypt.sh --force
```

### Step 7: Start Services with SSL

```bash
docker-compose --profile ssl up -d
```

### Step 8: Verify HTTPS Access

```bash
# Test ElasticSearch (should work without -k flag)
curl -u elastic:${ELASTIC_PASSWORD} \
  https://elk.example.com:9443/_cluster/health?pretty

# Test via APISIX gateway
curl https://elk.example.com:9443/elasticsearch/_cluster/health?pretty

# Check SSL certificate in browser
# Navigate to: https://elk.example.com:9443/kibana
# Click padlock icon to view certificate details
```

### Step 9: Monitor Certificate Expiration

```bash
# Check certificate expiration
openssl s_client -connect elk.example.com:9443 -servername elk.example.com 2>/dev/null | \
  openssl x509 -noout -dates

# View certificate details
openssl s_client -connect elk.example.com:9443 -servername elk.example.com 2>/dev/null | \
  openssl x509 -noout -text

# Check renewal logs
tail -f /var/log/letsencrypt-renewal.log
```

### Let's Encrypt Rate Limits

Be aware of Let's Encrypt rate limits:

- **50 certificates per registered domain per week**
- **5 duplicate certificates per week** (same exact set of hostnames)
- **300 new accounts per IP per 3 hours**
- **10 failed validations per hour**

**Tips to Avoid Rate Limits:**
1. Use `--staging` flag for testing
2. Don't delete and recreate certificates unnecessarily
3. Use renewal instead of new certificate requests
4. Group multiple subdomains into one certificate

---

## Production Setup (Commercial CA)

For enterprises requiring commercially trusted certificates (DigiCert, GlobalSign, Comodo, etc.).

### Step 1: Generate Certificate Signing Request (CSR)

```bash
# Create directory for commercial certificates
mkdir -p certs/commercial

# Generate private key (4096-bit for maximum security)
openssl genrsa -out certs/commercial/server.key 4096

# Generate CSR
openssl req -new -key certs/commercial/server.key \
  -out certs/commercial/server.csr \
  -subj "/C=US/ST=California/L=San Francisco/O=Your Company/CN=elk.example.com"
```

**With Subject Alternative Names (SAN):**

```bash
# Create OpenSSL configuration
cat > certs/commercial/server.cnf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = California
L = San Francisco
O = Your Company
OU = IT Department
CN = elk.example.com

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = elk.example.com
DNS.2 = *.elk.example.com
DNS.3 = elasticsearch.example.com
DNS.4 = kibana.example.com
IP.1 = 203.0.113.42
EOF

# Generate CSR with SAN
openssl req -new -key certs/commercial/server.key \
  -out certs/commercial/server.csr \
  -config certs/commercial/server.cnf
```

### Step 2: Submit CSR to Certificate Authority

1. **Choose a CA**: DigiCert, GlobalSign, Sectigo, etc.
2. **Select Certificate Type**:
   - **Domain Validation (DV)**: Fastest, validates domain ownership only
   - **Organization Validation (OV)**: Validates organization details
   - **Extended Validation (EV)**: Highest trust, green bar in browsers
3. **Submit CSR**: Paste contents of `server.csr` into CA's order form
4. **Complete Validation**: Follow CA's validation process
5. **Download Certificates**: Save certificate and intermediate chain

### Step 3: Install Downloaded Certificates

CA will provide:
- `server.crt` or `domain.crt`: Your domain certificate
- `intermediate.crt` or `ca-bundle.crt`: Intermediate certificates
- `root.crt`: Root CA certificate (often already trusted)

**Create Full Chain:**

```bash
# Combine domain certificate and intermediate certificates
cat certs/commercial/server.crt \
    certs/commercial/intermediate.crt \
    > certs/commercial/fullchain.crt

# OR if CA provides separate intermediate certificates:
cat certs/commercial/server.crt \
    certs/commercial/intermediate1.crt \
    certs/commercial/intermediate2.crt \
    certs/commercial/root.crt \
    > certs/commercial/fullchain.crt
```

### Step 4: Deploy Certificates to Services

```bash
# Copy to service directories
cp certs/commercial/fullchain.crt certs/elasticsearch/elasticsearch.crt
cp certs/commercial/server.key certs/elasticsearch/elasticsearch.key
cp certs/commercial/intermediate.crt certs/elasticsearch/ca.crt

cp certs/commercial/fullchain.crt certs/kibana/kibana.crt
cp certs/commercial/server.key certs/kibana/kibana.key

cp certs/commercial/fullchain.crt certs/logstash/logstash.crt
cp certs/commercial/server.key certs/logstash/logstash.key

cp certs/commercial/fullchain.crt certs/apisix/apisix.crt
cp certs/commercial/server.key certs/apisix/apisix.key

# Set permissions
chmod 600 certs/*/server.key certs/*/*.key
chmod 644 certs/*/fullchain.crt certs/*/*.crt
```

### Step 5: Create PKCS#12 Bundle (for ElasticSearch)

ElasticSearch can use PKCS#12 format:

```bash
openssl pkcs12 -export \
  -out certs/elasticsearch/elasticsearch.p12 \
  -in certs/commercial/fullchain.crt \
  -inkey certs/commercial/server.key \
  -name "elasticsearch" \
  -passout pass:changeit
```

Update `.env`:
```bash
ELASTIC_SSL_KEYSTORE_PASSWORD=changeit
```

### Step 6: Configure Docker Compose

```yaml
services:
  elasticsearch:
    environment:
      - xpack.security.http.ssl.enabled=true
      - xpack.security.http.ssl.keystore.path=/usr/share/elasticsearch/config/certificates/elasticsearch.p12
      - xpack.security.http.ssl.keystore.password=${ELASTIC_SSL_KEYSTORE_PASSWORD}
      - xpack.security.http.ssl.truststore.path=/usr/share/elasticsearch/config/certificates/elasticsearch.p12
      - xpack.security.http.ssl.truststore.password=${ELASTIC_SSL_KEYSTORE_PASSWORD}
    volumes:
      - ./certs/elasticsearch:/usr/share/elasticsearch/config/certificates:ro
```

### Step 7: Verify Certificate Chain

```bash
# Verify certificate chain
openssl verify -CAfile certs/commercial/root.crt \
  -untrusted certs/commercial/intermediate.crt \
  certs/commercial/server.crt

# Should output: server.crt: OK

# Test SSL connection
openssl s_client -connect elk.example.com:9443 \
  -CAfile certs/commercial/root.crt \
  -showcerts
```

### Step 8: Set Up Renewal Reminders

Commercial certificates typically last 1-2 years. Set reminders:

```bash
# Check certificate expiration
openssl x509 -in certs/commercial/server.crt -noout -enddate

# Add to crontab (check monthly, alert 60 days before expiry)
crontab -e

# Add:
0 0 1 * * /path/to/config/scripts/setup/check-cert-expiry.sh
```

**Create expiration check script:**

```bash
cat > scripts/check-cert-expiry.sh <<'EOF'
#!/bin/bash
CERT_FILE="certs/commercial/server.crt"
ALERT_DAYS=60

EXPIRY_DATE=$(openssl x509 -in "$CERT_FILE" -noout -enddate | cut -d= -f2)
EXPIRY_EPOCH=$(date -d "$EXPIRY_DATE" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( ($EXPIRY_EPOCH - $NOW_EPOCH) / 86400 ))

if [ $DAYS_LEFT -lt $ALERT_DAYS ]; then
  echo "WARNING: SSL certificate expires in $DAYS_LEFT days!"
  echo "Certificate: $CERT_FILE"
  echo "Expiry date: $EXPIRY_DATE"
  # Send email alert
  echo "SSL certificate expires in $DAYS_LEFT days" | \
    mail -s "SSL Certificate Expiration Warning" admin@example.com
fi
EOF

chmod +x scripts/check-cert-expiry.sh
```

---

## Service-Specific Configuration

Detailed SSL/TLS configuration for each service in the platform.

### ElasticSearch

**Configuration Options:**

```yaml
services:
  elasticsearch:
    environment:
      # Enable SSL for HTTP API
      - xpack.security.http.ssl.enabled=true

      # PEM format (recommended for Let's Encrypt/self-signed)
      - xpack.security.http.ssl.key=/usr/share/elasticsearch/config/certificates/elasticsearch.key
      - xpack.security.http.ssl.certificate=/usr/share/elasticsearch/config/certificates/elasticsearch.crt
      - xpack.security.http.ssl.certificate_authorities=/usr/share/elasticsearch/config/certificates/ca.crt

      # OR PKCS#12 format (recommended for commercial CA)
      # - xpack.security.http.ssl.keystore.path=/usr/share/elasticsearch/config/certificates/elasticsearch.p12
      # - xpack.security.http.ssl.keystore.password=${ELASTIC_SSL_KEYSTORE_PASSWORD}
      # - xpack.security.http.ssl.truststore.path=/usr/share/elasticsearch/config/certificates/elasticsearch.p12
      # - xpack.security.http.ssl.truststore.password=${ELASTIC_SSL_KEYSTORE_PASSWORD}

      # Enable SSL for transport layer (node-to-node communication)
      - xpack.security.transport.ssl.enabled=true
      - xpack.security.transport.ssl.key=/usr/share/elasticsearch/config/certificates/elasticsearch.key
      - xpack.security.transport.ssl.certificate=/usr/share/elasticsearch/config/certificates/elasticsearch.crt
      - xpack.security.transport.ssl.certificate_authorities=/usr/share/elasticsearch/config/certificates/ca.crt

      # Verification mode: none, certificate, full
      # - none: No verification (insecure, development only)
      # - certificate: Verify certificate is valid and signed by trusted CA
      # - full: Verify certificate and hostname match (production)
      - xpack.security.transport.ssl.verification_mode=certificate
      - xpack.security.http.ssl.verification_mode=certificate

      # Supported SSL/TLS versions
      - xpack.security.http.ssl.supported_protocols=TLSv1.2,TLSv1.3
      - xpack.security.transport.ssl.supported_protocols=TLSv1.2,TLSv1.3

      # Cipher suites (optional, defaults are secure)
      # - xpack.security.http.ssl.cipher_suites=TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384

    volumes:
      - ./certs/elasticsearch:/usr/share/elasticsearch/config/certificates:ro
      - ./certs/ca:/usr/share/elasticsearch/config/ca-certificates:ro

    ports:
      - "9443:9200"  # HTTPS (map 9200 to external 9443)

    healthcheck:
      test: ["CMD-SHELL", "curl -f -k -u elastic:${ELASTIC_PASSWORD} https://localhost:9200/_cluster/health || exit 1"]
```

**ElasticSearch Client Configuration:**

```bash
# Python Elasticsearch client
from elasticsearch import Elasticsearch

es = Elasticsearch(
    ['https://localhost:9443'],
    http_auth=('elastic', 'password'),
    verify_certs=True,
    ca_certs='/path/to/ca.crt'
)

# Curl
curl -u elastic:password \
  --cacert certs/ca/ca.crt \
  https://localhost:9443/_cluster/health
```

### Kibana

**Configuration Options:**

```yaml
services:
  kibana:
    environment:
      # ElasticSearch connection (HTTPS)
      - ELASTICSEARCH_HOSTS=https://elasticsearch:9200
      - ELASTICSEARCH_SSL_CERTIFICATEAUTHORITIES=/usr/share/kibana/config/certificates/ca.crt
      - ELASTICSEARCH_SSL_VERIFICATIONMODE=certificate

      # Kibana server SSL (HTTPS)
      - SERVER_SSL_ENABLED=true
      - SERVER_SSL_CERTIFICATE=/usr/share/kibana/config/certificates/kibana.crt
      - SERVER_SSL_KEY=/usr/share/kibana/config/certificates/kibana.key

      # Optional: Client certificate authentication
      # - ELASTICSEARCH_SSL_CERTIFICATE=/usr/share/kibana/config/certificates/kibana.crt
      # - ELASTICSEARCH_SSL_KEY=/usr/share/kibana/config/certificates/kibana.key

      # TLS version
      - SERVER_SSL_SUPPORTEDPROTOCOLS=["TLSv1.2", "TLSv1.3"]

      # Cipher suites (optional)
      # - SERVER_SSL_CIPHERSUITES=["TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256"]

    volumes:
      - ./certs/kibana:/usr/share/kibana/config/certificates:ro
      - ./certs/ca:/usr/share/kibana/config/ca-certificates:ro

    ports:
      - "5601:5601"  # HTTPS

    healthcheck:
      test: ["CMD-SHELL", "curl -f -k https://localhost:5601/api/status || exit 1"]
```

**Alternative: kibana.yml Configuration File**

Create `kibana/config/kibana.yml`:

```yaml
server.ssl.enabled: true
server.ssl.certificate: /usr/share/kibana/config/certificates/kibana.crt
server.ssl.key: /usr/share/kibana/config/certificates/kibana.key

elasticsearch.hosts: ["https://elasticsearch:9200"]
elasticsearch.ssl.certificateAuthorities: /usr/share/kibana/config/certificates/ca.crt
elasticsearch.ssl.verificationMode: certificate

# Optional: Mutual TLS
elasticsearch.ssl.certificate: /usr/share/kibana/config/certificates/kibana.crt
elasticsearch.ssl.key: /usr/share/kibana/config/certificates/kibana.key
```

Mount in docker-compose:
```yaml
volumes:
  - ./kibana/config/kibana.yml:/usr/share/kibana/config/kibana.yml:ro
```

### Logstash

**Configuration Options:**

Logstash SSL configuration is in `logstash/pipeline/logstash.conf`:

```ruby
# Input: Beats with SSL/TLS
input {
  beats {
    port => 5044
    ssl => true
    ssl_certificate => "/usr/share/logstash/config/certificates/logstash.crt"
    ssl_key => "/usr/share/logstash/config/certificates/logstash.key"
    ssl_certificate_authorities => ["/usr/share/logstash/config/certificates/ca.crt"]
    ssl_verify_mode => "force_peer"  # or "peer", "none"
  }
}

# Input: TCP with SSL/TLS
input {
  tcp {
    port => 5000
    ssl_enable => true
    ssl_cert => "/usr/share/logstash/config/certificates/logstash.crt"
    ssl_key => "/usr/share/logstash/config/certificates/logstash.key"
    ssl_extra_chain_certs => ["/usr/share/logstash/config/certificates/ca.crt"]
    ssl_verify => true
  }
}

# Output: ElasticSearch with SSL/TLS
output {
  elasticsearch {
    hosts => ["https://elasticsearch:9200"]
    user => "elastic"
    password => "${ELASTIC_PASSWORD}"

    ssl => true
    cacert => "/usr/share/logstash/config/certificates/ca.crt"
    ssl_certificate_verification => true

    # Optional: Client certificate authentication
    # keystore => "/usr/share/logstash/config/certificates/logstash.p12"
    # keystore_password => "${LOGSTASH_KEYSTORE_PASSWORD}"
  }
}
```

**Docker Compose Configuration:**

```yaml
services:
  logstash:
    environment:
      - ELASTICSEARCH_HOSTS=https://elasticsearch:9200
      - ELASTICSEARCH_SSL_CERTIFICATEAUTHORITY=/usr/share/logstash/config/certificates/ca.crt

    volumes:
      - ./logstash/config/logstash.yml:/usr/share/logstash/config/logstash.yml:ro
      - ./logstash/pipeline:/usr/share/logstash/pipeline:ro
      - ./certs/logstash:/usr/share/logstash/config/certificates:ro
      - ./certs/ca:/usr/share/logstash/config/ca-certificates:ro

    ports:
      - "5044:5044"  # Beats (SSL)
      - "5000:5000"  # TCP (SSL)
```

### APISIX Gateway

**APISIX SSL Configuration:**

APISIX SSL is configured in `apisix-config/config/config.yaml`:

```yaml
apisix:
  ssl:
    enable: true
    listen:
      - port: 9443
        enable_http2: true
    ssl_protocols: TLSv1.2 TLSv1.3
    ssl_ciphers: >
      ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:
      ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:
      ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305
    ssl_session_timeout: 1h

deployment:
  admin:
    https_admin: true
    admin_listen:
      port: 9180
    admin_api_mtls:
      admin_ssl_cert: /usr/local/apisix/conf/ssl/apisix.crt
      admin_ssl_cert_key: /usr/local/apisix/conf/ssl/apisix.key
```

**Upload SSL Certificate to APISIX:**

```bash
# Create SSL certificate in APISIX
curl -X PUT http://localhost:9180/apisix/admin/ssls/1 \
  -H "X-API-KEY: ${APISIX_ADMIN_KEY}" \
  -H 'Content-Type: application/json' \
  -d "{
    \"cert\": \"$(cat certs/apisix/apisix.crt | sed ':a;N;\$!ba;s/\\n/\\\\n/g')\",
    \"key\": \"$(cat certs/apisix/apisix.key | sed ':a;N;\$!ba;s/\\n/\\\\n/g')\",
    \"snis\": [\"localhost\", \"elk.example.com\"]
  }"
```

**Docker Compose Configuration:**

```yaml
services:
  apisix:
    volumes:
      - ./apisix-config/config/config.yaml:/usr/local/apisix/conf/config.yaml:ro
      - ./certs/apisix:/usr/local/apisix/conf/ssl:ro

    ports:
      - "9080:9080"   # HTTP
      - "9443:9443"   # HTTPS
      - "9180:9180"   # Admin API
```

### Prometheus

**Configuration:**

Create `prometheus/prometheus.yml` with TLS:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'elasticsearch'
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/certs/ca.crt
      cert_file: /etc/prometheus/certs/prometheus.crt
      key_file: /etc/prometheus/certs/prometheus.key
      insecure_skip_verify: false
    static_configs:
      - targets: ['elasticsearch:9200']
    basic_auth:
      username: 'elastic'
      password: 'your-password'
```

**Docker Compose:**

```yaml
services:
  prometheus:
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--web.config.file=/etc/prometheus/web-config.yml'

    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus/web-config.yml:/etc/prometheus/web-config.yml:ro
      - ./certs/prometheus:/etc/prometheus/certs:ro
      - ./certs/ca:/etc/prometheus/ca-certs:ro
```

Create `prometheus/web-config.yml`:

```yaml
tls_server_config:
  cert_file: /etc/prometheus/certs/prometheus.crt
  key_file: /etc/prometheus/certs/prometheus.key
  client_ca_file: /etc/prometheus/ca-certs/ca.crt
  client_auth_type: "RequireAndVerifyClientCert"
```

### Grafana

**Configuration:**

Create `grafana/grafana.ini`:

```ini
[server]
protocol = https
cert_file = /etc/grafana/certs/grafana.crt
cert_key = /etc/grafana/certs/grafana.key
```

**Docker Compose:**

```yaml
services:
  grafana:
    environment:
      - GF_SERVER_PROTOCOL=https
      - GF_SERVER_CERT_FILE=/etc/grafana/certs/grafana.crt
      - GF_SERVER_CERT_KEY=/etc/grafana/certs/grafana.key

    volumes:
      - ./grafana/grafana.ini:/etc/grafana/grafana.ini:ro
      - ./certs/grafana:/etc/grafana/certs:ro

    ports:
      - "3000:3000"  # HTTPS
```

### Alertmanager

**Configuration:**

Create `alertmanager/alertmanager.yml` with TLS for webhook receivers:

```yaml
global:
  # SMTP with TLS
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: 'alertmanager@example.com'
  smtp_auth_username: 'alertmanager@example.com'
  smtp_auth_password: 'password'
  smtp_require_tls: true

route:
  receiver: 'email'

receivers:
  - name: 'email'
    email_configs:
      - to: 'admin@example.com'
        tls_config:
          insecure_skip_verify: false

  - name: 'webhook'
    webhook_configs:
      - url: 'https://webhook.example.com/alert'
        tls_config:
          ca_file: /etc/alertmanager/certs/ca.crt
          cert_file: /etc/alertmanager/certs/alertmanager.crt
          key_file: /etc/alertmanager/certs/alertmanager.key
```

**Docker Compose:**

```yaml
services:
  alertmanager:
    volumes:
      - ./alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - ./certs/alertmanager:/etc/alertmanager/certs:ro
      - ./certs/ca:/etc/alertmanager/ca-certs:ro
```

---

## Inter-Service Communication

How services communicate securely within the Docker network.

### Communication Patterns

```
┌─────────────┐  HTTPS    ┌──────────────┐  HTTPS    ┌─────────────┐
│   Client    │ ────────> │    APISIX    │ ────────> │ ElasticSearch│
│  (Browser)  │           │   Gateway    │           │     :9200    │
└─────────────┘           └──────────────┘           └─────────────┘
                                │
                                │ HTTPS
                                ↓
                          ┌──────────────┐
                          │    Kibana    │
                          │     :5601    │
                          └──────────────┘
                                │
                                │ HTTPS
                                ↓
                          ┌──────────────┐
                          │ ElasticSearch│
                          │     :9200    │
                          └──────────────┘

┌─────────────┐  TLS      ┌──────────────┐  HTTPS    ┌─────────────┐
│ Mule App    │ ────────> │   Logstash   │ ────────> │ElasticSearch│
│  (Logger)   │           │    :5000     │           │    :9200    │
└─────────────┘           └──────────────┘           └─────────────┘
```

### Certificate Trust Chain

**Scenario 1: Self-Signed Certificates**

All services trust the same CA:

```
CA Certificate (ca.crt)
  │
  ├─> ElasticSearch Certificate (elasticsearch.crt)
  ├─> Kibana Certificate (kibana.crt)
  ├─> Logstash Certificate (logstash.crt)
  └─> APISIX Certificate (apisix.crt)
```

Each service needs:
1. Its own certificate and private key
2. The CA certificate to verify other services

**Scenario 2: Let's Encrypt / Commercial CA**

All services use the same certificate:

```
Let's Encrypt Root CA
  │
  └─> Intermediate CA
        │
        └─> Domain Certificate (elk.example.com)
              │
              ├─> Used by ElasticSearch
              ├─> Used by Kibana
              ├─> Used by Logstash
              └─> Used by APISIX
```

Each service needs:
1. The domain certificate (fullchain.pem)
2. The private key
3. The intermediate CA certificate (for verification)

### Mutual TLS (mTLS)

For enhanced security, enable mutual TLS where both client and server authenticate:

**ElasticSearch Configuration:**

```yaml
environment:
  # Require client certificates
  - xpack.security.http.ssl.client_authentication=required
  - xpack.security.http.ssl.certificate_authorities=/usr/share/elasticsearch/config/certificates/ca.crt
```

**Kibana Client Certificate:**

```yaml
environment:
  # Kibana presents client certificate when connecting to ElasticSearch
  - ELASTICSEARCH_SSL_CERTIFICATE=/usr/share/kibana/config/certificates/kibana.crt
  - ELASTICSEARCH_SSL_KEY=/usr/share/kibana/config/certificates/kibana.key
```

**Logstash Client Certificate:**

```ruby
output {
  elasticsearch {
    hosts => ["https://elasticsearch:9200"]
    ssl => true
    cacert => "/usr/share/logstash/config/certificates/ca.crt"

    # Client certificate for mTLS
    client_cert => "/usr/share/logstash/config/certificates/logstash.crt"
    client_key => "/usr/share/logstash/config/certificates/logstash.key"
  }
}
```

### Service-to-Service SSL Verification

**Verification Modes:**

| Mode | Description | Use Case |
|------|-------------|----------|
| `none` | No certificate verification | Development only, insecure |
| `certificate` | Verify certificate is signed by trusted CA | Self-signed certificates, internal services |
| `full` | Verify certificate and hostname matches | Production, public certificates |

**Example: Kibana → ElasticSearch**

```yaml
kibana:
  environment:
    # Strict verification (production)
    - ELASTICSEARCH_SSL_VERIFICATIONMODE=full
    - ELASTICSEARCH_HOSTS=https://elasticsearch:9200

    # OR relaxed verification (self-signed)
    # - ELASTICSEARCH_SSL_VERIFICATIONMODE=certificate

    # OR no verification (development only, insecure)
    # - ELASTICSEARCH_SSL_VERIFICATIONMODE=none
```

### Troubleshooting Inter-Service SSL

**Test ElasticSearch from Kibana container:**

```bash
docker exec kibana curl -v \
  --cacert /usr/share/kibana/config/certificates/ca.crt \
  -u elastic:password \
  https://elasticsearch:9200/_cluster/health
```

**Test ElasticSearch from Logstash container:**

```bash
docker exec logstash curl -v \
  --cacert /usr/share/logstash/config/certificates/ca.crt \
  -u elastic:password \
  https://elasticsearch:9200/_cluster/health
```

**Common Issues:**

1. **Certificate Verification Failed**
   ```
   SSLError: certificate verify failed: self signed certificate in certificate chain
   ```
   **Solution:** Ensure CA certificate is present and correctly configured

2. **Hostname Mismatch**
   ```
   SSLError: hostname 'elasticsearch' doesn't match certificate
   ```
   **Solution:** Use `verification_mode: certificate` instead of `full`, or add hostname to SAN

3. **Certificate Expired**
   ```
   SSLError: certificate has expired
   ```
   **Solution:** Regenerate certificates or renew via Let's Encrypt

---

## Docker Compose SSL Profiles

Use Docker Compose profiles to easily enable/disable SSL.

### Profile Configuration

Add profiles to `docker-compose.yml`:

```yaml
services:
  elasticsearch:
    profiles: ["ssl", "production"]
    # SSL-enabled configuration
    environment:
      - xpack.security.http.ssl.enabled=true
    volumes:
      - ./certs/elasticsearch:/usr/share/elasticsearch/config/certificates:ro
    ports:
      - "9443:9200"

  elasticsearch-http:
    profiles: ["development"]
    # HTTP-only configuration (development)
    image: docker.elastic.co/elasticsearch/elasticsearch:${ELASTIC_VERSION}
    environment:
      - xpack.security.http.ssl.enabled=false
    ports:
      - "9200:9200"
```

### Starting with Different Profiles

**Development (HTTP only):**

```bash
docker-compose --profile development up -d
```

**Production (HTTPS):**

```bash
docker-compose --profile ssl up -d

# OR
docker-compose --profile production up -d
```

**Multiple Profiles:**

```bash
docker-compose --profile ssl --profile monitoring up -d
```

### Environment-Based Configuration

Use `.env` file to control SSL:

```bash
# .env
COMPOSE_PROFILES=ssl,monitoring
SSL_ENABLED=true
```

Then simply:

```bash
docker-compose up -d
```

### Profile Examples

**Complete SSL Profile Example:**

```yaml
version: '3.8'

services:
  # ElasticSearch with SSL
  elasticsearch:
    profiles: ["ssl"]
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.3
    environment:
      - xpack.security.http.ssl.enabled=true
      - xpack.security.http.ssl.key=/usr/share/elasticsearch/config/certificates/elasticsearch.key
      - xpack.security.http.ssl.certificate=/usr/share/elasticsearch/config/certificates/elasticsearch.crt
    volumes:
      - ./certs/elasticsearch:/usr/share/elasticsearch/config/certificates:ro
    ports:
      - "9443:9200"

  # ElasticSearch without SSL (development)
  elasticsearch-dev:
    profiles: ["dev"]
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.3
    environment:
      - xpack.security.http.ssl.enabled=false
    ports:
      - "9200:9200"

  # Kibana with SSL
  kibana:
    profiles: ["ssl"]
    image: docker.elastic.co/kibana/kibana:8.11.3
    environment:
      - ELASTICSEARCH_HOSTS=https://elasticsearch:9200
      - SERVER_SSL_ENABLED=true
      - SERVER_SSL_CERTIFICATE=/usr/share/kibana/config/certificates/kibana.crt
      - SERVER_SSL_KEY=/usr/share/kibana/config/certificates/kibana.key
    volumes:
      - ./certs/kibana:/usr/share/kibana/config/certificates:ro
    ports:
      - "5601:5601"

  # Kibana without SSL (development)
  kibana-dev:
    profiles: ["dev"]
    image: docker.elastic.co/kibana/kibana:8.11.3
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch-dev:9200
      - SERVER_SSL_ENABLED=false
    ports:
      - "5601:5601"
```

**Usage:**

```bash
# Development
docker-compose --profile dev up -d

# Production
docker-compose --profile ssl up -d
```

---

## Certificate Management

Ongoing management of SSL/TLS certificates.

### Viewing Certificate Details

**Display Certificate Information:**

```bash
# View certificate details
openssl x509 -in certs/elasticsearch/elasticsearch.crt -text -noout

# View specific fields
openssl x509 -in certs/elasticsearch/elasticsearch.crt -noout \
  -subject -issuer -dates -ext subjectAltName

# View certificate in PEM format
openssl x509 -in certs/elasticsearch/elasticsearch.crt -text
```

**Example Output:**

```
Subject: CN=elasticsearch
Issuer: CN=ELK-Stack-CA
Not Before: Dec 29 10:00:00 2025 GMT
Not After : Dec 27 10:00:00 2035 GMT
X509v3 Subject Alternative Name:
    DNS:elasticsearch, DNS:localhost, DNS:elk.example.com, IP:127.0.0.1, IP:172.42.0.10
```

### Checking Certificate Expiration

**Check Single Certificate:**

```bash
# Show expiration dates
openssl x509 -in certs/elasticsearch/elasticsearch.crt -noout -dates

# Days until expiration
echo | openssl x509 -in certs/elasticsearch/elasticsearch.crt -noout -enddate | \
  awk -F= '{print $2}' | xargs -I {} date -d {} +%s | \
  awk -v now="$(date +%s)" '{print int(($1 - now) / 86400)" days"}'
```

**Check All Certificates:**

```bash
#!/bin/bash
# check-all-certs.sh

for cert in certs/*/*.crt; do
  echo "Certificate: $cert"
  openssl x509 -in "$cert" -noout -subject -enddate
  echo ""
done
```

**Automated Monitoring Script:**

```bash
cat > scripts/check-cert-expiry.sh <<'EOF'
#!/bin/bash
# Check certificate expiration and alert if < 30 days

WARN_DAYS=30
ALERT_EMAIL="admin@example.com"

for cert in certs/*/*.crt; do
  EXPIRY=$(openssl x509 -in "$cert" -noout -enddate | cut -d= -f2)
  EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s)
  NOW_EPOCH=$(date +%s)
  DAYS_LEFT=$(( ($EXPIRY_EPOCH - $NOW_EPOCH) / 86400 ))

  if [ $DAYS_LEFT -lt $WARN_DAYS ]; then
    echo "WARNING: $cert expires in $DAYS_LEFT days ($EXPIRY)"

    # Send email alert
    echo "Certificate $cert expires in $DAYS_LEFT days" | \
      mail -s "SSL Certificate Expiration Warning" "$ALERT_EMAIL"
  fi
done
EOF

chmod +x scripts/check-cert-expiry.sh
```

**Add to Crontab:**

```bash
crontab -e

# Check certificates daily at 9 AM
0 9 * * * /path/to/config/scripts/setup/check-cert-expiry.sh >> /var/log/cert-expiry-check.log 2>&1
```

### Renewal Procedures

**Self-Signed Certificates:**

```bash
# Regenerate all certificates
./config/scripts/setup/generate-certs.sh --force

# Restart services to load new certificates
docker-compose restart

# OR reload without downtime (APISIX example)
docker-compose exec apisix apisix reload
```

**Let's Encrypt Certificates:**

```bash
# Automatic renewal (via cron)
0 3 * * * /path/t./config/scripts/setup/renew-letsencrypt.sh >> /var/log/letsencrypt-renewal.log 2>&1

# Manual renewal
./config/scripts/setup/renew-letsencrypt.sh

# Force renewal (even if not expiring soon)
./config/scripts/setup/renew-letsencrypt.sh --force

# Dry run (test renewal without actually renewing)
certbot renew --dry-run
```

**Commercial CA Certificates:**

```bash
# 1. Generate new CSR (reuse existing private key)
openssl req -new -key certs/commercial/server.key \
  -out certs/commercial/server-renewal.csr \
  -config certs/commercial/server.cnf

# 2. Submit CSR to CA for renewal

# 3. Download new certificate

# 4. Install new certificate
cp new-server.crt certs/commercial/server.crt
cat certs/commercial/server.crt \
    certs/commercial/intermediate.crt \
    > certs/commercial/fullchain.crt

# 5. Deploy to services
./scripts/deploy-certs.sh

# 6. Restart services
docker-compose restart
```

### Rotating Certificates

**Best Practices:**

1. **Generate new certificates before old ones expire** (60 days for Let's Encrypt, 30 days for others)
2. **Test new certificates in staging environment** before production
3. **Keep backups of old certificates** until new ones are verified
4. **Update all services simultaneously** to avoid mixed configurations
5. **Monitor certificate expiration** continuously

**Certificate Rotation Script:**

```bash
cat > scripts/rotate-certs.sh <<'EOF'
#!/bin/bash
set -e

BACKUP_DIR="certs/backup-$(date +%Y%m%d-%H%M%S)"

echo "Backing up existing certificates to $BACKUP_DIR"
cp -r certs "$BACKUP_DIR"

echo "Generating new certificates"
./config/scripts/setup/generate-certs.sh --force

echo "Deploying certificates to services"
for service in elasticsearch kibana logstash apisix; do
  docker-compose exec $service \
    sh -c "ls /usr/share/$service/config/certificates/" || true
done

echo "Restarting services with new certificates"
docker-compose restart

echo "Verifying HTTPS connectivity"
curl -k -u elastic:${ELASTIC_PASSWORD} \
  https://localhost:9443/_cluster/health

echo "Certificate rotation complete!"
echo "Backup stored in: $BACKUP_DIR"
EOF

chmod +x scripts/rotate-certs.sh
```

### Certificate Backup and Recovery

**Backup Certificates:**

```bash
#!/bin/bash
# backup-certs.sh

BACKUP_DIR="backups/certs-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

# Copy certificates
cp -r certs "$BACKUP_DIR/"

# Create encrypted archive
tar -czf "$BACKUP_DIR.tar.gz" "$BACKUP_DIR"
openssl enc -aes-256-cbc -salt \
  -in "$BACKUP_DIR.tar.gz" \
  -out "$BACKUP_DIR.tar.gz.enc" \
  -k "your-encryption-password"

rm -rf "$BACKUP_DIR" "$BACKUP_DIR.tar.gz"

echo "Certificates backed up to: $BACKUP_DIR.tar.gz.enc"
```

**Restore Certificates:**

```bash
#!/bin/bash
# restore-certs.sh

BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ]; then
  echo "Usage: $0 <backup-file.tar.gz.enc>"
  exit 1
fi

# Decrypt archive
openssl enc -aes-256-cbc -d \
  -in "$BACKUP_FILE" \
  -out "${BACKUP_FILE%.enc}" \
  -k "your-encryption-password"

# Extract archive
tar -xzf "${BACKUP_FILE%.enc}"

# Restore certificates
RESTORE_DIR=$(basename "$BACKUP_FILE" .tar.gz.enc)
cp -r "$RESTORE_DIR/certs" .

# Restart services
docker-compose restart

echo "Certificates restored from: $BACKUP_FILE"
```

---

## Troubleshooting

Common SSL/TLS issues and solutions.

### Certificate Verification Errors

**Error: "certificate verify failed: self signed certificate"**

**Symptom:**
```
SSLError: certificate verify failed: self signed certificate
curl: (60) SSL certificate problem: self signed certificate
```

**Causes:**
- Using self-signed certificate without trusting CA
- CA certificate not configured in client

**Solutions:**

1. **Trust the CA certificate system-wide** (see [Development Setup Step 7](#step-7-trust-the-ca-certificate-optional))

2. **Provide CA certificate to client:**
   ```bash
   # Curl
   curl --cacert certs/ca/ca.crt https://localhost:9443

   # Python
   import requests
   response = requests.get('https://localhost:9443',
                          verify='certs/ca/ca.crt')
   ```

3. **Disable verification (development only, insecure):**
   ```bash
   # Curl
   curl -k https://localhost:9443

   # Python
   requests.get('https://localhost:9443', verify=False)
   ```

**Error: "certificate verify failed: self signed certificate in certificate chain"**

**Symptom:**
```
SSLError: certificate verify failed: self signed certificate in certificate chain
```

**Cause:**
- Intermediate certificates not included in chain

**Solution:**
```bash
# Ensure full chain is in certificate file
cat server.crt intermediate.crt root.crt > fullchain.crt

# Use fullchain.crt in service configuration
```

### Hostname Verification Errors

**Error: "hostname 'elasticsearch' doesn't match certificate"**

**Symptom:**
```
SSLError: hostname 'elasticsearch' doesn't match certificate
curl: (60) SSL: certificate subject name 'localhost' does not match target host name 'elasticsearch'
```

**Cause:**
- Certificate's Common Name (CN) or Subject Alternative Names (SAN) don't include the hostname

**Solutions:**

1. **Add hostname to certificate's SAN:**
   ```bash
   # Regenerate certificate with correct hostnames
   ./config/scripts/setup/generate-certs.sh --domain elasticsearch
   ```

2. **Use verification mode that ignores hostname:**
   ```yaml
   # In docker-compose.yml
   environment:
     - xpack.security.http.ssl.verification_mode=certificate  # Not 'full'
   ```

3. **Use IP address or hostname that matches certificate:**
   ```bash
   # If certificate is for 'localhost', use localhost:
   curl https://localhost:9443

   # If certificate is for 'elk.example.com', use that:
   curl https://elk.example.com:9443
   ```

### Connection Refused Errors

**Error: "Connection refused"**

**Symptom:**
```
curl: (7) Failed to connect to localhost port 9443: Connection refused
```

**Causes:**
1. Service not running
2. Wrong port number
3. Firewall blocking connection
4. Service listening on wrong interface

**Solutions:**

1. **Check service is running:**
   ```bash
   docker-compose ps
   docker-compose logs elasticsearch
   ```

2. **Verify port is listening:**
   ```bash
   netstat -tuln | grep 9443
   # OR
   docker exec elasticsearch netstat -tuln | grep 9200
   ```

3. **Check docker port mappings:**
   ```bash
   docker ps | grep elasticsearch
   # Look for 0.0.0.0:9443->9200/tcp
   ```

4. **Test from inside container:**
   ```bash
   docker exec elasticsearch curl -k https://localhost:9200
   ```

### Cipher Suite Mismatches

**Error: "no shared cipher" or "handshake failure"**

**Symptom:**
```
SSLError: [SSL: NO_SHARED_CIPHER] no shared cipher
curl: (35) error:14094410:SSL routines:ssl3_read_bytes:sslv3 alert handshake failure
```

**Cause:**
- Client and server don't support any common cipher suites
- Outdated SSL/TLS version

**Solutions:**

1. **Use modern TLS versions:**
   ```yaml
   environment:
     - xpack.security.http.ssl.supported_protocols=TLSv1.2,TLSv1.3
   ```

2. **Configure compatible cipher suites:**
   ```yaml
   environment:
     - xpack.security.http.ssl.cipher_suites=TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
   ```

3. **Check client TLS version:**
   ```bash
   # Test with specific TLS version
   curl --tlsv1.2 https://localhost:9443
   curl --tlsv1.3 https://localhost:9443
   ```

### Browser Security Warnings

**Warning: "Your connection is not private" or "NET::ERR_CERT_AUTHORITY_INVALID"**

**Symptom:**
- Browser shows warning page with "Your connection is not private"
- Red padlock or "Not Secure" in address bar

**Cause:**
- Using self-signed certificate
- Browser doesn't trust the CA

**Solutions:**

1. **Trust the CA certificate in browser** (see [Development Setup Step 7](#step-7-trust-the-ca-certificate-optional))

2. **Accept the certificate temporarily** (development only):
   - Click "Advanced"
   - Click "Proceed to localhost (unsafe)"

3. **Use production certificate** (Let's Encrypt or commercial CA)

### Certificate Expired Errors

**Error: "certificate has expired"**

**Symptom:**
```
SSLError: certificate has expired
curl: (60) SSL certificate problem: certificate has expired
```

**Cause:**
- Certificate validity period has passed

**Solutions:**

1. **Check expiration date:**
   ```bash
   openssl x509 -in certs/elasticsearch/elasticsearch.crt -noout -dates
   ```

2. **Regenerate certificates:**
   ```bash
   # Self-signed
   ./config/scripts/setup/generate-certs.sh --force

   # Let's Encrypt
   ./config/scripts/setup/renew-letsencrypt.sh --force

   # Commercial CA - request renewal from CA
   ```

3. **Restart services:**
   ```bash
   docker-compose restart
   ```

### Permission Denied Errors

**Error: "Permission denied" reading certificate files**

**Symptom:**
```
ERROR: unable to load certificate: permission denied
```

**Cause:**
- Certificate files have wrong permissions
- Docker volume mount permissions

**Solutions:**

1. **Fix file permissions:**
   ```bash
   # Private keys: owner only
   chmod 600 certs/*/*.key

   # Certificates: readable by all
   chmod 644 certs/*/*.crt

   # Directories: executable
   chmod 755 certs certs/*
   ```

2. **Fix ownership:**
   ```bash
   # ElasticSearch runs as UID 1000
   chown -R 1000:1000 certs/elasticsearch

   # OR make readable by all
   chmod -R a+r certs/*/*.crt
   ```

3. **Check SELinux context (CentOS/RHEL):**
   ```bash
   chcon -Rt svirt_sandbox_file_t certs/
   ```

### Mixed Content Warnings

**Warning: "Mixed content" in browser console**

**Symptom:**
```
Mixed Content: The page at 'https://elk.example.com' was loaded over HTTPS,
but requested an insecure resource 'http://elasticsearch:9200'.
This request has been blocked.
```

**Cause:**
- HTTPS page trying to load resources over HTTP
- Service configured with HTTP URL when HTTPS is available

**Solutions:**

1. **Update URLs to HTTPS:**
   ```yaml
   # Change
   - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
   # To
   - ELASTICSEARCH_HOSTS=https://elasticsearch:9200
   ```

2. **Configure reverse proxy to handle protocol:**
   ```nginx
   # APISIX or nginx handles HTTPS termination
   location /elasticsearch {
     proxy_pass http://elasticsearch:9200;
   }
   ```

---

## Security Best Practices

### File Permissions

**Proper Permissions:**

```bash
# Private keys: Only owner can read/write
chmod 600 certs/*/*.key
chmod 600 certs/ca/ca.key  # Especially important!

# Certificates: World-readable
chmod 644 certs/*/*.crt

# Directories: Executable for access
chmod 755 certs certs/*

# CSR files: Can be world-readable
chmod 644 certs/*/*.csr
```

**Ownership:**

```bash
# Run services as non-root user
chown -R elasticsearch:elasticsearch certs/elasticsearch
chown -R kibana:kibana certs/kibana

# OR use UID/GID
chown -R 1000:1000 certs/elasticsearch  # ElasticSearch UID
```

**Verify Permissions:**

```bash
# Check for world-writable files (should be none)
find certs -type f -perm -002

# Check for private keys with wrong permissions
find certs -name "*.key" ! -perm 600
```

### Key Management

**Best Practices:**

1. **Never commit private keys to version control:**
   ```bash
   # .gitignore
   certs/
   *.key
   *.p12
   *.pfx
   ```

2. **Use strong key sizes:**
   - RSA: 2048-bit minimum, 4096-bit recommended
   - ECDSA: 256-bit (equivalent to 3072-bit RSA)

3. **Protect CA private key:**
   ```bash
   # CA key should be offline, encrypted, and backed up securely
   openssl rsa -aes256 -in certs/ca/ca.key -out certs/ca/ca.key.enc
   chmod 400 certs/ca/ca.key.enc
   ```

4. **Use different keys for different services:**
   - Don't reuse private keys
   - Each service should have its own certificate/key pair

5. **Rotate keys periodically:**
   - Minimum every 2 years
   - Immediately after any suspected compromise

### Protocol Selection

**Recommended TLS Versions:**

```yaml
# Disable SSLv2, SSLv3, TLSv1.0, TLSv1.1 (all deprecated)
# Enable only TLSv1.2 and TLSv1.3

environment:
  - xpack.security.http.ssl.supported_protocols=TLSv1.2,TLSv1.3
```

**Why:**
- **TLSv1.3**: Most secure, faster handshake, forward secrecy
- **TLSv1.2**: Widely supported, secure when properly configured
- **TLSv1.0/1.1**: Deprecated, vulnerable to attacks (BEAST, POODLE)
- **SSLv2/v3**: Severely compromised, never use

### Cipher Suites

**Recommended Cipher Suites (in order of preference):**

```yaml
environment:
  - xpack.security.http.ssl.cipher_suites=TLS_AES_256_GCM_SHA384,TLS_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384,TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
```

**Cipher Suite Selection Criteria:**

1. **Forward Secrecy**: Use ECDHE or DHE key exchange
2. **Authenticated Encryption**: Use GCM or ChaCha20-Poly1305
3. **Strong Algorithms**: AES-256 or AES-128 (not 3DES or RC4)

**Testing Cipher Suites:**

```bash
# Test supported ciphers
nmap --script ssl-enum-ciphers -p 9443 localhost

# OR use testssl.sh
./testssl.sh https://localhost:9443

# OR use SSL Labs (for public sites)
# https://www.ssllabs.com/ssltest/
```

**Disable Weak Ciphers:**

Avoid these cipher suites:
- `TLS_RSA_*` (no forward secrecy)
- `*_CBC_*` (vulnerable to BEAST, Lucky13)
- `*_RC4_*` (RC4 is broken)
- `*_3DES_*` (3DES is weak)
- `*_MD5` (MD5 is broken)
- `*_NULL_*` (no encryption!)

### HTTP Strict Transport Security (HSTS)

**Enable HSTS in APISIX:**

```yaml
# apisix-config/config/config.yaml
apisix:
  ssl:
    enable: true

nginx_config:
  http_server_configuration_snippet: |
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
```

**Benefits:**
- Forces browsers to always use HTTPS
- Prevents downgrade attacks
- Protects against SSL stripping

### Certificate Pinning

**For High-Security Environments:**

```python
# Python client with certificate pinning
import hashlib
import ssl
import requests

# Expected certificate fingerprint (SHA-256)
EXPECTED_FINGERPRINT = "abcd1234..."

def verify_cert(cert_pem):
    cert_der = ssl.PEM_cert_to_DER_cert(cert_pem)
    fingerprint = hashlib.sha256(cert_der).hexdigest()
    return fingerprint == EXPECTED_FINGERPRINT

# Use in requests
response = requests.get('https://localhost:9443',
                       verify='certs/ca/ca.crt',
                       hooks={'response': lambda r, *args, **kwargs:
                              verify_cert(r.raw.connection.sock.getpeercert(True))})
```

**Get Certificate Fingerprint:**

```bash
# SHA-256 fingerprint
openssl x509 -in certs/elasticsearch/elasticsearch.crt -noout -fingerprint -sha256

# SHA-1 fingerprint
openssl x509 -in certs/elasticsearch/elasticsearch.crt -noout -fingerprint -sha1
```

### Monitoring and Auditing

**Log SSL/TLS Events:**

```yaml
# ElasticSearch audit logging
xpack.security.audit.enabled: true
xpack.security.audit.logfile.events.include:
  - authentication_success
  - authentication_failed
  - access_denied
  - connection_granted
  - connection_denied
```

**Monitor Certificate Expiration:**

```bash
# Add monitoring script to cron
0 9 * * * /path/to/config/scripts/setup/check-cert-expiry.sh

# Alert via Prometheus
# prometheus/rules/ssl-alerts.yml
groups:
  - name: ssl
    rules:
      - alert: SSLCertificateExpiringSoon
        expr: (ssl_certificate_expiry_seconds - time()) / 86400 < 30
        for: 1h
        annotations:
          summary: "SSL certificate expiring soon"
          description: "SSL certificate expires in {{ $value }} days"
```

**Audit Access Logs:**

```bash
# Check who accessed services
docker exec elasticsearch cat /usr/share/elasticsearch/logs/elasticsearch.log | \
  grep "SSL"

# APISIX access logs
docker exec apisix tail -f /usr/local/apisix/logs/access.log
```

---

## Migration from HTTP to HTTPS

Step-by-step plan for migrating an existing HTTP deployment to HTTPS with zero downtime.

### Pre-Migration Preparation

Before migrating to HTTPS, complete these steps:

1. Backup all data and configurations
2. Generate/obtain SSL certificates
3. Test SSL configuration in staging environment
4. Document current HTTP URLs and ports
5. Plan maintenance window (optional, for zero-downtime migration)
6. Notify users of upcoming changes
7. Prepare rollback plan

### Step-by-Step Migration

#### Phase 1: Preparation (No Downtime)

**1. Generate Certificates:**

```bash
# For production with domain
./config/scripts/setup/setup-letsencrypt.sh \
  --domain elk.example.com \
  --email admin@example.com

# OR for internal/development
./config/scripts/setup/generate-certs.sh
```

**2. Backup Current Configuration:**

```bash
cp docker-compose.yml docker-compose.yml.backup
cp .env .env.backup
tar -czf backup-$(date +%Y%m%d).tar.gz \
  docker-compose.yml .env certs/ elasticsearch-data/
```

**3. Test SSL Configuration:**

```bash
# Create test docker-compose-ssl.yml
cp docker-compose.yml docker-compose-ssl.yml

# Add SSL configuration to test file
# (Don't modify production yet)
```

#### Phase 2: Parallel HTTP and HTTPS (Zero Downtime)

**1. Configure Services to Listen on Both HTTP and HTTPS:**

```yaml
services:
  elasticsearch:
    environment:
      # Keep HTTP enabled
      - xpack.security.http.ssl.enabled=false
    ports:
      - "9200:9200"    # HTTP (existing)
      - "9443:9200"    # HTTPS (new)
    volumes:
      - ./certs/elasticsearch:/usr/share/elasticsearch/config/certificates:ro
```

**2. Start APISIX with Both HTTP and HTTPS Routes:**

```bash
# APISIX listens on both 9080 (HTTP) and 9443 (HTTPS)
# Routes configured for both protocols
```

**3. Update Clients Gradually:**

```bash
# Old clients continue using HTTP
curl http://localhost:9200/_cluster/health

# New clients use HTTPS
curl https://localhost:9443/_cluster/health
```

**4. Monitor Both Endpoints:**

```bash
# Check HTTP traffic
docker exec apisix tail -f /usr/local/apisix/logs/access.log | grep ":9080"

# Check HTTPS traffic
docker exec apisix tail -f /usr/local/apisix/logs/access.log | grep ":9443"
```

#### Phase 3: Gradual HTTPS Adoption (Zero Downtime)

**1. Update Internal Services First:**

```yaml
# Kibana → ElasticSearch
kibana:
  environment:
    - ELASTICSEARCH_HOSTS=https://elasticsearch:9200  # Changed from http
    - ELASTICSEARCH_SSL_CERTIFICATEAUTHORITIES=/usr/share/kibana/config/certificates/ca.crt
```

**2. Update Logstash:**

```ruby
# logstash/pipeline/logstash.conf
output {
  elasticsearch {
    hosts => ["https://elasticsearch:9200"]  # Changed from http
    ssl => true
    cacert => "/usr/share/logstash/config/certificates/ca.crt"
  }
}
```

**3. Update External Clients:**

```bash
# Update documentation
# Update API endpoint URLs
# Update application configurations
```

**4. Monitor Migration Progress:**

```bash
# Check HTTPS adoption rate
HTTPS_REQUESTS=$(docker exec apisix grep -c ":9443" /usr/local/apisix/logs/access.log)
HTTP_REQUESTS=$(docker exec apisix grep -c ":9080" /usr/local/apisix/logs/access.log)

echo "HTTPS: $HTTPS_REQUESTS, HTTP: $HTTP_REQUESTS"
```

#### Phase 4: Enforce HTTPS (Minimal Downtime)

**1. Enable HTTP to HTTPS Redirect:**

```yaml
# APISIX configuration
routes:
  - uri: /*
    upstream_id: 1
    plugins:
      redirect:
        http_to_https: true
        response_code: 301
```

**2. Wait for HTTP Traffic to Drop:**

```bash
# Monitor HTTP requests (should decrease to zero)
watch -n 60 'docker exec apisix tail -100 /usr/local/apisix/logs/access.log | grep -c ":9080"'
```

**3. Disable HTTP Completely:**

```yaml
services:
  elasticsearch:
    environment:
      # Enable HTTPS only
      - xpack.security.http.ssl.enabled=true
      - xpack.security.http.ssl.key=/usr/share/elasticsearch/config/certificates/elasticsearch.key
      - xpack.security.http.ssl.certificate=/usr/share/elasticsearch/config/certificates/elasticsearch.crt

    ports:
      - "9443:9200"    # HTTPS only
      # Remove: - "9200:9200"
```

**4. Restart Services:**

```bash
docker-compose up -d
```

**5. Verify HTTPS-Only Access:**

```bash
# Should fail (connection refused)
curl http://localhost:9200

# Should succeed
curl -k https://localhost:9443
```

#### Phase 5: Post-Migration Verification

**1. Test All Services:**

```bash
# ElasticSearch
curl -u elastic:${ELASTIC_PASSWORD} \
  https://localhost:9443/_cluster/health

# Kibana
curl https://localhost:5601/api/status

# Via APISIX
curl https://localhost:9443/elasticsearch/_cluster/health
curl https://localhost:9443/kibana/api/status
```

**2. Test Log Ingestion:**

```bash
# Send test log
echo '{"message":"SSL migration test"}' | \
  openssl s_client -connect localhost:5000 -quiet

# Verify in Kibana
curl -u elastic:${ELASTIC_PASSWORD} \
  "https://localhost:9443/mule-logs-*/_search?q=SSL%20migration"
```

**3. Monitor Error Logs:**

```bash
# Check for SSL errors
docker-compose logs | grep -i "ssl\|tls\|certificate"
```

**4. Update Documentation:**

```bash
# Update all references:
# - README.md
# - API documentation
# - Client configuration examples
# - Firewall rules (remove HTTP ports)
```

### Rollback Procedure

If migration fails, rollback to HTTP:

**1. Restore Backup:**

```bash
docker-compose down
cp docker-compose.yml.backup docker-compose.yml
cp .env.backup .env
```

**2. Remove SSL Configuration:**

```yaml
services:
  elasticsearch:
    environment:
      - xpack.security.http.ssl.enabled=false
    ports:
      - "9200:9200"    # HTTP only
```

**3. Restart Services:**

```bash
docker-compose up -d
```

**4. Verify HTTP Access:**

```bash
curl http://localhost:9200/_cluster/health
```

### Migration Phase Summary

**Phase 1: Preparation**
- Certificates generated/obtained
- Backups created
- Test environment validated

**Phase 2: Parallel HTTP/HTTPS**
- Both protocols working
- No errors in logs
- Monitoring shows traffic on both

**Phase 3: Gradual HTTPS Adoption**
- Internal services migrated
- External clients migrated
- HTTPS traffic > 90%

**Phase 4: Enforce HTTPS**
- HTTP redirects working
- HTTP traffic at zero
- HTTP disabled

**Phase 5: Post-Migration**
- All services tested
- Logs verified
- Documentation updated
- Backups archived

---

## Testing and Verification

Comprehensive testing procedures for SSL/TLS deployment.

### Testing Individual Services

**ElasticSearch HTTPS:**

```bash
# Basic connectivity test
curl -k https://localhost:9443

# Cluster health
curl -k -u elastic:${ELASTIC_PASSWORD} \
  https://localhost:9443/_cluster/health?pretty

# With certificate verification
curl --cacert certs/ca/ca.crt \
  -u elastic:${ELASTIC_PASSWORD} \
  https://localhost:9443/_cluster/health?pretty

# Check SSL/TLS version
openssl s_client -connect localhost:9443 -tls1_2
openssl s_client -connect localhost:9443 -tls1_3

# Verbose SSL debugging
curl -v --cacert certs/ca/ca.crt \
  https://localhost:9443 2>&1 | grep -i ssl
```

**Kibana HTTPS:**

```bash
# Status check
curl -k https://localhost:5601/api/status

# With authentication
curl -k -u elastic:${ELASTIC_PASSWORD} \
  https://localhost:5601/api/status

# Check certificate
echo | openssl s_client -connect localhost:5601 -servername localhost 2>/dev/null | \
  openssl x509 -noout -subject -issuer -dates
```

**Logstash TLS:**

```bash
# Test TCP TLS input
echo '{"message":"test"}' | \
  openssl s_client -connect localhost:5000 -quiet

# Test Beats TLS input
filebeat test output -E \
  'output.logstash.hosts=["localhost:5044"]' \
  -E 'output.logstash.ssl.certificate_authorities=["certs/ca/ca.crt"]'

# Check Logstash API
curl -k https://localhost:9600/_node/stats
```

**APISIX HTTPS:**

```bash
# Test HTTPS gateway
curl -k https://localhost:9443/

# Test proxied services
curl -k https://localhost:9443/elasticsearch/_cluster/health
curl -k https://localhost:9443/kibana/api/status

# Test admin API
curl -k https://localhost:9180/apisix/admin/routes \
  -H "X-API-KEY: ${APISIX_ADMIN_KEY}"

# Check SSL certificate
openssl s_client -connect localhost:9443 -servername localhost
```

### End-to-End Testing

**Full Stack Test:**

```bash
#!/bin/bash
# test-ssl-stack.sh

set -e

echo "Testing ElasticSearch..."
curl -f -k -u elastic:${ELASTIC_PASSWORD} \
  https://localhost:9443/_cluster/health || exit 1
echo "✓ ElasticSearch OK"

echo "Testing Kibana..."
curl -f -k https://localhost:5601/api/status || exit 1
echo "✓ Kibana OK"

echo "Testing Logstash..."
curl -f -k https://localhost:9600 || exit 1
echo "✓ Logstash OK"

echo "Testing APISIX..."
curl -f -k https://localhost:9443/ || exit 1
echo "✓ APISIX OK"

echo "Testing log ingestion..."
echo '{"message":"SSL test","level":"INFO"}' | \
  openssl s_client -connect localhost:5000 -quiet
sleep 5
curl -f -k -u elastic:${ELASTIC_PASSWORD} \
  "https://localhost:9443/logstash-*/_search?q=SSL%20test" || exit 1
echo "✓ Log ingestion OK"

echo ""
echo "All tests passed!"
```

**Automated Testing Script:**

```bash
cat > scripts/test-ssl.sh <<'EOF'
#!/bin/bash
# Comprehensive SSL/TLS testing

FAILED_TESTS=0

test_service() {
  local NAME=$1
  local URL=$2

  echo -n "Testing $NAME... "

  if curl -f -k -s -o /dev/null "$URL"; then
    echo "✓ PASS"
  else
    echo "✗ FAIL"
    FAILED_TESTS=$((FAILED_TESTS + 1))
  fi
}

test_certificate() {
  local NAME=$1
  local CERT_FILE=$2

  echo -n "Checking $NAME certificate... "

  # Check file exists
  if [ ! -f "$CERT_FILE" ]; then
    echo "✗ FAIL (file not found)"
    FAILED_TESTS=$((FAILED_TESTS + 1))
    return
  fi

  # Check not expired
  if openssl x509 -in "$CERT_FILE" -noout -checkend 0 >/dev/null 2>&1; then
    echo "✓ PASS"
  else
    echo "✗ FAIL (expired)"
    FAILED_TESTS=$((FAILED_TESTS + 1))
  fi
}

echo "=== SSL/TLS Test Suite ==="
echo ""

echo "Certificate Tests:"
test_certificate "CA" "certs/ca/ca.crt"
test_certificate "ElasticSearch" "certs/elasticsearch/elasticsearch.crt"
test_certificate "Kibana" "certs/kibana/kibana.crt"
test_certificate "Logstash" "certs/logstash/logstash.crt"
test_certificate "APISIX" "certs/apisix/apisix.crt"
echo ""

echo "Service Connectivity Tests:"
test_service "ElasticSearch HTTPS" "https://localhost:9443"
test_service "Kibana HTTPS" "https://localhost:5601/api/status"
test_service "Logstash API" "https://localhost:9600"
test_service "APISIX HTTPS" "https://localhost:9443/"
echo ""

echo "Certificate Verification Tests:"
echo -n "ElasticSearch certificate verification... "
if curl -f -s -o /dev/null --cacert certs/ca/ca.crt https://localhost:9443; then
  echo "✓ PASS"
else
  echo "✗ FAIL"
  FAILED_TESTS=$((FAILED_TESTS + 1))
fi

echo -n "TLS 1.3 support... "
if openssl s_client -connect localhost:9443 -tls1_3 </dev/null 2>&1 | grep -q "TLSv1.3"; then
  echo "✓ PASS"
else
  echo "✗ FAIL"
  FAILED_TESTS=$((FAILED_TESTS + 1))
fi
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
  echo "=== All tests passed! ==="
  exit 0
else
  echo "=== $FAILED_TESTS test(s) failed ==="
  exit 1
fi
EOF

chmod +x scripts/test-ssl.sh
./scripts/test-ssl.sh
```

### Browser Testing

**Test HTTPS in Browser:**

1. **Open Kibana:**
   ```
   https://localhost:5601/kibana
   ```

2. **Check Security Indicators:**
   - Green padlock icon (production certificates)
   - "Not Secure" or warning (self-signed certificates)

3. **View Certificate Details:**
   - Click padlock icon
   - Click "Certificate"
   - Verify:
     - Issued to: Correct domain/hostname
     - Issued by: Expected CA
     - Valid from/to: Not expired

4. **Test Mixed Content:**
   - Open browser console (F12)
   - Check for "Mixed Content" warnings
   - All resources should load via HTTPS

5. **Test HSTS:**
   - Open developer tools → Network tab
   - Reload page
   - Check response headers for:
     ```
     Strict-Transport-Security: max-age=31536000
     ```

**Browser Compatibility Testing:**

Test in multiple browsers:
- Chrome/Chromium
- Firefox
- Safari
- Edge

### API Testing

**Test with Different Clients:**

**Python requests:**

```python
import requests

# With certificate verification
response = requests.get(
    'https://localhost:9443/_cluster/health',
    auth=('elastic', 'password'),
    verify='certs/ca/ca.crt'
)
print(response.json())

# ElasticSearch Python client
from elasticsearch import Elasticsearch

es = Elasticsearch(
    ['https://localhost:9443'],
    http_auth=('elastic', 'password'),
    verify_certs=True,
    ca_certs='certs/ca/ca.crt'
)
print(es.cluster.health())
```

**Node.js:**

```javascript
const https = require('https');
const fs = require('fs');

const options = {
  hostname: 'localhost',
  port: 9443,
  path: '/_cluster/health',
  method: 'GET',
  ca: fs.readFileSync('certs/ca/ca.crt'),
  auth: 'elastic:password'
};

https.request(options, (res) => {
  res.on('data', (d) => {
    process.stdout.write(d);
  });
}).end();
```

**Java:**

```java
import org.apache.http.conn.ssl.SSLConnectionSocketFactory;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClients;
import org.apache.http.ssl.SSLContexts;

import javax.net.ssl.SSLContext;
import java.io.File;

SSLContext sslContext = SSLContexts.custom()
    .loadTrustMaterial(new File("certs/ca/ca.crt"), null)
    .build();

CloseableHttpClient httpClient = HttpClients.custom()
    .setSSLSocketFactory(new SSLConnectionSocketFactory(sslContext))
    .build();
```

### Performance Testing

**Measure SSL/TLS Overhead:**

```bash
# HTTP baseline
ab -n 1000 -c 10 http://localhost:9200/

# HTTPS performance
ab -n 1000 -c 10 https://localhost:9443/

# Compare response times
# Expect 10-20% overhead for TLS
```

**Load Testing:**

```bash
# Apache Bench
ab -n 10000 -c 100 \
  -H "Authorization: Basic ZWxhc3RpYzpwYXNzd29yZA==" \
  https://localhost:9443/_cluster/health

# wrk
wrk -t 12 -c 400 -d 30s \
  --header "Authorization: Basic ZWxhc3RpYzpwYXNzd29yZA==" \
  https://localhost:9443/_cluster/health
```

### Security Scanning

**SSL/TLS Vulnerability Scan:**

```bash
# testssl.sh (comprehensive SSL/TLS testing)
git clone https://github.com/drwetter/testssl.sh.git
cd testssl.sh
./testssl.sh https://localhost:9443

# nmap SSL scripts
nmap --script ssl-enum-ciphers -p 9443 localhost
nmap --script ssl-cert,ssl-date -p 9443 localhost

# SSLyze
sslyze --regular localhost:9443

# Qualys SSL Labs (for public sites only)
# https://www.ssllabs.com/ssltest/
```

**Expected Results:**
- Grade: A or A+
- No SSL 2.0, SSL 3.0, TLS 1.0, TLS 1.1
- Forward secrecy supported
- No weak ciphers (RC4, 3DES, MD5)

**Certificate Validation:**

```bash
# Verify certificate chain
openssl verify -CAfile certs/ca/ca.crt certs/elasticsearch/elasticsearch.crt

# Check for certificate revocation
openssl ocsp -issuer certs/ca/ca.crt -cert certs/elasticsearch/elasticsearch.crt \
  -url http://ocsp.example.com

# Verify certificate matches private key
diff <(openssl x509 -in certs/elasticsearch/elasticsearch.crt -noout -modulus) \
     <(openssl rsa -in certs/elasticsearch/elasticsearch.key -noout -modulus)
```

---

## Performance Considerations

Understanding and optimizing SSL/TLS performance impact.

### SSL/TLS Overhead

**Performance Impact:**

| Metric | HTTP | HTTPS | Overhead |
|--------|------|-------|----------|
| Handshake | N/A | 1-2 RTT | +50-100ms |
| Throughput | 100% | 90-95% | -5-10% |
| CPU Usage | Baseline | +10-20% | Variable |
| Memory | Baseline | +5-10% | Variable |

**Factors Affecting Performance:**

1. **TLS Version**:
   - TLS 1.3: Faster handshake (1-RTT), better performance
   - TLS 1.2: 2-RTT handshake, slightly slower

2. **Cipher Suite**:
   - AES-GCM: Fast with hardware acceleration
   - ChaCha20-Poly1305: Fast on mobile/ARM
   - AES-CBC: Slower, avoid if possible

3. **Key Size**:
   - RSA 2048: Good balance
   - RSA 4096: More secure, slower handshake
   - ECDSA P-256: Faster, smaller keys

4. **Session Resumption**:
   - Session ID: Reduces handshake overhead
   - Session Tickets: Zero-RTT resumption

### Hardware Acceleration

**AES-NI (Intel/AMD):**

```bash
# Check if CPU supports AES-NI
grep -m1 -o aes /proc/cpuinfo
# Output: aes (supported)

# Verify OpenSSL uses AES-NI
openssl speed -evp aes-128-gcm
# Look for high Mb/s throughput (>1000 Mb/s indicates hardware acceleration)
```

**SSL Offloading:**

For high-traffic deployments, consider:

1. **Hardware SSL Accelerators**: Dedicated crypto chips
2. **Load Balancers with SSL Termination**: F5, HAProxy, nginx
3. **Cloudflare/CDN**: SSL termination at edge

### Optimization Tips

**1. Enable HTTP/2:**

```yaml
# APISIX configuration
apisix:
  ssl:
    listen:
      - port: 9443
        enable_http2: true  # HTTP/2 for multiplexing
```

**Benefits:**
- Single connection for multiple requests
- Header compression
- Server push
- Faster page loads

**2. Configure Session Resumption:**

```yaml
# APISIX
apisix:
  ssl:
    ssl_session_timeout: 1h
    ssl_session_cache: shared:SSL:10m
```

**ElasticSearch:**

```yaml
environment:
  - xpack.security.http.ssl.session.timeout=1h
  - xpack.security.http.ssl.session.cache_size=1000
```

**3. Use Efficient Cipher Suites:**

```yaml
# Prioritize AES-GCM (hardware accelerated)
ssl_ciphers: >
  TLS_AES_128_GCM_SHA256:
  TLS_AES_256_GCM_SHA384:
  ECDHE-RSA-AES128-GCM-SHA256:
  ECDHE-RSA-AES256-GCM-SHA384
```

**4. Optimize Certificate Chain:**

```bash
# Keep certificate chain small
# Include only necessary intermediate certificates

# Bad: server + intermediate1 + intermediate2 + root (4 certs, large)
# Good: server + intermediate (2 certs, small)

# Minimize certificate size
# Use ECDSA instead of RSA (smaller keys, faster)
```

**5. Enable OCSP Stapling:**

```yaml
# APISIX
apisix:
  ssl:
    ssl_stapling: on
    ssl_stapling_verify: on
```

**Benefits:**
- Faster certificate validation
- Reduced OCSP responder load
- Better privacy

**6. Tune Buffer Sizes:**

```yaml
# Increase SSL buffer size for high throughput
nginx_config:
  http_configuration_snippet: |
    ssl_buffer_size 4k;  # Default: 16k (reduce for lower latency)
```

**7. Connection Pooling:**

```python
# Python example: Reuse connections
import requests
from requests.adapters import HTTPAdapter

session = requests.Session()
adapter = HTTPAdapter(
    pool_connections=100,
    pool_maxsize=100,
    max_retries=3,
    pool_block=False
)
session.mount('https://', adapter)

# Connections are reused, avoiding repeated SSL handshakes
```

### Performance Benchmarking

**Benchmark SSL vs Non-SSL:**

```bash
# HTTP baseline
ab -n 10000 -c 100 http://localhost:9200/ > http-bench.txt

# HTTPS
ab -n 10000 -c 100 https://localhost:9443/ > https-bench.txt

# Compare
echo "HTTP Requests per second:"
grep "Requests per second" http-bench.txt

echo "HTTPS Requests per second:"
grep "Requests per second" https-bench.txt
```

**Monitor CPU Usage:**

```bash
# During load test
docker stats elasticsearch kibana logstash apisix

# Look for CPU spikes during SSL handshakes
```

**Profile SSL Performance:**

```bash
# OpenSSL speed test
openssl speed rsa2048 rsa4096 ecdsap256

# Test cipher performance
openssl speed -evp aes-128-gcm
openssl speed -evp aes-256-gcm
openssl speed -evp chacha20-poly1305
```

### Scaling Considerations

**Horizontal Scaling:**

```yaml
# Run multiple instances behind load balancer
services:
  elasticsearch-1:
    # SSL configured

  elasticsearch-2:
    # SSL configured

  elasticsearch-3:
    # SSL configured

  apisix:
    # Load balances across all 3 instances
    # SSL termination at APISIX
```

**SSL Termination at Load Balancer:**

```
Client → [HTTPS] → Load Balancer → [HTTP] → Backend Services
         (Encrypted)              (Internal, not encrypted)
```

**Benefits:**
- Single point for SSL configuration
- Reduced CPU load on backend services
- Easier certificate management

**End-to-End Encryption:**

```
Client → [HTTPS] → Load Balancer → [HTTPS] → Backend Services
         (Encrypted)                (Encrypted)
```

**Benefits:**
- Maximum security
- Compliance with strict regulations
- Defense in depth

**Recommendation:**
- Use SSL termination for performance
- Use end-to-end encryption for security
- Balance based on requirements

---

## Summary

This guide covered:

1. **Introduction**: What SSL/TLS is and why it's important
2. **Quick Start**: Three paths for different deployment scenarios
3. **Prerequisites**: Requirements before starting
4. **Development Setup**: Self-signed certificates for testing
5. **Production Setup (Let's Encrypt)**: Free automated certificates
6. **Production Setup (Commercial CA)**: Enterprise certificates
7. **Service Configuration**: Detailed settings for each service
8. **Inter-Service Communication**: How services talk securely
9. **Docker Compose Profiles**: Easy SSL enable/disable
10. **Certificate Management**: Renewal, rotation, monitoring
11. **Troubleshooting**: Common issues and solutions
12. **Security Best Practices**: Hardening SSL/TLS
13. **Migration**: HTTP to HTTPS with zero downtime
14. **Testing**: Comprehensive verification
15. **Performance**: Optimization and scaling

**Next Steps:**

1. Choose your deployment path (Development/Production)
2. Generate or obtain certificates
3. Configure services with SSL/TLS
4. Test thoroughly
5. Monitor certificate expiration
6. Keep certificates updated

**Related Documentation:**

- [SECURITY_SETUP.md](SECURITY_SETUP.md) - Password and credential management
- [MONITORING_SETUP.md](MONITORING_SETUP.md) - Monitoring and alerting
- [BACKUP_SETUP.md](BACKUP_SETUP.md) - Backup and recovery

**Support:**

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review logs: `docker-compose logs -f`
3. Test with: `./scripts/test-ssl.sh`

---

**Last Updated:** 2025-12-29
**Version:** 1.0
