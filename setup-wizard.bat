@echo off
REM ELK Stack - Interactive Setup Wizard (Windows)
REM
REM This wizard guides you through complete configuration of the ELK Stack
REM

setlocal enabledelayedexpansion

REM Configuration variables
set "DEPLOYMENT_MODE="
set "ENVIRONMENT_NAME=dev"
set "DOMAIN_NAME=localhost"
set "SSL_ENABLED=false"
set "ELASTIC_MEMORY=2g"
set "LOGSTASH_MEMORY=1g"
set "PROMETHEUS_RETENTION=30d"
set "BACKUP_ENABLED=false"
set "ALERTING_ENABLED=false"
set "LOG_RETENTION_DAYS=730"
set "MONITORING_ENABLED=true"

cls
echo.
echo ===============================================================
echo.
echo         ELK Stack Interactive Setup Wizard
echo.
echo    ElasticSearch + Kibana + Logstash + APISIX + Monitoring
echo.
echo ===============================================================
echo.
echo This wizard will guide you through configuring your ELK Stack.
echo You can customize all settings or use recommended defaults.
echo.
echo Estimated time: 5-10 minutes
echo.

set /p "START=Ready to begin? (Y/n): "
if /i "!START!"=="n" (
    echo Setup cancelled.
    exit /b 0
)

REM Check prerequisites
echo.
echo ========================================
echo Checking Prerequisites
echo ========================================
echo.

docker ps >nul 2>&1
if errorlevel 1 (
    echo [X] Docker is not running
    echo Please start Docker Desktop and try again
    pause
    exit /b 1
)
echo [OK] Docker is running

docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo [X] docker-compose is not installed
    pause
    exit /b 1
)
echo [OK] docker-compose is installed

echo.
echo All prerequisites met!
pause

REM Step 1: Basic Configuration
cls
echo.
echo ========================================
echo Step 1: Basic Configuration
echo ========================================
echo.

echo Select deployment mode:
echo   1. Development (single node, lower resources)
echo   2. Production (optimized, higher resources)
echo   3. Testing (minimal resources)
echo.
set /p "MODE_CHOICE=Enter choice [1-3]: "

if "!MODE_CHOICE!"=="1" (
    set "DEPLOYMENT_MODE=Development"
    set "ELASTIC_MEMORY=2g"
    set "LOGSTASH_MEMORY=1g"
) else if "!MODE_CHOICE!"=="2" (
    set "DEPLOYMENT_MODE=Production"
    set "ELASTIC_MEMORY=4g"
    set "LOGSTASH_MEMORY=2g"
) else (
    set "DEPLOYMENT_MODE=Testing"
    set "ELASTIC_MEMORY=1g"
    set "LOGSTASH_MEMORY=512m"
)

echo.
set /p "ENV_NAME=Environment name (dev/staging/prod) [dev]: "
if not "!ENV_NAME!"=="" set "ENVIRONMENT_NAME=!ENV_NAME!"

echo.
set /p "DOMAIN=Domain or hostname [localhost]: "
if not "!DOMAIN!"=="" set "DOMAIN_NAME=!DOMAIN!"

echo.
echo [OK] Basic configuration complete
pause

REM Step 2: Security Configuration
cls
echo.
echo ========================================
echo Step 2: Security Configuration
echo ========================================
echo.

echo The following passwords will be automatically generated:
echo   - ElasticSearch (elastic user)
echo   - Kibana system user
echo   - Logstash authentication
echo   - APM Server secret token
echo   - Grafana admin
echo   - APISIX admin key
echo.

