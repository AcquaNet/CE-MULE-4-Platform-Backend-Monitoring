#!/bin/bash
#
# ELK Stack - Interactive Setup Wizard
#
# This wizard guides you through complete configuration of the ELK Stack,
# including security, SSL/TLS, resources, monitoring, and backup settings.
#
# Usage:
#   ./setup-wizard.sh
#

set -e

# Color definitions
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration variables
DEPLOYMENT_MODE=""
ENVIRONMENT_NAME=""
DOMAIN_NAME=""
SSL_ENABLED="false"
SSL_TYPE=""
ELASTIC_MEMORY="2g"
LOGSTASH_MEMORY="1g"
KIBANA_MEMORY="1g"
PROMETHEUS_RETENTION="30d"
BACKUP_ENABLED="false"
BACKUP_SCHEDULE=""
ALERTING_ENABLED="false"
ALERTMANAGER_EMAIL=""
LOG_RETENTION_DAYS="730"
MONITORING_ENABLED="true"

# Helper functions
print_header() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
}

print_section() {
    echo ""
    echo -e "${BLUE}────────────────────────────────────────${NC}"
    echo -e "${BOLD}$1${NC}"
    echo -e "${BLUE}────────────────────────────────────────${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local response

    read -p "$(echo -e ${YELLOW}${prompt}${NC} [${default}]: )" response
    echo "${response:-$default}"
}

prompt_yes_no() {
    local prompt="$1"
    local default="${2:-n}"
    local response

    if [ "$default" = "y" ]; then
        read -p "$(echo -e ${YELLOW}${prompt}${NC} [Y/n]: )" response
        response="${response:-y}"
    else
        read -p "$(echo -e ${YELLOW}${prompt}${NC} [y/N]: )" response
        response="${response:-n}"
    fi

    [[ "$response" =~ ^[Yy] ]]
}

prompt_choice() {
    local prompt="$1"
    shift
    local options=("$@")
    local choice

    echo -e "${YELLOW}${prompt}${NC}"
    for i in "${!options[@]}"; do
        echo "  $((i+1)). ${options[$i]}"
    done

    while true; do
        read -p "Enter choice [1-${#options[@]}]: " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
            echo "${options[$((choice-1))]}"
            return
        fi
        echo "Invalid choice. Please try again."
    done
}

generate_password() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-25
}

# Check prerequisites
check_prerequisites() {
    print_section "Checking Prerequisites"

    local missing=0

    # Check Docker
    if command -v docker &> /dev/null; then
        print_success "Docker is installed"
        if docker ps &> /dev/null; then
            print_success "Docker daemon is running"
        else
            print_error "Docker daemon is not running"
            echo "Please start Docker and try again"
            exit 1
        fi
    else
        print_error "Docker is not installed"
        missing=1
    fi

    # Check docker-compose
    if command -v docker-compose &> /dev/null; then
        print_success "docker-compose is installed"
    else
        print_error "docker-compose is not installed"
        missing=1
    fi

    # Check openssl
    if command -v openssl &> /dev/null; then
        print_success "openssl is installed"
    else
        print_warning "openssl is not installed (needed for SSL/TLS)"
    fi

    if [ $missing -eq 1 ]; then
        print_error "Missing required dependencies"
        echo "Please install missing components and try again"
        exit 1
    fi

    echo ""
    print_success "All prerequisites met!"
}

# Welcome screen
show_welcome() {
    clear
    echo -e "${GREEN}"
    cat << "EOF"
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║         ELK Stack Interactive Setup Wizard                    ║
║                                                               ║
║    ElasticSearch + Kibana + Logstash + APISIX + Monitoring   ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    echo ""
    echo "This wizard will guide you through configuring your ELK Stack."
    echo "You can customize all settings or use recommended defaults."
    echo ""
    print_info "Estimated time: 5-10 minutes"
    echo ""

    if ! prompt_yes_no "Ready to begin?" "y"; then
        echo "Setup cancelled."
        exit 0
    fi
}

