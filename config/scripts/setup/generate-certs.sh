#!/bin/bash
#
# SSL/TLS Certificate Generation Script
#
# This script generates self-signed SSL/TLS certificates for the platform.
#
# SSL Architecture:
#   - SSL Termination at APISIX Gateway (ACTIVE)
#   - Direct HTTPS for APM Server (ACTIVE - port 8200 exposed for CloudHub)
#   - Optional end-to-end encryption for internal services (EXTRA)
#
# Active Certificates (certs/):
#   - apisix/       - Gateway SSL termination (REQUIRED)
#   - apm-server/   - Direct HTTPS endpoint (REQUIRED for CloudHub)
#   - ca/           - Certificate Authority (REQUIRED)
#
# Optional Certificates (certs/extra/):
#   - elasticsearch/, kibana/, logstash/, prometheus/, grafana/, alertmanager/
#   - For compliance requirements (HIPAA, PCI-DSS, zero-trust architecture)
#
# Usage:
#   ./config/scripts/setup/generate-certs.sh [options]
#
# Options:
#   --domain DOMAIN    Domain name for certificates (default: localhost)
#   --days DAYS        Certificate validity in days (default: 3650 = 10 years)
#   --force            Overwrite existing certificates
#   --ca-only          Only generate CA certificate
#   --active-only      Only generate active certificates (APISIX, APM Server, CA)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CERTS_DIR="$PROJECT_ROOT/certs"

# Default configuration
DOMAIN="${SSL_DOMAIN:-localhost}"
DAYS=3650
FORCE=false
CA_ONLY=false
ACTIVE_ONLY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --domain)
            DOMAIN="$2"
            shift 2
            ;;
        --days)
            DAYS="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --ca-only)
            CA_ONLY=true
            shift
            ;;
        --active-only)
            ACTIVE_ONLY=true
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--domain DOMAIN] [--days DAYS] [--force] [--ca-only] [--active-only]"
            exit 1
            ;;
    esac