set /p "GEN_PASS=Generate secure random passwords? (Y/n): "
if /i not "!GEN_PASS!"=="n" (
    echo Generating passwords...

    REM Generate random passwords (simplified for Windows)
    for /f %%i in ('powershell -command "[guid]::NewGuid().ToString('N').Substring(0,25)"') do set "ELASTIC_PASSWORD=%%i"
    for /f %%i in ('powershell -command "[guid]::NewGuid().ToString('N').Substring(0,25)"') do set "KIBANA_PASSWORD=%%i"
    for /f %%i in ('powershell -command "[guid]::NewGuid().ToString('N').Substring(0,25)"') do set "LOGSTASH_TOKEN=%%i"
    for /f %%i in ('powershell -command "[guid]::NewGuid().ToString('N').Substring(0,25)"') do set "APM_SECRET_TOKEN=%%i"
    for /f %%i in ('powershell -command "[guid]::NewGuid().ToString('N').Substring(0,25)"') do set "GRAFANA_PASSWORD=%%i"
    for /f %%i in ('powershell -command "[guid]::NewGuid().ToString('N').Substring(0,64)"') do set "KIBANA_ENCRYPTION_KEY=%%i"
    for /f %%i in ('powershell -command "[guid]::NewGuid().ToString('N').Substring(0,64)"') do set "GRAFANA_SECRET_KEY=%%i"
    set "APISIX_ADMIN_KEY=!ELASTIC_PASSWORD!"

    echo [OK] Passwords generated
    echo [!] Passwords will be saved in .env file
)

echo.
echo [OK] Security configuration complete
pause

REM Step 3: SSL/TLS Configuration
cls
echo.
echo ========================================
echo Step 3: SSL/TLS Configuration
echo ========================================
echo.

echo SSL/TLS encrypts communication between clients and the gateway.
echo.