# Step 1: Basic Configuration
configure_basic_settings() {
    print_header "Step 1: Basic Configuration"

    # Deployment mode
    DEPLOYMENT_MODE=$(prompt_choice "Select deployment mode:" \
        "Development (single node, lower resources)" \
        "Production (optimized, higher resources)" \
        "Testing (minimal resources)")

    # Set defaults based on mode
    case "$DEPLOYMENT_MODE" in
        *Development*)
            ELASTIC_MEMORY="2g"
            LOGSTASH_MEMORY="1g"
            ;;
        *Production*)
            ELASTIC_MEMORY="4g"
            LOGSTASH_MEMORY="2g"
            ;;
        *Testing*)
            ELASTIC_MEMORY="1g"
            LOGSTASH_MEMORY="512m"
            ;;
    esac

    # Environment name
    ENVIRONMENT_NAME=$(prompt_with_default "Environment name (dev/staging/prod)" "dev")

    # Domain/hostname
    print_info "Leave blank to use 'localhost'"
    DOMAIN_NAME=$(prompt_with_default "Domain or hostname" "localhost")

    print_success "Basic configuration complete"
}

# Step 2: Security Configuration
configure_security() {
    print_header "Step 2: Security Configuration"

    echo "The following passwords will be automatically generated:"
    echo "  - ElasticSearch (elastic user)"
    echo "  - Kibana system user"
    echo "  - Logstash authentication"
    echo "  - APM Server secret token"
    echo "  - Grafana admin"
    echo "  - APISIX admin key"
    echo ""

    if prompt_yes_no "Generate secure random passwords?" "y"; then
        ELASTIC_PASSWORD=$(generate_password)
        KIBANA_PASSWORD=$(generate_password)
        LOGSTASH_TOKEN=$(generate_password)
        APM_SECRET_TOKEN=$(generate_password)
        GRAFANA_PASSWORD=$(generate_password)
        APISIX_ADMIN_KEY=$(generate_password)
        KIBANA_ENCRYPTION_KEY=$(openssl rand -hex 32)
        GRAFANA_SECRET_KEY=$(openssl rand -hex 32)

        print_success "Passwords generated successfully"
        print_warning "Passwords will be saved in .env file"
    else
        echo "You can set passwords manually in .env file later"
    fi

    print_success "Security configuration complete"
}

# Step 3: SSL/TLS Configuration
configure_ssl() {
    print_header "Step 3: SSL/TLS Configuration"

    echo "SSL/TLS encrypts communication between clients and the gateway."
    echo ""

    if prompt_yes_no "Enable SSL/TLS (HTTPS)?" "n"; then
        SSL_ENABLED="true"

        SSL_TYPE=$(prompt_choice "Select SSL certificate type:" \
            "Self-signed (for development/testing)" \
            "Let's Encrypt (for production with public domain)" \
            "Custom certificates (I'll provide my own)")

        case "$SSL_TYPE" in
            *Self-signed*)
                print_info "Self-signed certificates will be generated automatically"
                CERT_DAYS=$(prompt_with_default "Certificate validity (days)" "3650")
                ;;
            *Let*)
                if [ "$DOMAIN_NAME" = "localhost" ]; then
                    print_error "Let's Encrypt requires a public domain name"
                    print_info "Falling back to self-signed certificates"
                    SSL_TYPE="Self-signed"
                else
                    LETSENCRYPT_EMAIL=$(prompt_with_default "Email for Let's Encrypt notifications" "admin@$DOMAIN_NAME")
                    if prompt_yes_no "Use Let's Encrypt staging server (for testing)?" "n"; then
                        LETSENCRYPT_STAGING="true"
                    else
                        LETSENCRYPT_STAGING="false"
                    fi
                fi
                ;;
            *Custom*)
                print_info "Place your certificates in:"
                echo "  - certs/apisix/apisix.crt"
                echo "  - certs/apisix/apisix.key"
                echo "  - certs/ca/ca.crt"
                ;;
        esac

        if prompt_yes_no "Force HTTPS (redirect HTTP to HTTPS)?" "y"; then
            FORCE_HTTPS="true"
        else
            FORCE_HTTPS="false"
        fi
    else
        SSL_ENABLED="false"
        print_info "SSL/TLS disabled - using HTTP only"
        print_warning "Not recommended for production deployments"
    fi

    print_success "SSL/TLS configuration complete"
}