done

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   SSL/TLS Certificate Generation${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Configuration summary
echo -e "${YELLOW}Configuration:${NC}"
echo "  Domain: $DOMAIN"
echo "  Validity: $DAYS days ($(echo "scale=1; $DAYS / 365" | bc) years)"
echo "  Certificate Directory: $CERTS_DIR"
echo ""

# Check if certs directory exists
if [ -d "$CERTS_DIR" ] && [ "$FORCE" != true ]; then
    echo -e "${YELLOW}Warning: Certificate directory already exists${NC}"
    read -p "Overwrite existing certificates? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "Certificate generation cancelled."
        exit 0
    fi
    echo ""
fi

# Create directory structure
echo -e "${GREEN}Creating certificate directory structure...${NC}"
mkdir -p "$CERTS_DIR"/{ca,apisix,apm-server}
if [ "$ACTIVE_ONLY" != true ]; then
    mkdir -p "$CERTS_DIR/extra"/{elasticsearch,kibana,logstash,prometheus,grafana,alertmanager}
fi
echo -e "${GREEN}✓ Directory structure created${NC}"
echo ""

# ========================================
# Generate Certificate Authority (CA)
# ========================================
echo -e "${GREEN}[1/8] Generating Certificate Authority (CA)...${NC}"

if [ -f "$CERTS_DIR/ca/ca.key" ] && [ "$FORCE" != true ]; then
    echo -e "${YELLOW}CA certificate already exists, skipping...${NC}"
else
    # Generate CA private key
    openssl genrsa -out "$CERTS_DIR/ca/ca.key" 4096

    # Generate CA certificate
    openssl req -new -x509 -days "$DAYS" -key "$CERTS_DIR/ca/ca.key" \
        -out "$CERTS_DIR/ca/ca.crt" \
        -subj "/C=US/ST=State/L=City/O=Organization/OU=IT/CN=ELK-Stack-CA"

    echo -e "${GREEN}✓ CA certificate generated${NC}"
fi
echo ""

if [ "$CA_ONLY" = true ]; then
    echo -e "${GREEN}CA-only mode: Stopping after CA generation${NC}"
    exit 0
fi

# ========================================
# Generate APISIX Certificates (ACTIVE)
# ========================================
echo -e "${GREEN}[2/3] Generating APISIX certificates (SSL termination)...${NC}"

cat > "$CERTS_DIR/apisix/apisix.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = Organization
OU = IT
CN = apisix

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = apisix
DNS.2 = localhost
DNS.3 = ${DOMAIN}
IP.1 = 127.0.0.1
IP.2 = 172.42.0.20
EOF

openssl genrsa -out "$CERTS_DIR/apisix/apisix.key" 2048

openssl req -new -key "$CERTS_DIR/apisix/apisix.key" \
    -out "$CERTS_DIR/apisix/apisix.csr" \
    -config "$CERTS_DIR/apisix/apisix.cnf"

openssl x509 -req -in "$CERTS_DIR/apisix/apisix.csr" \
    -CA "$CERTS_DIR/ca/ca.crt" -CAkey "$CERTS_DIR/ca/ca.key" \
    -CAcreateserial -out "$CERTS_DIR/apisix/apisix.crt" \
    -days "$DAYS" -extensions v3_req \
    -extfile "$CERTS_DIR/apisix/apisix.cnf"

echo -e "${GREEN}✓ APISIX certificates generated${NC}"
echo ""

# ========================================
# Generate APM Server Certificates (ACTIVE)
# ========================================
echo -e "${GREEN}[3/3] Generating APM Server certificates (direct HTTPS endpoint)...${NC}"

cat > "$CERTS_DIR/apm-server/apm-server.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = Organization
OU = IT
CN = apm-server

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = apm-server
DNS.2 = localhost
DNS.3 = ${DOMAIN}
IP.1 = 127.0.0.1
IP.2 = 172.42.0.13
EOF

openssl genrsa -out "$CERTS_DIR/apm-server/apm-server.key" 2048

openssl req -new -key "$CERTS_DIR/apm-server/apm-server.key" \
    -out "$CERTS_DIR/apm-server/apm-server.csr" \
    -config "$CERTS_DIR/apm-server/apm-server.cnf"

openssl x509 -req -in "$CERTS_DIR/apm-server/apm-server.csr" \
    -CA "$CERTS_DIR/ca/ca.crt" -CAkey "$CERTS_DIR/ca/ca.key" \
    -CAcreateserial -out "$CERTS_DIR/apm-server/apm-server.crt" \
    -days "$DAYS" -extensions v3_req \
    -extfile "$CERTS_DIR/apm-server/apm-server.cnf"

echo -e "${GREEN}✓ APM Server certificates generated${NC}"
echo ""

if [ "$ACTIVE_ONLY" = true ]; then
    echo -e "${GREEN}Active-only mode: Skipping optional certificates${NC}"
    echo -e "${YELLOW}To generate optional end-to-end encryption certificates, run without --active-only${NC}"
    echo ""

    # Skip to permissions and summary
    # Set Permissions
    echo -e "${GREEN}Setting file permissions...${NC}"
    find "$CERTS_DIR" -name "*.key" -exec chmod 600 {} \;
    find "$CERTS_DIR" -name "*.crt" -exec chmod 644 {} \;
    find "$CERTS_DIR" -type d -exec chmod 755 {} \;
    echo -e "${GREEN}✓ Permissions set${NC}"
    echo ""

    # Print summary for active-only
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  ✓ Active SSL/TLS Certificates Generated Successfully${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${YELLOW}Certificate Summary:${NC}"
    echo ""
    echo "  Certificate Authority:"
    echo "    CA Certificate: $CERTS_DIR/ca/ca.crt"
    echo "    CA Key: $CERTS_DIR/ca/ca.key"
    echo ""
    echo "  Active Certificates (SSL Termination):"
    echo "    APISIX Gateway: $CERTS_DIR/apisix/"
    echo "    APM Server: $CERTS_DIR/apm-server/"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo ""
    echo "  1. Enable SSL/TLS in .env file:"
    echo "     ${BLUE}SSL_ENABLED=true${NC}"
    echo ""
    echo "  2. Start services with SSL configuration:"
    echo "     ${BLUE}docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d${NC}"
    echo ""
    echo "  3. Verify HTTPS access:"
    echo "     ${BLUE}curl -k https://localhost:9443/apisix/status${NC}"
    echo ""
    exit 0
fi

echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  Generating Optional Certificates (End-to-End Encryption)${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}These certificates are optional and only needed for:${NC}"
echo "  - HIPAA compliance (healthcare data)"
echo "  - PCI-DSS compliance (payment card data)"
echo "  - Government/military deployments"
echo "  - Zero-trust network architecture"
echo ""
echo -e "${YELLOW}Location: certs/extra/${NC}"
echo ""

# ========================================
# Generate ElasticSearch Certificates (EXTRA)
# ========================================
echo -e "${GREEN}[Extra 1/6] Generating ElasticSearch certificates...${NC}"

# Create ElasticSearch config for SAN
cat > "$CERTS_DIR/extra/elasticsearch/elasticsearch.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = Organization
OU = IT
CN = elasticsearch

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = elasticsearch
DNS.2 = localhost
DNS.3 = ${DOMAIN}
IP.1 = 127.0.0.1
IP.2 = 172.42.0.10
EOF

# Generate ElasticSearch private key
openssl genrsa -out "$CERTS_DIR/extra/elasticsearch/elasticsearch.key" 2048

# Generate ElasticSearch certificate signing request (CSR)
openssl req -new -key "$CERTS_DIR/extra/elasticsearch/elasticsearch.key" \
    -out "$CERTS_DIR/extra/elasticsearch/elasticsearch.csr" \
    -config "$CERTS_DIR/extra/elasticsearch/elasticsearch.cnf"

# Sign ElasticSearch certificate with CA
openssl x509 -req -in "$CERTS_DIR/extra/elasticsearch/elasticsearch.csr" \
    -CA "$CERTS_DIR/ca/ca.crt" -CAkey "$CERTS_DIR/ca/ca.key" \
    -CAcreateserial -out "$CERTS_DIR/extra/elasticsearch/elasticsearch.crt" \
    -days "$DAYS" -extensions v3_req \
    -extfile "$CERTS_DIR/extra/elasticsearch/elasticsearch.cnf"

# Create PKCS#12 bundle (for Elastic)
openssl pkcs12 -export -out "$CERTS_DIR/extra/elasticsearch/elasticsearch.p12" \
    -in "$CERTS_DIR/extra/elasticsearch/elasticsearch.crt" \
    -inkey "$CERTS_DIR/extra/elasticsearch/elasticsearch.key" \
    -certfile "$CERTS_DIR/ca/ca.crt" \
    -name "elasticsearch" -passout pass:changeit

echo -e "${GREEN}✓ ElasticSearch certificates generated${NC}"
echo ""

# ========================================
# Generate Kibana Certificates (EXTRA)
# ========================================
echo -e "${GREEN}[Extra 2/6] Generating Kibana certificates...${NC}"

cat > "$CERTS_DIR/extra/kibana/kibana.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = Organization
OU = IT
CN = kibana

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = kibana
DNS.2 = localhost
DNS.3 = ${DOMAIN}
IP.1 = 127.0.0.1
IP.2 = 172.42.0.12
EOF

openssl genrsa -out "$CERTS_DIR/extra/kibana/kibana.key" 2048

openssl req -new -key "$CERTS_DIR/extra/kibana/kibana.key" \
    -out "$CERTS_DIR/extra/kibana/kibana.csr" \
    -config "$CERTS_DIR/extra/kibana/kibana.cnf"

openssl x509 -req -in "$CERTS_DIR/extra/kibana/kibana.csr" \
    -CA "$CERTS_DIR/ca/ca.crt" -CAkey "$CERTS_DIR/ca/ca.key" \
    -CAcreateserial -out "$CERTS_DIR/extra/kibana/kibana.crt" \
    -days "$DAYS" -extensions v3_req \
    -extfile "$CERTS_DIR/extra/kibana/kibana.cnf"

echo -e "${GREEN}✓ Kibana certificates generated${NC}"
echo ""

# ========================================
# Generate Logstash Certificates (EXTRA)
# ========================================
echo -e "${GREEN}[Extra 3/6] Generating Logstash certificates...${NC}"

cat > "$CERTS_DIR/extra/logstash/logstash.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = Organization
OU = IT
CN = logstash

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = logstash
DNS.2 = localhost
DNS.3 = ${DOMAIN}
IP.1 = 127.0.0.1
IP.2 = 172.42.0.11
EOF

openssl genrsa -out "$CERTS_DIR/extra/logstash/logstash.key" 2048

openssl req -new -key "$CERTS_DIR/extra/logstash/logstash.key" \
    -out "$CERTS_DIR/extra/logstash/logstash.csr" \
    -config "$CERTS_DIR/extra/logstash/logstash.cnf"

openssl x509 -req -in "$CERTS_DIR/extra/logstash/logstash.csr" \
    -CA "$CERTS_DIR/ca/ca.crt" -CAkey "$CERTS_DIR/ca/ca.key" \
    -CAcreateserial -out "$CERTS_DIR/extra/logstash/logstash.crt" \
    -days "$DAYS" -extensions v3_req \
    -extfile "$CERTS_DIR/extra/logstash/logstash.cnf"

echo -e "${GREEN}✓ Logstash certificates generated${NC}"
echo ""

# ========================================
# Generate Prometheus Certificates (EXTRA)
# ========================================
echo -e "${GREEN}[Extra 4/6] Generating Prometheus certificates...${NC}"

cat > "$CERTS_DIR/extra/prometheus/prometheus.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = Organization
OU = IT
CN = prometheus

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = prometheus
DNS.2 = localhost
DNS.3 = ${DOMAIN}
IP.1 = 127.0.0.1
IP.2 = 172.42.0.23
EOF

openssl genrsa -out "$CERTS_DIR/extra/prometheus/prometheus.key" 2048

openssl req -new -key "$CERTS_DIR/extra/prometheus/prometheus.key" \
    -out "$CERTS_DIR/extra/prometheus/prometheus.csr" \
    -config "$CERTS_DIR/extra/prometheus/prometheus.cnf"

openssl x509 -req -in "$CERTS_DIR/extra/prometheus/prometheus.csr" \
    -CA "$CERTS_DIR/ca/ca.crt" -CAkey "$CERTS_DIR/ca/ca.key" \
    -CAcreateserial -out "$CERTS_DIR/extra/prometheus/prometheus.crt" \
    -days "$DAYS" -extensions v3_req \
    -extfile "$CERTS_DIR/extra/prometheus/prometheus.cnf"

echo -e "${GREEN}✓ Prometheus certificates generated${NC}"
echo ""

# ========================================
# Generate Grafana Certificates (EXTRA)
# ========================================
echo -e "${GREEN}[Extra 5/6] Generating Grafana certificates...${NC}"

cat > "$CERTS_DIR/extra/grafana/grafana.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = Organization
OU = IT
CN = grafana

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = grafana
DNS.2 = localhost
DNS.3 = ${DOMAIN}
IP.1 = 127.0.0.1
IP.2 = 172.42.0.24
EOF

openssl genrsa -out "$CERTS_DIR/extra/grafana/grafana.key" 2048

openssl req -new -key "$CERTS_DIR/extra/grafana/grafana.key" \
    -out "$CERTS_DIR/extra/grafana/grafana.csr" \
    -config "$CERTS_DIR/extra/grafana/grafana.cnf"

openssl x509 -req -in "$CERTS_DIR/extra/grafana/grafana.csr" \
    -CA "$CERTS_DIR/ca/ca.crt" -CAkey "$CERTS_DIR/ca/ca.key" \
    -CAcreateserial -out "$CERTS_DIR/extra/grafana/grafana.crt" \
    -days "$DAYS" -extensions v3_req \
    -extfile "$CERTS_DIR/extra/grafana/grafana.cnf"

echo -e "${GREEN}✓ Grafana certificates generated${NC}"
echo ""

# ========================================
# Generate Alertmanager Certificates (EXTRA)
# ========================================
echo -e "${GREEN}[Extra 6/6] Generating Alertmanager certificates...${NC}"

cat > "$CERTS_DIR/extra/alertmanager/alertmanager.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = Organization
OU = IT
CN = alertmanager

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = alertmanager
DNS.2 = localhost
DNS.3 = ${DOMAIN}
IP.1 = 127.0.0.1
IP.2 = 172.42.0.25
EOF

openssl genrsa -out "$CERTS_DIR/extra/alertmanager/alertmanager.key" 2048

openssl req -new -key "$CERTS_DIR/extra/alertmanager/alertmanager.key" \
    -out "$CERTS_DIR/extra/alertmanager/alertmanager.csr" \
    -config "$CERTS_DIR/extra/alertmanager/alertmanager.cnf"

openssl x509 -req -in "$CERTS_DIR/extra/alertmanager/alertmanager.csr" \
    -CA "$CERTS_DIR/ca/ca.crt" -CAkey "$CERTS_DIR/ca/ca.key" \
    -CAcreateserial -out "$CERTS_DIR/extra/alertmanager/alertmanager.crt" \
    -days "$DAYS" -extensions v3_req \
    -extfile "$CERTS_DIR/extra/alertmanager/alertmanager.cnf"

echo -e "${GREEN}✓ Alertmanager certificates generated${NC}"
echo ""

# ========================================
# Set Permissions
# ========================================
echo -e "${GREEN}Setting file permissions...${NC}"

# Set restrictive permissions on private keys
find "$CERTS_DIR" -name "*.key" -exec chmod 600 {} \;

# Set readable permissions on certificates
find "$CERTS_DIR" -name "*.crt" -exec chmod 644 {} \;
find "$CERTS_DIR" -name "*.pem" -exec chmod 644 {} \; 2>/dev/null || true

# Set directory permissions
find "$CERTS_DIR" -type d -exec chmod 755 {} \;

echo -e "${GREEN}✓ Permissions set${NC}"
echo ""

# ========================================
# Generate Summary
# ========================================
echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  ✓ SSL/TLS Certificates Generated Successfully${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Certificate Summary:${NC}"
echo ""
echo "  Certificate Authority:"
echo "    CA Certificate: $CERTS_DIR/ca/ca.crt"
echo "    CA Key: $CERTS_DIR/ca/ca.key"
echo ""
echo "  Active Certificates (SSL Termination):"
echo "    APISIX Gateway: $CERTS_DIR/apisix/"
echo "    APM Server: $CERTS_DIR/apm-server/"
echo ""
echo "  Optional Certificates (End-to-End Encryption):"
echo "    ElasticSearch: $CERTS_DIR/extra/elasticsearch/"
echo "    Kibana: $CERTS_DIR/extra/kibana/"
echo "    Logstash: $CERTS_DIR/extra/logstash/"
echo "    Prometheus: $CERTS_DIR/extra/prometheus/"
echo "    Grafana: $CERTS_DIR/extra/grafana/"
echo "    Alertmanager: $CERTS_DIR/extra/alertmanager/"
echo ""
echo -e "${YELLOW}SSL Architecture:${NC}"
echo ""
echo "  Default: SSL termination at APISIX gateway"
echo "    - External traffic encrypted (HTTPS on port 9443)"
echo "    - Internal services use HTTP on trusted Docker network"
echo "    - APM Server uses HTTPS (port 8200 directly exposed for CloudHub)"
echo ""
echo "  Optional: End-to-end encryption"
echo "    - For HIPAA, PCI-DSS, government/military deployments"
echo "    - Certificates available in certs/extra/"
echo "    - See docs/SSL_TLS_SETUP.md for configuration"
echo ""
echo -e "${YELLOW}Certificate Details:${NC}"
echo "  Domain: $DOMAIN"
echo "  Validity: $DAYS days (expires: $(date -d "+$DAYS days" '+%Y-%m-%d'))"
echo "  Type: Self-Signed (Development/Internal Use)"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "  1. Enable SSL/TLS in .env file:"
echo "     ${BLUE}SSL_ENABLED=true${NC}"
echo ""
echo "  2. Start services with SSL configuration:"
echo "     ${BLUE}docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d${NC}"
echo ""
echo "  3. Verify HTTPS access:"
echo "     ${BLUE}curl -k https://localhost:9443/apisix/status${NC}"
echo "     ${BLUE}curl -k https://localhost:8200/${NC}"
echo ""
echo -e "${YELLOW}Security Notes:${NC}"
echo ""
echo "  - These are SELF-SIGNED certificates for development/testing"
echo "  - For production, use Let's Encrypt or commercial CA certificates"
echo "  - Browsers will show security warnings for self-signed certs"
echo "  - Add '-k' or '--insecure' flag to curl for testing"
echo ""
echo -e "${YELLOW}Trust CA Certificate (Optional):${NC}"
echo ""
echo "  Linux:"
echo "    ${BLUE}sudo cp $CERTS_DIR/ca/ca.crt /usr/local/share/ca-certificates/elk-ca.crt${NC}"
echo "    ${BLUE}sudo update-ca-certificates${NC}"
echo ""
echo "  macOS:"
echo "    ${BLUE}sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $CERTS_DIR/ca/ca.crt${NC}"
echo ""
echo "  Windows:"
echo "    Import $CERTS_DIR/ca/ca.crt to Trusted Root Certificate Authorities"
echo ""

# Create certificate inventory file
cat > "$CERTS_DIR/CERTIFICATE_INVENTORY.txt" <<EOF
SSL/TLS Certificate Inventory
Generated: $(date)
Domain: $DOMAIN
Validity: $DAYS days
Expires: $(date -d "+$DAYS days" '+%Y-%m-%d')

SSL Architecture:
  - SSL Termination at APISIX Gateway (default)
  - Direct HTTPS for APM Server (port 8200 exposed for CloudHub)
  - Optional end-to-end encryption (certs in extra/)

Certificate Authority:
  - ca/ca.crt (Certificate)
  - ca/ca.key (Private Key)

Active Certificates (SSL Termination):
  APISIX Gateway:
    - apisix/apisix.crt
    - apisix/apisix.key

  APM Server:
    - apm-server/apm-server.crt
    - apm-server/apm-server.key

Optional Certificates (End-to-End Encryption):
  Located in: certs/extra/
  For: HIPAA, PCI-DSS, zero-trust architecture

  ElasticSearch:
    - extra/elasticsearch/elasticsearch.crt
    - extra/elasticsearch/elasticsearch.key
    - extra/elasticsearch/elasticsearch.p12 (PKCS#12, password: changeit)

  Kibana:
    - extra/kibana/kibana.crt
    - extra/kibana/kibana.key

  Logstash:
    - extra/logstash/logstash.crt
    - extra/logstash/logstash.key

  Prometheus:
    - extra/prometheus/prometheus.crt
    - extra/prometheus/prometheus.key

  Grafana:
    - extra/grafana/grafana.crt
    - extra/grafana/grafana.key

  Alertmanager:
    - extra/alertmanager/alertmanager.crt
    - extra/alertmanager/alertmanager.key

Renewal:
  Active certs only: ./config/scripts/setup/generate-certs.sh --active-only --force
  All certs: ./config/scripts/setup/generate-certs.sh --force
EOF

echo "Certificate inventory saved to: $CERTS_DIR/CERTIFICATE_INVENTORY.txt"
echo ""