set /p "ENABLE_SSL=Enable SSL/TLS (HTTPS)? (y/N): "
if /i "!ENABLE_SSL!"=="y" (
    set "SSL_ENABLED=true"

    echo.
    echo Select SSL certificate type:
    echo   1. Self-signed (for development/testing)
    echo   2. Let's Encrypt (for production with public domain)
    echo   3. Custom certificates (I'll provide my own)
    echo.
    set /p "SSL_CHOICE=Enter choice [1-3]: "

    if "!SSL_CHOICE!"=="1" (
        set "SSL_TYPE=Self-signed"
        set /p "CERT_DAYS=Certificate validity (days) [3650]: "
        if "!CERT_DAYS!"=="" set "CERT_DAYS=3650"
    ) else if "!SSL_CHOICE!"=="2" (
        if "!DOMAIN_NAME!"=="localhost" (
            echo [!] Let's Encrypt requires a public domain name
            echo [!] Falling back to self-signed certificates
            set "SSL_TYPE=Self-signed"
        ) else (
            set "SSL_TYPE=LetsEncrypt"
            set /p "LE_EMAIL=Email for Let's Encrypt [admin@!DOMAIN_NAME!]: "
            if "!LE_EMAIL!"=="" set "LE_EMAIL=admin@!DOMAIN_NAME!"
        )
    ) else (
        set "SSL_TYPE=Custom"
        echo [i] Place your certificates in:
        echo     - certs/apisix/apisix.crt
        echo     - certs/apisix/apisix.key
        echo     - certs/ca/ca.crt
    )

    echo.
    set /p "FORCE_HTTPS=Force HTTPS (redirect HTTP to HTTPS)? (Y/n): "
    if /i not "!FORCE_HTTPS!"=="n" set "FORCE_HTTPS_ENABLED=true"
) else (
    set "SSL_ENABLED=false"
    echo [i] SSL/TLS disabled - using HTTP only
    echo [!] Not recommended for production deployments
)

echo.
echo [OK] SSL/TLS configuration complete
pause

REM Step 4: Resource Allocation
cls
echo.
echo ========================================
echo Step 4: Resource Allocation
echo ========================================
echo.

echo Current default memory allocations (based on !DEPLOYMENT_MODE! mode):
echo   - ElasticSearch: !ELASTIC_MEMORY!
echo   - Logstash: !LOGSTASH_MEMORY!
echo.

set /p "CUSTOM_MEM=Customize memory allocations? (y/N): "
if /i "!CUSTOM_MEM!"=="y" (
    echo.
    echo Note: Use format like 1g, 2g, 512m, etc.
    set /p "ES_MEM=ElasticSearch memory (heap size) [!ELASTIC_MEMORY!]: "
    if not "!ES_MEM!"=="" set "ELASTIC_MEMORY=!ES_MEM!"

    set /p "LS_MEM=Logstash memory (heap size) [!LOGSTASH_MEMORY!]: "
    if not "!LS_MEM!"=="" set "LOGSTASH_MEMORY=!LS_MEM!"
)

echo.
set /p "PROM_RET=Prometheus data retention period [30d]: "
if not "!PROM_RET!"=="" set "PROMETHEUS_RETENTION=!PROM_RET!"

echo.
echo [OK] Resource allocation complete
pause

REM Step 5: Service Selection
cls
echo.
echo ========================================
echo Step 5: Service Selection
echo ========================================
echo.

echo Select which optional services to enable:
echo.

set /p "ENABLE_MON=Enable monitoring (Prometheus + Grafana)? (Y/n): "
if /i not "!ENABLE_MON!"=="n" (
    set "MONITORING_ENABLED=true"
    echo [i] Prometheus and Grafana will be started

    set /p "ENABLE_ES_EXP=  Enable ElasticSearch metrics exporter? (Y/n): "
    if /i not "!ENABLE_ES_EXP!"=="n" (
        set "ES_EXPORTER_ENABLED=true"
    )
) else (
    set "MONITORING_ENABLED=false"
)

echo.
if "!MONITORING_ENABLED!"=="true" (
    set /p "ENABLE_ALERT=Enable alerting (Alertmanager)? (y/N): "
    if /i "!ENABLE_ALERT!"=="y" (
        set "ALERTING_ENABLED=true"
        set /p "ALERT_EMAIL=Email for alert notifications [admin@!DOMAIN_NAME!]: "
        if "!ALERT_EMAIL!"=="" set "ALERT_EMAIL=admin@!DOMAIN_NAME!"
    )
)

echo.
echo [OK] Service selection complete
pause

REM Step 6: Backup Configuration
cls
echo.
echo ========================================
echo Step 6: Backup Configuration
echo ========================================
echo.

echo Automatic backups can save ElasticSearch snapshots regularly.
echo.

set /p "ENABLE_BACKUP=Enable automatic backups? (y/N): "
if /i "!ENABLE_BACKUP!"=="y" (
    set "BACKUP_ENABLED=true"

    echo.
    echo Select backup type:
    echo   1. Daily (only today's indices)
    echo   2. Full (all indices)
    echo   3. Weekly (all indices, once per week)
    echo.
    set /p "BACKUP_CHOICE=Enter choice [1-3]: "

    if "!BACKUP_CHOICE!"=="1" set "BACKUP_INDICES=daily"
    if "!BACKUP_CHOICE!"=="2" set "BACKUP_INDICES=all"
    if "!BACKUP_CHOICE!"=="3" set "BACKUP_INDICES=all"

    echo.
    set /p "BACKUP_RET=Keep backups for (days) [30]: "
    if "!BACKUP_RET!"=="" set "BACKUP_RET=30"
    set "BACKUP_RETENTION_DAYS=!BACKUP_RET!"
)

echo.
echo [OK] Backup configuration complete
pause

REM Step 7: Log Retention
cls
echo.
echo ========================================
echo Step 7: Log Retention Policy
echo ========================================
echo.

echo Configure how long to keep logs in ElasticSearch.
echo Older logs will be automatically deleted.
echo.

set /p "LOG_RET=Log retention period (days) [730]: "
if "!LOG_RET!"=="" set "LOG_RET=730"
set "LOG_RETENTION_DAYS=!LOG_RET!"

set /p "ROLLOVER=Index rollover size [1gb]: "
if "!ROLLOVER!"=="" set "ROLLOVER=1gb"
set "ROLLOVER_SIZE=!ROLLOVER!"

echo.
echo [i] Logs older than !LOG_RETENTION_DAYS! days will be automatically deleted
echo.
echo [OK] Log retention configuration complete
pause

REM Step 8: Review Configuration
cls
echo.
echo ========================================
echo Configuration Summary
echo ========================================
echo.

echo Please review your configuration:
echo.
echo Basic Settings:
echo   Deployment Mode: !DEPLOYMENT_MODE!
echo   Environment: !ENVIRONMENT_NAME!
echo   Domain: !DOMAIN_NAME!
echo.
echo Security:
echo   SSL/TLS: !SSL_ENABLED!
if "!SSL_ENABLED!"=="true" (
    echo   SSL Type: !SSL_TYPE!
)
echo   Passwords: Auto-generated
echo.
echo Resources:
echo   ElasticSearch Memory: !ELASTIC_MEMORY!
echo   Logstash Memory: !LOGSTASH_MEMORY!
echo   Prometheus Retention: !PROMETHEUS_RETENTION!
echo.
echo Services:
echo   Monitoring: !MONITORING_ENABLED!
echo   Alerting: !ALERTING_ENABLED!
echo.
echo Backup:
echo   Enabled: !BACKUP_ENABLED!
echo.
echo Logs:
echo   Retention: !LOG_RETENTION_DAYS! days
echo   Rollover Size: !ROLLOVER_SIZE!
echo.

set /p "PROCEED=Proceed with this configuration? (Y/n): "
if /i "!PROCEED!"=="n" (
    echo.
    echo Setup cancelled.
    pause
    exit /b 0
)

REM Step 9: Apply Configuration
cls
echo.
echo ========================================
echo Applying Configuration
echo ========================================
echo.

echo Creating .env file...

(
echo # ELK Stack Configuration
echo # Generated by setup wizard on %DATE% %TIME%
echo.
echo # Basic Configuration
echo NODE_NAME=elasticsearch
echo ELASTIC_CLUSTER_NAME=elk-cluster
echo DISCOVERY_TYPE=single-node
echo ELASTIC_VERSION=8.11.3
echo ENVIRONMENT=!ENVIRONMENT_NAME!
echo.
echo # Security
echo XPACK_SECURITY_ENABLED=true
echo ELASTIC_PASSWORD=!ELASTIC_PASSWORD!
echo KIBANA_PASSWORD=!KIBANA_PASSWORD!
echo LOGSTASH_AUTH_TOKEN=!LOGSTASH_TOKEN!
echo APM_SECRET_TOKEN=!APM_SECRET_TOKEN!
echo KIBANA_ENCRYPTION_KEY=!KIBANA_ENCRYPTION_KEY!
echo KIBANA_REPORTING_ENCRYPTION_KEY=!KIBANA_ENCRYPTION_KEY!
echo.
echo # SSL/TLS Configuration
echo SSL_ENABLED=!SSL_ENABLED!
echo SSL_DOMAIN=!DOMAIN_NAME!
echo APISIX_SSL_ENABLED=!SSL_ENABLED!
echo APISIX_FORCE_HTTPS=!FORCE_HTTPS_ENABLED!
echo APM_SERVER_SSL_ENABLED=!SSL_ENABLED!
echo.
echo # Resource Allocation
echo ES_JAVA_OPTS=-Xms!ELASTIC_MEMORY! -Xmx!ELASTIC_MEMORY!
echo LS_JAVA_OPTS=-Xms!LOGSTASH_MEMORY! -Xmx!LOGSTASH_MEMORY!
echo PROMETHEUS_RETENTION=!PROMETHEUS_RETENTION!
echo.
echo # APISIX Configuration
echo APISIX_ADMIN_KEY=!APISIX_ADMIN_KEY!
echo.
echo # Grafana Configuration
echo GRAFANA_ADMIN_USER=admin
echo GRAFANA_ADMIN_PASSWORD=!GRAFANA_PASSWORD!
echo GRAFANA_SECRET_KEY=!GRAFANA_SECRET_KEY!
echo.
echo # Backup Configuration
echo BACKUP_ENABLED=!BACKUP_ENABLED!
echo BACKUP_INDICES=!BACKUP_INDICES!
echo BACKUP_RETENTION_DAYS=!BACKUP_RETENTION_DAYS!
echo SNAPSHOT_REPOSITORY_PATH=/mnt/elasticsearch-backups
echo.
echo # Monitoring Configuration
echo MONITORING_ENABLED=!MONITORING_ENABLED!
echo.
echo # Alerting Configuration
echo ALERTING_ENABLED=!ALERTING_ENABLED!
echo.
echo # Log Retention
echo MULE_LOGS_RETENTION_DAYS=!LOG_RETENTION_DAYS!
echo LOGSTASH_LOGS_RETENTION_DAYS=!LOG_RETENTION_DAYS!
echo ROLLOVER_SIZE=!ROLLOVER_SIZE!
) > .env

echo [OK] .env file created

REM Generate SSL certificates if needed
if "!SSL_ENABLED!"=="true" (
    if "!SSL_TYPE!"=="Self-signed" (
        echo.
        echo Generating self-signed certificates...
        if exist "config\scripts\setup\generate-certs.sh" (
            bash config/scripts/setup/generate-certs.sh --domain !DOMAIN_NAME! --days !CERT_DAYS!
            echo [OK] Certificates generated
        ) else (
            echo [!] Certificate generation script not found
            echo [i] You can generate certificates manually later
        )
    )
)

REM Create networks
echo.
echo Creating Docker networks...
docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet 2>nul
docker network create ce-base-network 2>nul
echo [OK] Networks ready

echo.
echo [OK] Configuration applied successfully
pause

REM Step 10: Start Services
cls
echo.
echo ========================================
echo Starting Services
echo ========================================
echo.

echo Ready to start the ELK Stack.
echo.

set /p "START_NOW=Start services now? (Y/n): "
if /i not "!START_NOW!"=="n" (
    echo.
    echo Starting services...
    echo.

    set "COMPOSE_CMD=docker-compose -f docker-compose.yml"
    if "!SSL_ENABLED!"=="true" set "COMPOSE_CMD=!COMPOSE_CMD! -f docker-compose.ssl.yml"

    !COMPOSE_CMD! up -d

    echo.
    echo [OK] Services started!
    echo [i] Waiting for services to become healthy (this may take 2-3 minutes)...
    echo.

    timeout /t 5 >nul

    docker-compose ps
) else (
    echo [i] Services not started
    echo.
    echo To start services later, run:
    if "!SSL_ENABLED!"=="true" (
        echo   docker-compose -f docker-compose.yml -f docker-compose.ssl.yml up -d
    ) else (
        echo   docker-compose up -d
    )
)

pause

REM Final Summary
cls
echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.

echo Your ELK Stack has been configured successfully!
echo.

echo Access your services:
if "!SSL_ENABLED!"=="true" (
    echo   - Kibana:           https://!DOMAIN_NAME!:9443/kibana
    echo   - APISIX Dashboard: https://!DOMAIN_NAME!:9000
    echo   - Grafana:          https://!DOMAIN_NAME!:9443/grafana
    echo   - Prometheus:       https://!DOMAIN_NAME!:9443/prometheus
) else (
    echo   - Kibana:           http://!DOMAIN_NAME!:9080/kibana
    echo   - APISIX Dashboard: http://!DOMAIN_NAME!:9000
    echo   - Grafana:          http://!DOMAIN_NAME!:9080/grafana
    echo   - Prometheus:       http://!DOMAIN_NAME!:9080/prometheus
)
echo.

echo Login Credentials:
echo   - Kibana:     elastic / (see .env file for ELASTIC_PASSWORD^)
echo   - Grafana:    admin / (see .env file for GRAFANA_ADMIN_PASSWORD^)
echo   - APISIX:     admin / admin
echo.

echo Important Files:
echo   - Configuration: .env
echo   - Passwords: .env (keep secure!^)
if "!SSL_ENABLED!"=="true" (
    echo   - SSL Certificates: certs\
)
echo.

echo Useful Commands:
echo   - Check status:  docker-compose ps
echo   - View logs:     docker-compose logs -f
echo   - Stop services: docker-compose down
echo   - Restart:       docker-compose restart
echo.

echo For detailed documentation, see README.md and docs\
echo.

echo [OK] Happy logging!
echo.

pause
endlocal