# Step 4: Resource Allocation
configure_resources() {
    print_header "Step 4: Resource Allocation"

    echo "Current default memory allocations (based on $DEPLOYMENT_MODE mode):"
    echo "  - ElasticSearch: $ELASTIC_MEMORY"
    echo "  - Logstash: $LOGSTASH_MEMORY"
    echo "  - Kibana: $KIBANA_MEMORY"
    echo ""

    if prompt_yes_no "Customize memory allocations?" "n"; then
        echo ""
        echo "Note: Use format like 1g, 2g, 512m, etc."
        ELASTIC_MEMORY=$(prompt_with_default "ElasticSearch memory (heap size)" "$ELASTIC_MEMORY")
        LOGSTASH_MEMORY=$(prompt_with_default "Logstash memory (heap size)" "$LOGSTASH_MEMORY")

        print_info "Kibana memory is auto-configured"
    fi

    # Prometheus retention
    echo ""
    PROMETHEUS_RETENTION=$(prompt_with_default "Prometheus data retention period" "30d")

    print_success "Resource allocation complete"
}

# Step 5: Service Selection
configure_services() {
    print_header "Step 5: Service Selection"

    echo "Select which optional services to enable:"
    echo ""

    # Monitoring
    if prompt_yes_no "Enable monitoring (Prometheus + Grafana)?" "y"; then
        MONITORING_ENABLED="true"
        print_info "Prometheus and Grafana will be started"

        # ElasticSearch exporter
        if prompt_yes_no "  Enable ElasticSearch metrics exporter?" "y"; then
            ES_EXPORTER_ENABLED="true"
        else
            ES_EXPORTER_ENABLED="false"
        fi
    else
        MONITORING_ENABLED="false"
        ES_EXPORTER_ENABLED="false"
    fi

    echo ""

    # Alerting
    if [ "$MONITORING_ENABLED" = "true" ]; then
        if prompt_yes_no "Enable alerting (Alertmanager)?" "n"; then
            ALERTING_ENABLED="true"
            ALERTMANAGER_EMAIL=$(prompt_with_default "Email for alert notifications" "admin@$DOMAIN_NAME")

            SMTP_HOST=$(prompt_with_default "  SMTP server host" "smtp.gmail.com")
            SMTP_PORT=$(prompt_with_default "  SMTP server port" "587")
            SMTP_FROM=$(prompt_with_default "  From email address" "$ALERTMANAGER_EMAIL")
            SMTP_USERNAME=$(prompt_with_default "  SMTP username" "$ALERTMANAGER_EMAIL")
            read -sp "  SMTP password: " SMTP_PASSWORD
            echo ""
        else
            ALERTING_ENABLED="false"
        fi
    fi

    print_success "Service selection complete"
}

# Step 6: Backup Configuration
configure_backup() {
    print_header "Step 6: Backup Configuration"

    echo "Automatic backups can save ElasticSearch snapshots regularly."
    echo ""

    if prompt_yes_no "Enable automatic backups?" "n"; then
        BACKUP_ENABLED="true"

        BACKUP_TYPE=$(prompt_choice "Select backup type:" \
            "Daily (only today's indices)" \
            "Full (all indices)" \
            "Weekly (all indices, once per week)")

        case "$BACKUP_TYPE" in
            *Daily*)
                BACKUP_INDICES="daily"
                BACKUP_SCHEDULE="0 2 * * *"
                ;;
            *Full*)
                BACKUP_INDICES="all"
                BACKUP_SCHEDULE="0 2 * * *"
                ;;
            *Weekly*)
                BACKUP_INDICES="all"
                BACKUP_SCHEDULE="0 2 * * 0"
                ;;
        esac

        BACKUP_RETENTION_DAYS=$(prompt_with_default "Keep backups for (days)" "30")
        BACKUP_MAX_COUNT=$(prompt_with_default "Maximum number of backups to keep" "30")

        # Backup location
        BACKUP_LOCATION=$(prompt_choice "Backup storage location:" \
            "Local (Docker volume)" \
            "Network share (NFS/CIFS)" \
            "Cloud (S3-compatible)")

        case "$BACKUP_LOCATION" in
            *Network*)
                BACKUP_PATH=$(prompt_with_default "Network share path" "/mnt/backups")
                ;;
            *Cloud*)
                S3_BUCKET=$(prompt_with_default "S3 bucket name" "elk-backups")
                S3_REGION=$(prompt_with_default "S3 region" "us-east-1")
                S3_ACCESS_KEY=$(prompt_with_default "S3 access key" "")
                read -sp "S3 secret key: " S3_SECRET_KEY
                echo ""
                ;;
            *)
                BACKUP_PATH="/mnt/elasticsearch-backups"
                ;;
        esac
    else
        BACKUP_ENABLED="false"
    fi

    print_success "Backup configuration complete"
}

