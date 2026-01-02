#!/bin/bash
#
# Let's Encrypt SSL/TLS Certificate Setup Script
#
# This script automates the setup of Let's Encrypt SSL/TLS certificates for
# production deployments with real domain names.
#
# Prerequisites:
#   - Domain name pointing to this server's IP address
#   - Ports 80 and 443 accessible from the internet
#   - certbot installed (or use Docker certbot)
#
# Usage:
#   ./scripts/setup-letsencrypt.sh --domain example.com --email admin@example.com
#
# Options:
#   --domain DOMAIN      Domain name for certificate (required)
#   --email EMAIL        Email for Let's Encrypt notifications (required)
#   --staging            Use Let's Encrypt staging server (for testing)
#   --standalone         Use standalone mode (stops APISIX temporarily)
#   --webroot PATH       Use webroot mode with specified path
#   --force              Force certificate renewal
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
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CERTS_DIR="$PROJECT_ROOT/certs"
LETSENCRYPT_DIR="$PROJECT_ROOT/letsencrypt"

# Default configuration
DOMAIN=""
EMAIL=""
STAGING=false
STANDALONE=false
WEBROOT_PATH=""
FORCE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --domain)
            DOMAIN="$2"
            shift 2
            ;;
        --email)
            EMAIL="$2"
            shift 2
            ;;
        --staging)
            STAGING=true
            shift
            ;;
        --standalone)
            STANDALONE=true
            shift
            ;;
        --webroot)
            WEBROOT_PATH="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 --domain DOMAIN --email EMAIL [--staging] [--standalone|--webroot PATH] [--force]"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [ -z "$DOMAIN" ]; then
    echo -e "${RED}Error: --domain is required${NC}"
    echo "Usage: $0 --domain DOMAIN --email EMAIL"
    exit 1
fi

if [ -z "$EMAIL" ]; then
    echo -e "${RED}Error: --email is required${NC}"
    echo "Usage: $0 --domain DOMAIN --email EMAIL"
    exit 1
fi

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Let's Encrypt SSL/TLS Certificate Setup${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Configuration summary
echo -e "${YELLOW}Configuration:${NC}"
echo "  Domain: $DOMAIN"
echo "  Email: $EMAIL"
echo "  Mode: $([ "$STANDALONE" = true ] && echo "Standalone" || echo "Webroot")"
echo "  Server: $([ "$STAGING" = true ] && echo "Staging (testing)" || echo "Production")"
echo ""

# Check if certbot is installed
if ! command -v certbot &> /dev/null; then
    echo -e "${YELLOW}certbot not found. Installing via Docker...${NC}"
    USE_DOCKER=true
else
    echo -e "${GREEN}✓ certbot found: $(certbot --version)${NC}"
    USE_DOCKER=false
fi
echo ""

# Create directories
echo -e "${GREEN}Creating Let's Encrypt directories...${NC}"
mkdir -p "$LETSENCRYPT_DIR"/{config,work,logs,webroot}
echo -e "${GREEN}✓ Directories created${NC}"
echo ""

# Build certbot command
CERTBOT_ARGS=(
    "certonly"
    "--non-interactive"
    "--agree-tos"
    "--email" "$EMAIL"
    "--domains" "$DOMAIN"
)

if [ "$STAGING" = true ]; then
    CERTBOT_ARGS+=("--staging")
fi

if [ "$FORCE" = true ]; then
    CERTBOT_ARGS+=("--force-renewal")
fi

