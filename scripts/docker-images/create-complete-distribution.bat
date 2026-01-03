@echo off
REM
REM Create Complete ELK Stack Distribution Package
REM
REM This creates a complete, portable package containing:
REM   1. All Docker images (in single tar file)
REM   2. All configuration files
REM   3. Setup scripts
REM   4. Documentation
REM
REM Clients can customize configurations without rebuilding images.
REM
REM Usage:
REM   create-complete-distribution.bat [output-directory]
REM
REM Default output: elk-stack-distribution
REM

setlocal enabledelayedexpansion

set "OUTPUT_DIR=%~1"
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=elk-stack-distribution"

for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ("%TIME%") do (set mytime=%%a%%b)
set TIMESTAMP=%mydate%-%mytime%
set "PACKAGE_NAME=elk-stack-complete-%TIMESTAMP%"

echo ========================================
echo Complete ELK Stack Distribution Creator
echo ========================================
echo.
echo Creating complete distribution package...
echo Output directory: %OUTPUT_DIR%
echo.

REM Create output directory structure
if not exist "%OUTPUT_DIR%\%PACKAGE_NAME%" mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%"

echo Step 1: Exporting Docker images...
echo This may take 10-15 minutes...
echo.

REM Create images directory
if not exist "%OUTPUT_DIR%\%PACKAGE_NAME%\images" mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%\images"

REM Export images using the single archive script
if not exist "create-elk-single-archive.bat" (
    echo ERROR: create-elk-single-archive.bat not found
    exit /b 1
)

call create-elk-single-archive.bat "%OUTPUT_DIR%\%PACKAGE_NAME%\images\elk-stack-all-images.tar"

if errorlevel 1 (
    echo Failed to export images
    exit /b 1
)

echo.
echo Docker images exported
echo.

echo Step 2: Copying configuration files...

REM Copy essential files
if not exist "%OUTPUT_DIR%\%PACKAGE_NAME%\config" mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%\config"
if not exist "%OUTPUT_DIR%\%PACKAGE_NAME%\scripts" mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%\scripts"
if not exist "%OUTPUT_DIR%\%PACKAGE_NAME%\docs" mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%\docs"
if not exist "%OUTPUT_DIR%\%PACKAGE_NAME%\certs" mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%\certs"

REM Copy docker-compose files
copy ..\..\docker-compose.yml "%OUTPUT_DIR%\%PACKAGE_NAME%\" >nul
copy ..\..\docker-compose.ssl.yml "%OUTPUT_DIR%\%PACKAGE_NAME%\" >nul

REM Copy environment template
copy ..\..\. env.example "%OUTPUT_DIR%\%PACKAGE_NAME%\" >nul

REM Copy entire config directory
xcopy /E /I /Y ..\..\config "%OUTPUT_DIR%\%PACKAGE_NAME%\config" >nul

REM Copy scripts directory
xcopy /E /I /Y ..\..\scripts "%OUTPUT_DIR%\%PACKAGE_NAME%\scripts" >nul

REM Copy documentation
copy ..\..\README.md "%OUTPUT_DIR%\%PACKAGE_NAME%\" >nul
copy ..\..\SETUP.md "%OUTPUT_DIR%\%PACKAGE_NAME%\" >nul
copy ..\..\CLAUDE.md "%OUTPUT_DIR%\%PACKAGE_NAME%\" >nul
xcopy /E /I /Y ..\..\docs "%OUTPUT_DIR%\%PACKAGE_NAME%\docs" >nul

REM Create certificate directories
mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%\certs\ca" >nul 2>&1
mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%\certs\apisix" >nul 2>&1
mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%\certs\apm-server" >nul 2>&1
mkdir "%OUTPUT_DIR%\%PACKAGE_NAME%\certs\extra" >nul 2>&1

echo Configuration files copied
echo.

echo Step 3: Creating deployment scripts...