# Step 7: Log Retention
configure_log_retention() {
    print_header "Step 7: Log Retention Policy"

    echo "Configure how long to keep logs in ElasticSearch."
    echo "Older logs will be automatically deleted."
    echo ""

    LOG_RETENTION_DAYS=$(prompt_with_default "Log retention period (days)" "730")
    ROLLOVER_SIZE=$(prompt_with_default "Index rollover size" "1gb")

    print_info "Logs older than $LOG_RETENTION_DAYS days will be automatically deleted"

    print_success "Log retention configuration complete"
}

# Step 8: Network Configuration
configure_network() {
    print_header "Step 8: Network Configuration"

    echo "Configure network settings and external access."
    echo ""

    # Port configuration
    if prompt_yes_no "Customize port mappings?" "n"; then
        APISIX_HTTP_PORT=$(prompt_with_default "APISIX HTTP port" "9080")
        APISIX_HTTPS_PORT=$(prompt_with_default "APISIX HTTPS port" "9443")
        APISIX_DASHBOARD_PORT=$(prompt_with_default "APISIX Dashboard port" "9000")
        APM_PORT=$(prompt_with_default "APM Server port" "8200")
    else
        APISIX_HTTP_PORT="9080"
        APISIX_HTTPS_PORT="9443"
        APISIX_DASHBOARD_PORT="9000"
        APM_PORT="8200"
    fi

    # Logstash external access
    echo ""
    echo "Logstash ports (for external log sources like CloudHub):"
    if prompt_yes_no "Enable external Logstash TCP input (port 5000)?" "n"; then
        LOGSTASH_TCP_EXTERNAL="true"
    else
        LOGSTASH_TCP_EXTERNAL="false"
    fi

    if prompt_yes_no "Enable external Logstash Beats input (port 5044)?" "n"; then
        LOGSTASH_BEATS_EXTERNAL="true"
    else
        LOGSTASH_BEATS_EXTERNAL="false"
    fi

    print_success "Network configuration complete"
}

# Step 9: Review Configuration
review_configuration() {
    print_header "Step 9: Configuration Summary"

    echo "Please review your configuration:"
    echo ""
    echo -e "${BOLD}Basic Settings:${NC}"
    echo "  Deployment Mode: $DEPLOYMENT_MODE"
    echo "  Environment: $ENVIRONMENT_NAME"
    echo "  Domain: $DOMAIN_NAME"
    echo ""

    echo -e "${BOLD}Security:${NC}"
    echo "  SSL/TLS: $SSL_ENABLED"
    if [ "$SSL_ENABLED" = "true" ]; then
        echo "  SSL Type: $SSL_TYPE"
        echo "  Force HTTPS: ${FORCE_HTTPS:-false}"
    fi
    echo "  Passwords: Auto-generated"
    echo ""

    echo -e "${BOLD}Resources:${NC}"
    echo "  ElasticSearch Memory: $ELASTIC_MEMORY"
    echo "  Logstash Memory: $LOGSTASH_MEMORY"
    echo "  Prometheus Retention: $PROMETHEUS_RETENTION"
    echo ""

    echo -e "${BOLD}Services:${NC}"
    echo "  Monitoring: $MONITORING_ENABLED"
    echo "  Alerting: $ALERTING_ENABLED"
    echo "  ElasticSearch Exporter: ${ES_EXPORTER_ENABLED:-false}"
    echo ""

    echo -e "${BOLD}Backup:${NC}"
    echo "  Enabled: $BACKUP_ENABLED"
    if [ "$BACKUP_ENABLED" = "true" ]; then
        echo "  Type: $BACKUP_TYPE"
        echo "  Retention: $BACKUP_RETENTION_DAYS days"
        echo "  Location: $BACKUP_LOCATION"
    fi
    echo ""

    echo -e "${BOLD}Logs:${NC}"
    echo "  Retention: $LOG_RETENTION_DAYS days"
    echo "  Rollover Size: $ROLLOVER_SIZE"
    echo ""

    echo -e "${BOLD}Network:${NC}"
    echo "  APISIX HTTP Port: ${APISIX_HTTP_PORT:-9080}"
    echo "  APISIX HTTPS Port: ${APISIX_HTTPS_PORT:-9443}"
    echo "  External Logstash TCP: ${LOGSTASH_TCP_EXTERNAL:-false}"
    echo "  External Logstash Beats: ${LOGSTASH_BEATS_EXTERNAL:-false}"
    echo ""

    if ! prompt_yes_no "Proceed with this configuration?" "y"; then
        echo ""
        if prompt_yes_no "Start over?" "y"; then
            exec "$0"
        else
            echo "Setup cancelled."
            exit 0
        fi
    fi
}

