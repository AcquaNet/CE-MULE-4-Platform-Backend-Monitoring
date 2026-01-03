@echo off
REM
REM Import all Docker images from exported tar files
REM
REM This script loads all Docker images that were exported using export-images.bat
REM
REM Usage:
REM   import-images.bat [directory]
REM
REM Default directory: current directory
REM

setlocal enabledelayedexpansion

set "IMPORT_DIR=%~1"
if "%IMPORT_DIR%"=="" set "IMPORT_DIR=."

echo ================================
echo Docker Images Import Tool
echo ================================
echo.
echo Import directory: %IMPORT_DIR%
echo.

REM Change to import directory
cd /d "%IMPORT_DIR%"

REM Count tar files
set TOTAL=0
for %%f in (*.tar) do set /a TOTAL+=1

if %TOTAL%==0 (
    echo No tar files found in %IMPORT_DIR%
    echo.
    echo Expected file pattern: *.tar
    echo.
    echo Make sure you have exported images using export-images.bat first
    exit /b 1
)

echo Found %TOTAL% image files to import
echo.

REM Ask for confirmation
set /p CONFIRM="Import all %TOTAL% images? This may take several minutes. (y/n) "
if /i not "%CONFIRM%"=="y" (
    echo Import cancelled
    exit /b 0
)
echo.

set CURRENT=0
set IMPORTED=0
set FAILED=0

REM Import each tar file
for %%f in (*.tar) do (
    set /a CURRENT+=1
    echo [!CURRENT!/%TOTAL%] Importing: %%f

    docker load -i "%%f"
    if errorlevel 1 (
        echo   Failed to import
        set /a FAILED+=1
    ) else (
        echo   Imported successfully
        set /a IMPORTED+=1
    )

    echo.
)

REM Summary
echo ================================
echo Import Summary:
echo   Total: %TOTAL%
echo   Imported: %IMPORTED%
echo   Failed: %FAILED%
echo ================================
echo.

REM Verify imported images
echo Verifying imported images...
echo.
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | findstr /i "elasticsearch kibana logstash apm-server apisix etcd prometheus grafana alertmanager curl"
echo.

if %FAILED%==0 (
    echo All images imported successfully!
    echo.
    echo Next steps:
    echo.
    echo 1. Ensure Docker networks are created:
    echo    docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet
    echo    docker network create ce-base-network
    echo.
    echo 2. Navigate to project root directory (if not already there)
    echo.
    echo 3. Configure environment:
    echo    copy .env.example .env
    echo    config\scripts\setup\generate-secrets.bat
    echo.
    echo 4. Start services:
    echo    docker-compose up -d
    echo.
    echo 5. Check status:
    echo    docker-compose ps
    echo.
    echo 6. Access services:
    echo    - Kibana: http://localhost:9080/kibana
    echo    - APISIX Dashboard: http://localhost:9000
    echo    - Grafana: http://localhost:9080/grafana
    echo    - Prometheus: http://localhost:9080/prometheus
) else (
    echo Some images failed to import.
    echo.
    echo Troubleshooting:
    echo   1. Check Docker is running: docker ps
    echo   2. Check disk space: dir
    echo   3. Try importing failed files manually: docker load -i [filename].tar
    exit /b 1
)

endlocal
