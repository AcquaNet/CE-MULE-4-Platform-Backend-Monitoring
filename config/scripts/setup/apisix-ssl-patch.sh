#!/bin/sh
# APISIX SSL Patch Script
# This script patches the APISIX nginx.conf to enable SSL on port 9443
# Run this inside the APISIX container as part of healthcheck

NGINX_CONF="/usr/local/apisix/conf/nginx.conf"

# Check if nginx.conf exists
if [ ! -f "$NGINX_CONF" ]; then
    # Config not generated yet, skip silently
    exit 0
fi

# Check if SSL is already enabled
if grep -q "listen 0\.0\.0\.0:9443 ssl" "$NGINX_CONF"; then
    # Already patched, nothing to do
    exit 0
fi

# Check if the line needing patch exists
if ! grep -q "listen 0\.0\.0\.0:9443 default_server http2" "$NGINX_CONF"; then
    # Line not found, skip silently
    exit 0
fi

# Apply the SSL patch
LINE_NUM=$(grep -n "listen 0\.0\.0\.0:9443 default_server http2" "$NGINX_CONF" | cut -d: -f1 | head -1)
if [ -n "$LINE_NUM" ]; then
    sed -i "${LINE_NUM}s/.*/        listen 0.0.0.0:9443 ssl http2;/" "$NGINX_CONF"

    # Reload nginx if PID file exists
    if [ -f "/usr/local/apisix/logs/nginx.pid" ]; then
        kill -HUP $(cat /usr/local/apisix/logs/nginx.pid) 2>/dev/null || true
    fi
fi

exit 0