if [ "$STANDALONE" = true ]; then
    # Standalone mode - requires port 80
    CERTBOT_ARGS+=("--standalone")

    echo -e "${YELLOW}Standalone mode: Checking if port 80 is available...${NC}"

    # Check if APISIX is running on port 80
    if docker ps --filter "name=apisix" --format "{{.Names}}" | grep -q apisix; then
        echo -e "${YELLOW}APISIX is running. Stopping temporarily...${NC}"
        docker-compose -f "$PROJECT_ROOT/docker-compose.yml" stop apisix
        RESTART_APISIX=true
    fi

    # Check if port 80 is in use
    if netstat -tuln | grep -q ":80 "; then
        echo -e "${RED}Error: Port 80 is in use by another process${NC}"
        echo "Please stop the service using port 80 or use --webroot mode"
        exit 1
    fi

    echo -e "${GREEN}✓ Port 80 is available${NC}"
    echo ""
else
    # Webroot mode - works with running web server
    if [ -z "$WEBROOT_PATH" ]; then
        WEBROOT_PATH="$LETSENCRYPT_DIR/webroot"
    fi

    CERTBOT_ARGS+=("--webroot" "--webroot-path" "$WEBROOT_PATH")

    echo -e "${YELLOW}Webroot mode: Using path $WEBROOT_PATH${NC}"
    echo ""

    # Create .well-known directory
    mkdir -p "$WEBROOT_PATH/.well-known/acme-challenge"

    echo -e "${YELLOW}Configure your web server to serve:${NC}"
    echo "  $WEBROOT_PATH/.well-known/acme-challenge"
    echo "  at URL: http://$DOMAIN/.well-known/acme-challenge"
    echo ""

    read -p "Is your web server configured? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "Please configure your web server first"
        exit 0
    fi
    echo ""
fi

# Run certbot
echo -e "${GREEN}Requesting SSL certificate from Let's Encrypt...${NC}"
echo ""

if [ "$USE_DOCKER" = true ]; then
    # Use Docker certbot
    docker run --rm -it \
        -v "$LETSENCRYPT_DIR/config:/etc/letsencrypt" \
        -v "$LETSENCRYPT_DIR/work:/var/lib/letsencrypt" \
        -v "$LETSENCRYPT_DIR/logs:/var/log/letsencrypt" \
        -v "$LETSENCRYPT_DIR/webroot:/webroot" \
        -p 80:80 \
        certbot/certbot "${CERTBOT_ARGS[@]}"
else
    # Use system certbot
    if [ "$STANDALONE" = true ]; then
        sudo certbot "${CERTBOT_ARGS[@]}"
    else
        sudo certbot "${CERTBOT_ARGS[@]}"
    fi
fi

# Restart APISIX if stopped
if [ "${RESTART_APISIX:-false}" = true ]; then
    echo ""
    echo -e "${GREEN}Restarting APISIX...${NC}"
    docker-compose -f "$PROJECT_ROOT/docker-compose.yml" start apisix
    echo -e "${GREEN}✓ APISIX restarted${NC}"
fi

echo ""
echo -e "${GREEN}✓ SSL certificate obtained successfully${NC}"
echo ""

# Copy certificates to certs directory
echo -e "${GREEN}Copying certificates to certs directory...${NC}"

mkdir -p "$CERTS_DIR"/{apisix,elasticsearch,kibana,logstash}

if [ "$USE_DOCKER" = true ]; then
    CERT_PATH="$LETSENCRYPT_DIR/config/live/$DOMAIN"
else
    CERT_PATH="/etc/letsencrypt/live/$DOMAIN"
fi

# Copy for APISIX (main gateway)
if [ "$USE_DOCKER" = true ]; then
    cp "$CERT_PATH/fullchain.pem" "$CERTS_DIR/apisix/apisix.crt"
    cp "$CERT_PATH/privkey.pem" "$CERTS_DIR/apisix/apisix.key"
    cp "$CERT_PATH/chain.pem" "$CERTS_DIR/apisix/ca.crt"
else
    sudo cp "$CERT_PATH/fullchain.pem" "$CERTS_DIR/apisix/apisix.crt"
    sudo cp "$CERT_PATH/privkey.pem" "$CERTS_DIR/apisix/apisix.key"
    sudo cp "$CERT_PATH/chain.pem" "$CERTS_DIR/apisix/ca.crt"
    sudo chown -R $(whoami):$(whoami) "$CERTS_DIR/apisix"