# Step 10: Apply Configuration
apply_configuration() {
    print_header "Step 10: Applying Configuration"

    # Create .env file
    print_info "Creating .env file..."

    cat > .env << EOF
# ELK Stack Configuration
# Generated by setup wizard on $(date)

# ============================================================================
# Basic Configuration
# ============================================================================
NODE_NAME=elasticsearch
ELASTIC_CLUSTER_NAME=elk-cluster
DISCOVERY_TYPE=single-node
ELASTIC_VERSION=8.11.3
ENVIRONMENT=$ENVIRONMENT_NAME

# ============================================================================
# Security
# ============================================================================
XPACK_SECURITY_ENABLED=true
ELASTIC_PASSWORD=${ELASTIC_PASSWORD:-changeme}
KIBANA_PASSWORD=${KIBANA_PASSWORD:-changeme}
LOGSTASH_AUTH_TOKEN=${LOGSTASH_TOKEN:-changeme}
APM_SECRET_TOKEN=${APM_SECRET_TOKEN:-changeme}
KIBANA_ENCRYPTION_KEY=${KIBANA_ENCRYPTION_KEY:-changeme}
KIBANA_REPORTING_ENCRYPTION_KEY=${KIBANA_ENCRYPTION_KEY:-changeme}

# ============================================================================
# SSL/TLS Configuration
# ============================================================================
SSL_ENABLED=$SSL_ENABLED
SSL_DOMAIN=$DOMAIN_NAME
APISIX_SSL_ENABLED=$SSL_ENABLED
APISIX_FORCE_HTTPS=${FORCE_HTTPS:-false}
APM_SERVER_SSL_ENABLED=$SSL_ENABLED

EOF

    if [ "$SSL_ENABLED" = "true" ] && [ "$SSL_TYPE" = "*Let's Encrypt*" ]; then
        cat >> .env << EOF
LETSENCRYPT_EMAIL=${LETSENCRYPT_EMAIL:-}
LETSENCRYPT_STAGING=${LETSENCRYPT_STAGING:-false}

EOF
    fi

    cat >> .env << EOF
# ============================================================================
# Resource Allocation
# ============================================================================
ES_JAVA_OPTS=-Xms${ELASTIC_MEMORY} -Xmx${ELASTIC_MEMORY}
LS_JAVA_OPTS=-Xms${LOGSTASH_MEMORY} -Xmx${LOGSTASH_MEMORY}
PROMETHEUS_RETENTION=${PROMETHEUS_RETENTION}

# ============================================================================
# APISIX Configuration
# ============================================================================
APISIX_ADMIN_KEY=${APISIX_ADMIN_KEY:-edd1c9f034335f136f87ad84b625c8f1}

# ============================================================================
# Grafana Configuration
# ============================================================================
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
GRAFANA_SECRET_KEY=${GRAFANA_SECRET_KEY:-changeme}

# ============================================================================
# Backup Configuration
# ============================================================================
BACKUP_ENABLED=$BACKUP_ENABLED
BACKUP_INDICES=${BACKUP_INDICES:-daily}
BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-30}
BACKUP_MAX_COUNT=${BACKUP_MAX_COUNT:-30}
SNAPSHOT_REPOSITORY_PATH=${BACKUP_PATH:-/mnt/elasticsearch-backups}

EOF

    if [ "$BACKUP_LOCATION" = "*Cloud*" ]; then
        cat >> .env << EOF
S3_BUCKET=${S3_BUCKET:-}
S3_REGION=${S3_REGION:-us-east-1}
S3_ACCESS_KEY=${S3_ACCESS_KEY:-}
S3_SECRET_KEY=${S3_SECRET_KEY:-}

EOF
    fi

    cat >> .env << EOF
# ============================================================================
# Monitoring Configuration
# ============================================================================
MONITORING_ENABLED=$MONITORING_ENABLED