REM Create Windows deployment script
(
echo @echo off
echo REM ELK Stack - Complete Deployment Script
echo REM
echo setlocal
echo.
echo echo ========================================
echo echo ELK Stack Deployment
echo echo ========================================
echo echo.
echo.
echo REM Check if Docker is running
echo docker ps ^>nul 2^>^&1
echo if errorlevel 1 ^(
echo     echo ERROR: Docker is not running
echo     echo Please start Docker Desktop and try again
echo     exit /b 1
echo ^)
echo.
echo echo Step 1: Loading Docker images...
echo echo This may take 5-10 minutes...
echo echo.
echo.
echo if exist "images\elk-stack-all-images.tar" ^(
echo     docker load -i images\elk-stack-all-images.tar
echo     if errorlevel 1 ^(
echo         echo ERROR: Failed to load Docker images
echo         exit /b 1
echo     ^)
echo     echo Images loaded successfully!
echo ^) else ^(
echo     echo ERROR: Image file not found: images\elk-stack-all-images.tar
echo     exit /b 1
echo ^)
echo echo.
echo.
echo echo Step 2: Creating Docker networks...
echo docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet 2^>nul
echo docker network create ce-base-network 2^>nul
echo echo.
echo.
echo echo Step 3: Configuring environment...
echo if not exist ".env" ^(
echo     copy .env.example .env
echo     if exist "config\scripts\setup\generate-secrets.bat" ^(
echo         call config\scripts\setup\generate-secrets.bat
echo     ^)
echo ^)
echo echo.
echo.
echo echo Step 4: Starting services...
echo docker-compose up -d
echo echo.
echo.
echo echo ========================================
echo echo Deployment Complete!
echo echo ========================================
echo echo.
echo echo Access your services at:
echo echo   - Kibana:           http://localhost:9080/kibana
echo echo   - APISIX Dashboard: http://localhost:9000
echo echo   - Grafana:          http://localhost:9080/grafana
echo echo.
echo endlocal
) > "%OUTPUT_DIR%\%PACKAGE_NAME%\deploy.bat"

echo Deployment scripts created
echo.

echo Step 4: Creating README and documentation...

REM Create distribution README
(
echo # ELK Stack - Complete Distribution Package
echo.
echo ## Quick Start
echo.
echo ### Windows
echo.
echo 1. Run: `deploy.bat`
echo 2. Wait 2-3 minutes
echo 3. Access: http://localhost:9080/kibana
echo.
echo ## Customization ^(NO Image Rebuild Required!^)
echo.
echo ### Change Logstash Pipeline
echo.
echo 1. Edit: `config/logstash/pipeline/logstash.conf`
echo 2. Restart: `docker-compose restart logstash`
echo.
echo ✅ No rebuild needed - config is mounted as volume!
echo.
echo ### Change APISIX Routes
echo.
echo 1. Edit: `config/apisix/apisix.yaml`
echo 2. Restart: `docker-compose restart apisix`
echo.
echo ✅ No rebuild needed!
echo.
echo ## What Requires Image Rebuild?
echo.
echo **Almost nothing!** Only version changes or plugin installations.
echo.
echo Everything else is configuration mounted as volumes!
echo.
echo ## Configuration Files Reference
echo.
echo All files in `config/` can be changed without rebuild.
echo Just restart the affected service.
echo.
echo See full documentation in `docs/` directory.
) > "%OUTPUT_DIR%\%PACKAGE_NAME%\DISTRIBUTION-README.md"

echo Documentation created
echo.

echo Step 5: Creating manifest...

REM Create manifest
(
echo ELK Stack Complete Distribution Package
echo ========================================
echo.
echo Created: %DATE% %TIME%
echo Package: %PACKAGE_NAME%
echo.
echo Contents:
echo ---------
echo.
echo 1. Docker Images ^(images/^)
echo    - elk-stack-all-images.tar
echo.
echo 2. Configuration Files ^(config/^)
echo    - apisix/          - API Gateway configuration
echo    - logstash/        - Log processing pipelines
echo    - prometheus/      - Metrics and alerts
echo    - grafana/         - Dashboards
echo.
echo 3. Deployment Files
echo    - docker-compose.yml
echo    - .env.example
echo.
echo 4. Scripts
echo    - deploy.bat       - Windows deployment
echo.
echo 5. Documentation
echo    - DISTRIBUTION-README.md
echo    - README.md, SETUP.md, CLAUDE.md
echo    - docs/
echo.
echo Key Features:
echo -------------
echo ✓ Complete offline deployment
echo ✓ All configurations included
echo ✓ Clients can customize without rebuilding images
echo ✓ Automated deployment script
echo ✓ Full documentation
echo.
echo Quick Start:
echo ------------
echo Windows: deploy.bat
echo.
echo Customization:
echo --------------
echo All configuration files can be modified without rebuilding images.
echo See DISTRIBUTION-README.md for details.
) > "%OUTPUT_DIR%\%PACKAGE_NAME%\MANIFEST.txt"

echo Manifest created
echo.

echo.
echo ========================================
echo Distribution Package Complete!
echo ========================================
echo.
echo Package location: %OUTPUT_DIR%\%PACKAGE_NAME%
echo.
echo Contents:
echo   - Docker images:     images\elk-stack-all-images.tar
echo   - Configurations:    config\
echo   - Deploy script:     deploy.bat
echo   - Documentation:     DISTRIBUTION-README.md
echo.
echo To deploy:
echo   cd %OUTPUT_DIR%\%PACKAGE_NAME%
echo   deploy.bat
echo.
echo Key Feature: Clients can modify all configs without rebuilding images!
echo.

endlocal