fi

# Copy for other services (they can use the same cert)
cp "$CERTS_DIR/apisix/apisix.crt" "$CERTS_DIR/elasticsearch/elasticsearch.crt"
cp "$CERTS_DIR/apisix/apisix.key" "$CERTS_DIR/elasticsearch/elasticsearch.key"
cp "$CERTS_DIR/apisix/apisix.crt" "$CERTS_DIR/kibana/kibana.crt"
cp "$CERTS_DIR/apisix/apisix.key" "$CERTS_DIR/kibana/kibana.key"
cp "$CERTS_DIR/apisix/apisix.crt" "$CERTS_DIR/logstash/logstash.crt"
cp "$CERTS_DIR/apisix/apisix.key" "$CERTS_DIR/logstash/logstash.key"

# Set permissions
chmod 644 "$CERTS_DIR"/*/*.crt
chmod 600 "$CERTS_DIR"/*/*.key

echo -e "${GREEN}✓ Certificates copied${NC}"
echo ""

# Create renewal script
cat > "$PROJECT_ROOT/scripts/renew-letsencrypt.sh" <<'RENEWAL_SCRIPT'
#!/bin/bash
#
# Let's Encrypt Certificate Renewal Script
#
# This script should be run via cron to automatically renew certificates
# before they expire (Let's Encrypt certificates expire after 90 days).
#
# Recommended cron schedule (runs daily at 3 AM):
#   0 3 * * * /path/to/scripts/renew-letsencrypt.sh >> /var/log/letsencrypt-renewal.log 2>&1
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CERTS_DIR="$PROJECT_ROOT/certs"
LETSENCRYPT_DIR="$PROJECT_ROOT/letsencrypt"

echo "$(date): Checking for certificate renewal..."

# Check if Docker certbot is used
if [ -d "$LETSENCRYPT_DIR/config" ]; then
    # Docker certbot
    docker run --rm \
        -v "$LETSENCRYPT_DIR/config:/etc/letsencrypt" \
        -v "$LETSENCRYPT_DIR/work:/var/lib/letsencrypt" \
        -v "$LETSENCRYPT_DIR/logs:/var/log/letsencrypt" \
        -v "$LETSENCRYPT_DIR/webroot:/webroot" \
        certbot/certbot renew --quiet --deploy-hook "/scripts/copy-certs.sh"
else
    # System certbot
    sudo certbot renew --quiet --deploy-hook "/path/to/scripts/copy-certs.sh"
fi

echo "$(date): Certificate renewal check complete"
RENEWAL_SCRIPT

chmod +x "$PROJECT_ROOT/scripts/renew-letsencrypt.sh"

echo -e "${GREEN}✓ Renewal script created: scripts/renew-letsencrypt.sh${NC}"
echo ""

# Create certificate copy script for renewal hook
cat > "$PROJECT_ROOT/scripts/copy-certs.sh" <<COPY_SCRIPT
#!/bin/bash
# Copy renewed certificates to certs directory

SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="\$(cd "\$SCRIPT_DIR/.." && pwd)"
CERTS_DIR="\$PROJECT_ROOT/certs"
LETSENCRYPT_DIR="\$PROJECT_ROOT/letsencrypt"

if [ -d "\$LETSENCRYPT_DIR/config" ]; then
    CERT_PATH="\$LETSENCRYPT_DIR/config/live/$DOMAIN"
else
    CERT_PATH="/etc/letsencrypt/live/$DOMAIN"
fi

# Copy to all service directories
for service in apisix elasticsearch kibana logstash; do
    cp "\$CERT_PATH/fullchain.pem" "\$CERTS_DIR/\$service/\${service}.crt"
    cp "\$CERT_PATH/privkey.pem" "\$CERTS_DIR/\$service/\${service}.key"
    chmod 644 "\$CERTS_DIR/\$service/\${service}.crt"
    chmod 600 "\$CERTS_DIR/\$service/\${service}.key"