# ============================================================================
# Alerting Configuration
# ============================================================================
ALERTING_ENABLED=$ALERTING_ENABLED

EOF

    if [ "$ALERTING_ENABLED" = "true" ]; then
        cat >> .env << EOF
ALERTMANAGER_EMAIL=${ALERTMANAGER_EMAIL:-}
SMTP_HOST=${SMTP_HOST:-smtp.gmail.com}
SMTP_PORT=${SMTP_PORT:-587}
SMTP_FROM=${SMTP_FROM:-}
SMTP_USERNAME=${SMTP_USERNAME:-}
SMTP_PASSWORD=${SMTP_PASSWORD:-}

EOF
    fi

    cat >> .env << EOF
# ============================================================================
# Log Retention
# ============================================================================
MULE_LOGS_RETENTION_DAYS=${LOG_RETENTION_DAYS}
LOGSTASH_LOGS_RETENTION_DAYS=${LOG_RETENTION_DAYS}
ROLLOVER_SIZE=${ROLLOVER_SIZE}

# ============================================================================
# Network Configuration
# ============================================================================
# Port mappings handled in docker-compose.yml
# External Logstash access configured below

EOF

    print_success ".env file created"

    # Modify docker-compose.yml for external Logstash ports if needed
    if [ "$LOGSTASH_TCP_EXTERNAL" = "true" ] || [ "$LOGSTASH_BEATS_EXTERNAL" = "true" ]; then
        print_info "Configuring external Logstash access..."
        # This would require modifying docker-compose.yml
        # For now, just note it
        print_warning "Please uncomment Logstash ports in docker-compose.yml manually"
    fi

    # Generate SSL certificates if needed
    if [ "$SSL_ENABLED" = "true" ]; then
        case "$SSL_TYPE" in
            *Self-signed*)
                print_info "Generating self-signed certificates..."
                if [ -f "config/scripts/setup/generate-certs.sh" ]; then
                    chmod +x config/scripts/setup/generate-certs.sh
                    ./config/scripts/setup/generate-certs.sh --domain "$DOMAIN_NAME" --days "${CERT_DAYS:-3650}"
                    print_success "Certificates generated"
                else
                    print_error "Certificate generation script not found"
                fi
                ;;
            *Let*)
                print_info "Let's Encrypt certificates will be obtained on first start"
                print_warning "Make sure DNS points to this server and port 80/443 are accessible"
                ;;
        esac
    fi

    # Create networks
    print_info "Creating Docker networks..."
    docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet 2>/dev/null || print_info "Network ce-base-micronet already exists"
    docker network create ce-base-network 2>/dev/null || print_info "Network ce-base-network already exists"
    print_success "Networks ready"

    # Configure log retention
    print_info "Configuring log retention policies..."
    export MULE_LOGS_RETENTION_DAYS=${LOG_RETENTION_DAYS}
    export LOGSTASH_LOGS_RETENTION_DAYS=${LOG_RETENTION_DAYS}
    export ROLLOVER_SIZE=${ROLLOVER_SIZE}

    # Configure backup if enabled
    if [ "$BACKUP_ENABLED" = "true" ]; then
        print_info "Configuring backup system..."
        if [ -f "config/scripts/backup/configure-backup.sh" ]; then
            chmod +x config/scripts/backup/configure-backup.sh
            # ./config/scripts/backup/configure-backup.sh
            print_info "Backup configuration ready (will be applied on first start)"
        fi
    fi

    # Configure alerting if enabled
    if [ "$ALERTING_ENABLED" = "true" ]; then
        print_info "Configuring alerting..."
        # Update alertmanager config
        if [ -f "config/alertmanager/alertmanager.yml.template" ]; then
            sed "s/ALERTMANAGER_EMAIL/${ALERTMANAGER_EMAIL}/g; \
                 s/SMTP_HOST/${SMTP_HOST}/g; \
                 s/SMTP_PORT/${SMTP_PORT}/g; \
                 s/SMTP_FROM/${SMTP_FROM}/g; \
                 s/SMTP_USERNAME/${SMTP_USERNAME}/g; \
                 s/SMTP_PASSWORD/${SMTP_PASSWORD}/g" \
                config/alertmanager/alertmanager.yml.template > config/alertmanager/alertmanager.yml
            print_success "Alerting configured"
        fi
    fi

    print_success "Configuration applied successfully"
}

