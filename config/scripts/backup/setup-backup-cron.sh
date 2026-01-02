#!/bin/bash
#
# Setup Automated Backup Cron Jobs
#
# This script sets up cron jobs for automated ElasticSearch backups based on
# the schedule defined in .env file.
#
# Usage:
#   ./config/backup/setup-backup-cron.sh
#
# Options:
#   --remove    Remove existing backup cron jobs
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
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# Parse arguments
REMOVE=false

for arg in "$@"; do
    case $arg in
        --remove)
            REMOVE=true
            shift
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--remove]"
            exit 1
            ;;
    esac
done

# Load environment variables from .env
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: .env file not found at $ENV_FILE${NC}"
    exit 1
fi

# Source the .env file
set -a
source "$ENV_FILE"
set +a

# Print banner
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Setup Automated ElasticSearch Backups${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Check if running as root (required for system-wide cron)
if [ "$EUID" -eq 0 ]; then
    CRON_USER="${SUDO_USER:-root}"
    echo -e "${YELLOW}Running as root - will install system-wide cron jobs${NC}"
else
    CRON_USER="$USER"
    echo -e "${YELLOW}Running as user - will install user cron jobs${NC}"
fi
echo ""

# Backup settings
BACKUP_ENABLED="${BACKUP_ENABLED:-true}"
SCHEDULE="${BACKUP_SCHEDULE:-0 2 * * *}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

# Cron job identifiers (for easy removal)
BACKUP_MARKER="# ElasticSearch Backup - Managed by setup-backup-cron.sh"
CLEANUP_MARKER="# ElasticSearch Cleanup - Managed by setup-backup-cron.sh"

# Remove existing cron jobs if requested
if [ "$REMOVE" = true ]; then
    echo -e "${GREEN}Removing existing backup cron jobs...${NC}"

    # Get current crontab
    CURRENT_CRON=$(crontab -l 2>/dev/null || true)

    # Remove lines with our markers
    NEW_CRON=$(echo "$CURRENT_CRON" | grep -v "$BACKUP_MARKER" | grep -v "$CLEANUP_MARKER" || true)

    # Update crontab
    if [ -z "$NEW_CRON" ]; then
        # No cron jobs left, remove crontab
        crontab -r 2>/dev/null || true
    else
        echo "$NEW_CRON" | crontab -
    fi

    echo -e "${GREEN}✓ Backup cron jobs removed${NC}"
    exit 0
fi

# Check if backups are enabled
if [ "$BACKUP_ENABLED" != "true" ]; then
    echo -e "${YELLOW}Warning: Backups are disabled in .env (BACKUP_ENABLED=false)${NC}"
    read -p "Do you want to continue anyway? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Setup cancelled."
        exit 0
    fi
fi

# Display configuration
echo -e "${YELLOW}Backup Configuration:${NC}"
echo "  Enabled: ${BACKUP_ENABLED}"
echo "  Schedule: ${SCHEDULE}"
echo "  Retention: ${RETENTION_DAYS} days"
echo "  Project: ${PROJECT_ROOT}"
echo ""

# Validate cron schedule
if ! echo "$SCHEDULE" | grep -qE '^[0-9*,/-]+ [0-9*,/-]+ [0-9*,/-]+ [0-9*,/-]+ [0-9*,/-]+'; then
    echo -e "${RED}Error: Invalid cron schedule: ${SCHEDULE}${NC}"
    echo ""
    echo "Valid cron format: minute hour day month weekday"
    echo "Examples:"
    echo "  0 2 * * *       = Daily at 2:00 AM"
    echo "  0 */6 * * *     = Every 6 hours"
    echo "  0 0 * * 0       = Weekly on Sunday at midnight"
    exit 1
fi

# Create log directory
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "$LOG_DIR"

# Backup script path
BACKUP_SCRIPT="${SCRIPT_DIR}/backup.sh"
CLEANUP_SCRIPT="${SCRIPT_DIR}/backup-cleanup.sh"

# Check if scripts exist
if [ ! -f "$BACKUP_SCRIPT" ]; then
    echo -e "${RED}Error: Backup script not found at ${BACKUP_SCRIPT}${NC}"
    exit 1
fi

if [ ! -f "$CLEANUP_SCRIPT" ]; then
    echo -e "${RED}Error: Cleanup script not found at ${CLEANUP_SCRIPT}${NC}"
    exit 1
fi

# Make scripts executable
chmod +x "$BACKUP_SCRIPT"
chmod +x "$CLEANUP_SCRIPT"

# Get current crontab
CURRENT_CRON=$(crontab -l 2>/dev/null || true)

# Remove existing backup cron jobs (if any)
NEW_CRON=$(echo "$CURRENT_CRON" | grep -v "$BACKUP_MARKER" | grep -v "$CLEANUP_MARKER" || true)

# Add new cron jobs
echo -e "${GREEN}Adding cron jobs...${NC}"
echo ""

# Backup cron job
BACKUP_CRON="${SCHEDULE} ${BACKUP_SCRIPT} >> ${LOG_DIR}/backup.log 2>&1 ${BACKUP_MARKER}"
echo -e "${BLUE}Backup Job:${NC}"
echo "  Schedule: ${SCHEDULE}"
echo "  Script: ${BACKUP_SCRIPT}"
echo "  Log: ${LOG_DIR}/backup.log"
echo ""

# Cleanup cron job (daily at 3 AM)
CLEANUP_SCHEDULE="0 3 * * *"
CLEANUP_CRON="${CLEANUP_SCHEDULE} ${CLEANUP_SCRIPT} >> ${LOG_DIR}/cleanup.log 2>&1 ${CLEANUP_MARKER}"
echo -e "${BLUE}Cleanup Job:${NC}"
echo "  Schedule: ${CLEANUP_SCHEDULE} (daily at 3:00 AM)"
echo "  Script: ${CLEANUP_SCRIPT}"
echo "  Log: ${LOG_DIR}/cleanup.log"
echo ""

# Combine cron jobs
if [ -n "$NEW_CRON" ]; then
    FINAL_CRON="${NEW_CRON}\n${BACKUP_CRON}\n${CLEANUP_CRON}"
else
    FINAL_CRON="${BACKUP_CRON}\n${CLEANUP_CRON}"
fi

# Install crontab
echo -e "$FINAL_CRON" | crontab -

echo -e "${GREEN}✓ Cron jobs installed successfully${NC}"
echo ""

# Display installed cron jobs
echo -e "${YELLOW}Installed cron jobs:${NC}"
crontab -l | grep -A 1 "$BACKUP_MARKER" | grep -v "^--$"
crontab -l | grep -A 1 "$CLEANUP_MARKER" | grep -v "^--$"
echo ""

# Test backup script
echo -e "${YELLOW}Testing backup script execution...${NC}"
if bash -n "$BACKUP_SCRIPT"; then
    echo -e "${GREEN}✓ Backup script syntax is valid${NC}"
else
    echo -e "${RED}✗ Backup script has syntax errors${NC}"
    exit 1
fi
echo ""

# Display next run time
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Setup Complete${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Automated backups are now configured!"
echo ""
echo "Next backup: $(date -d "$(echo "$SCHEDULE" | awk '{print $2":"$1}')" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "Check cron schedule")"
echo ""
echo -e "${YELLOW}Useful Commands:${NC}"
echo ""
echo "  View cron jobs:"
echo "    ${BLUE}crontab -l${NC}"
echo ""
echo "  View backup logs:"
echo "    ${BLUE}tail -f ${LOG_DIR}/backup.log${NC}"
echo ""
echo "  View cleanup logs:"
echo "    ${BLUE}tail -f ${LOG_DIR}/cleanup.log${NC}"
echo ""
echo "  Remove cron jobs:"
echo "    ${BLUE}$0 --remove${NC}"
echo ""
echo "  Run backup manually:"
echo "    ${BLUE}${BACKUP_SCRIPT}${NC}"
echo ""
echo "  Run cleanup manually:"
echo "    ${BLUE}${CLEANUP_SCRIPT}${NC}"
echo ""