done

# Reload APISIX to pick up new certificates
docker-compose -f "\$PROJECT_ROOT/docker-compose.yml" exec apisix apisix reload || true

echo "Certificates copied and APISIX reloaded"
COPY_SCRIPT

chmod +x "$PROJECT_ROOT/scripts/copy-certs.sh"

echo -e "${GREEN}✓ Certificate copy script created: scripts/copy-certs.sh${NC}"
echo ""

# Summary
echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  ✓ Let's Encrypt Setup Complete${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Certificate Details:${NC}"
echo "  Domain: $DOMAIN"
echo "  Email: $EMAIL"
echo "  Certificate Path: $CERT_PATH"
echo "  Expires: In 90 days (auto-renewal configured)"
echo ""
echo -e "${YELLOW}Certificates Installed:${NC}"
echo "  APISIX: $CERTS_DIR/apisix/"
echo "  ElasticSearch: $CERTS_DIR/elasticsearch/"
echo "  Kibana: $CERTS_DIR/kibana/"
echo "  Logstash: $CERTS_DIR/logstash/"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "  1. Enable SSL/TLS in .env file:"
echo "     ${BLUE}SSL_ENABLED=true${NC}"
echo "     ${BLUE}SSL_DOMAIN=$DOMAIN${NC}"
echo ""
echo "  2. Restart services with SSL profile:"
echo "     ${BLUE}docker-compose --profile ssl up -d${NC}"
echo ""
echo "  3. Verify HTTPS access:"
echo "     ${BLUE}curl https://$DOMAIN:9443/elasticsearch/_cluster/health${NC}"
echo ""
echo -e "${YELLOW}Automatic Renewal:${NC}"
echo ""
echo "  Certificates will expire in 90 days. Set up automatic renewal:"
echo ""
echo "  Add to crontab (run daily at 3 AM):"
echo "     ${BLUE}0 3 * * * $PROJECT_ROOT/scripts/renew-letsencrypt.sh >> /var/log/letsencrypt-renewal.log 2>&1${NC}"
echo ""
echo "  Or test renewal manually:"
echo "     ${BLUE}$PROJECT_ROOT/scripts/renew-letsencrypt.sh${NC}"
echo ""
echo -e "${YELLOW}Certificate Information:${NC}"
echo ""
echo "  View certificate details:"
echo "     ${BLUE}openssl x509 -in $CERTS_DIR/apisix/apisix.crt -text -noout${NC}"
echo ""
echo "  Check expiration date:"
echo "     ${BLUE}openssl x509 -in $CERTS_DIR/apisix/apisix.crt -noout -dates${NC}"
echo ""

# Create certificate information file
cat > "$CERTS_DIR/LETSENCRYPT_INFO.txt" <<INFO
Let's Encrypt Certificate Information
Generated: $(date)
Domain: $DOMAIN
Email: $EMAIL
Server: $([ "$STAGING" = true ] && echo "Staging" || echo "Production")

Certificate Locations:
  Live Certificates: $CERT_PATH
  Copied to: $CERTS_DIR

Certificate Files:
  fullchain.pem -> apisix.crt (full certificate chain)
  privkey.pem -> apisix.key (private key)
  chain.pem -> ca.crt (intermediate certificates)

Renewal:
  Automatic: scripts/renew-letsencrypt.sh (add to cron)
  Manual: sudo certbot renew

Expiration:
  Certificates expire after 90 days
  Let's Encrypt recommends renewal at 60 days
  Auto-renewal will attempt renewal daily

Cron Job:
  0 3 * * * $PROJECT_ROOT/scripts/renew-letsencrypt.sh >> /var/log/letsencrypt-renewal.log 2>&1
INFO

echo "Certificate information saved to: $CERTS_DIR/LETSENCRYPT_INFO.txt"
echo ""