# Step 11: Start Services
start_services() {
    print_header "Step 11: Starting Services"

    echo "Ready to start the ELK Stack."
    echo ""

    if prompt_yes_no "Start services now?" "y"; then
        print_info "Starting services..."
        echo ""

        # Determine which compose files to use
        COMPOSE_FILES="-f docker-compose.yml"

        if [ "$SSL_ENABLED" = "true" ]; then
            COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.ssl.yml"
        fi

        # Set profiles
        PROFILES=""
        if [ "$ALERTING_ENABLED" = "true" ]; then
            PROFILES="--profile alerting"
        fi
        if [ "$ES_EXPORTER_ENABLED" = "true" ]; then
            PROFILES="$PROFILES --profile elasticsearch-monitoring"
        fi

        # Start services
        docker-compose $COMPOSE_FILES up -d $PROFILES

        echo ""
        print_success "Services started!"
        print_info "Waiting for services to become healthy (this may take 2-3 minutes)..."
        echo ""

        # Wait a bit
        sleep 5

        # Show status
        docker-compose ps

    else
        print_info "Services not started"
        echo ""
        echo "To start services later, run:"
        if [ "$SSL_ENABLED" = "true" ]; then
            echo "  docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d"
        else
            echo "  docker-compose up -d"
        fi
    fi
}

# Final summary
show_summary() {
    print_header "Setup Complete!"

    echo -e "${GREEN}Your ELK Stack has been configured successfully!${NC}"
    echo ""

    echo -e "${BOLD}Access your services:${NC}"

    if [ "$SSL_ENABLED" = "true" ]; then
        echo "  • Kibana:           https://$DOMAIN_NAME:${APISIX_HTTPS_PORT:-9443}/kibana"
        echo "  • APISIX Dashboard: https://$DOMAIN_NAME:${APISIX_DASHBOARD_PORT:-9000}"
        echo "  • Grafana:          https://$DOMAIN_NAME:${APISIX_HTTPS_PORT:-9443}/grafana"
        echo "  • Prometheus:       https://$DOMAIN_NAME:${APISIX_HTTPS_PORT:-9443}/prometheus"
    else
        echo "  • Kibana:           http://$DOMAIN_NAME:${APISIX_HTTP_PORT:-9080}/kibana"
        echo "  • APISIX Dashboard: http://$DOMAIN_NAME:${APISIX_DASHBOARD_PORT:-9000}"
        echo "  • Grafana:          http://$DOMAIN_NAME:${APISIX_HTTP_PORT:-9080}/grafana"
        echo "  • Prometheus:       http://$DOMAIN_NAME:${APISIX_HTTP_PORT:-9080}/prometheus"
    fi
    echo ""

    echo -e "${BOLD}Login Credentials:${NC}"
    echo "  • Kibana:     elastic / (see .env file for ELASTIC_PASSWORD)"
    echo "  • Grafana:    admin / (see .env file for GRAFANA_ADMIN_PASSWORD)"
    echo "  • APISIX:     admin / admin"
    echo ""

    echo -e "${BOLD}Important Files:${NC}"
    echo "  • Configuration: .env"
    echo "  • Passwords: .env (keep secure!)"
    if [ "$SSL_ENABLED" = "true" ]; then
        echo "  • SSL Certificates: certs/"
    fi
    echo ""

    echo -e "${BOLD}Useful Commands:${NC}"
    echo "  • Check status:  docker-compose ps"
    echo "  • View logs:     docker-compose logs -f"
    echo "  • Stop services: docker-compose down"
    echo "  • Restart:       docker-compose restart"
    echo ""

    if [ "$BACKUP_ENABLED" = "true" ]; then
        echo -e "${BOLD}Backups:${NC}"
        echo "  • Configured: $BACKUP_TYPE backups"
        echo "  • Retention: $BACKUP_RETENTION_DAYS days"
        echo "  • Manual backup: ./config/scripts/backup/backup.sh"
        echo ""
    fi

    print_info "For detailed documentation, see README.md and docs/"
    echo ""

    print_success "Happy logging! 📊"
}

# Main execution
main() {
    show_welcome
    check_prerequisites
    configure_basic_settings
    configure_security
    configure_ssl
    configure_resources
    configure_services
    configure_backup
    configure_log_retention
    configure_network
    review_configuration
    apply_configuration
    start_services
    show_summary
}

# Run main function
main

exit 0
