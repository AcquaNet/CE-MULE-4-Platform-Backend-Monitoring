@echo off
REM
REM Create a single tar archive containing all ELK Stack Docker images
REM
REM This script combines all ELK stack images into a single tar file,
REM making it easier to transfer and import on target machines.
REM
REM Usage:
REM   create-elk-single-archive.bat [output-file]
REM
REM Default output: elk-stack-all-images.tar
REM

setlocal enabledelayedexpansion

set "OUTPUT_FILE=%~1"
if "%OUTPUT_FILE%"=="" set "OUTPUT_FILE=elk-stack-all-images.tar"

echo ================================
echo ELK Stack Single Archive Creator
echo ================================
echo.
echo Output file: %OUTPUT_FILE%
echo.

REM Define ELK stack images (excluding Mule-related images)
set "IMAGES[0]=docker.elastic.co/elasticsearch/elasticsearch:8.11.3"
set "IMAGES[1]=docker.elastic.co/kibana/kibana:8.11.3"
set "IMAGES[2]=docker.elastic.co/logstash/logstash:8.11.3"
set "IMAGES[3]=docker.elastic.co/apm/apm-server:8.10.4"
set "IMAGES[4]=apache/apisix:3.7.0-debian"
set "IMAGES[5]=apache/apisix-dashboard:3.0.1-alpine"
set "IMAGES[6]=quay.io/coreos/etcd:v3.5.9"
set "IMAGES[7]=prom/prometheus:v2.48.0"
set "IMAGES[8]=grafana/grafana:10.2.2"
set "IMAGES[9]=prom/alertmanager:v0.26.0"
set "IMAGES[10]=quay.io/prometheuscommunity/elasticsearch-exporter:v1.6.0"
set "IMAGES[11]=curlimages/curl:latest"

set TOTAL=12
echo Images to include: %TOTAL%
echo.

REM Check for missing images
echo Checking for missing images...
set MISSING=0

for /L %%i in (0,1,11) do (
    set "IMAGE=!IMAGES[%%i]!"
    docker image inspect "!IMAGE!" >nul 2>&1
    if errorlevel 1 (
        echo   Missing: !IMAGE!
        set /a MISSING+=1
    )
)

REM Pull missing images if needed
if %MISSING% gtr 0 (
    echo.
    echo Found %MISSING% missing images. Pulling...
    echo.

    for /L %%i in (0,1,11) do (
        set "IMAGE=!IMAGES[%%i]!"
        docker image inspect "!IMAGE!" >nul 2>&1
        if errorlevel 1 (
            echo Pulling: !IMAGE!
            docker pull "!IMAGE!"
            if errorlevel 1 (
                echo Failed to pull !IMAGE!
                exit /b 1
            )
        )
    )
    echo.
)

echo All images are available locally
echo.

REM Create single tar file with all images
echo Creating single archive with all images...
echo This may take several minutes...
echo.

REM Build the docker save command with all images
set "DOCKER_CMD=docker save -o "%OUTPUT_FILE%""
for /L %%i in (0,1,11) do (
    set "DOCKER_CMD=!DOCKER_CMD! !IMAGES[%%i]!"
)

REM Execute the command
%DOCKER_CMD%

if errorlevel 1 (
    echo Failed to create archive
    exit /b 1
)

echo.
echo Archive created successfully!
echo.
echo File: %OUTPUT_FILE%
for %%F in ("%OUTPUT_FILE%") do echo Size: %%~zF bytes
echo.

REM Create companion import script
set "IMPORT_SCRIPT=%OUTPUT_FILE:.tar=-import.bat%"

(
    echo @echo off
    echo REM Import ELK Stack images from single archive
    echo.
    echo setlocal
    echo set "ARCHIVE_FILE=elk-stack-all-images.tar"
    echo.
    echo if not exist "%%ARCHIVE_FILE%%" ^(
    echo     echo Error: Archive file not found: %%ARCHIVE_FILE%%
    echo     exit /b 1
    echo ^)
    echo.
    echo echo Importing ELK Stack images...
    echo echo.
    echo echo Archive: %%ARCHIVE_FILE%%
    echo echo.
    echo.
    echo docker load -i "%%ARCHIVE_FILE%%"
    echo.
    echo if errorlevel 1 ^(
    echo     echo Import failed
    echo     exit /b 1
    echo ^)
    echo.
    echo echo.
    echo echo All images imported successfully!
    echo echo.
    echo echo Imported images:
    echo docker images
    echo echo.
    echo echo Next steps:
    echo echo   1. Create networks:
    echo echo      docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet
    echo echo      docker network create ce-base-network
    echo echo.
    echo echo   2. Configure environment:
    echo echo      copy .env.example .env
    echo echo      config\scripts\setup\generate-secrets.bat
    echo echo.
    echo echo   3. Start services:
    echo echo      docker-compose up -d
    echo.
    echo endlocal
) > "%IMPORT_SCRIPT%"

echo Created import script: %IMPORT_SCRIPT%
echo.

REM Create manifest
set "MANIFEST_FILE=%OUTPUT_FILE:.tar=-manifest.txt%"

(
    echo ELK Stack Single Archive Manifest
    echo ==================================
    echo.
    echo Created: %DATE% %TIME%
    echo Archive: %OUTPUT_FILE%
    echo Total Images: %TOTAL%
    echo.
    echo Images Included:
    echo ----------------
    for /L %%i in (0,1,11) do echo   - !IMAGES[%%i]!
    echo.
    echo Import Instructions:
    echo -------------------
    echo 1. Transfer this archive to target machine
    echo 2. Run: docker load -i %OUTPUT_FILE%
    echo 3. Or use: %IMPORT_SCRIPT%
    echo.
    echo Components Included:
    echo -------------------
    echo - ElasticSearch 8.11.3
    echo - Kibana 8.11.3
    echo - Logstash 8.11.3
    echo - APM Server 8.10.4
    echo - Apache APISIX 3.7.0
    echo - APISIX Dashboard 3.0.1
    echo - etcd v3.5.9
    echo - Prometheus v2.48.0
    echo - Grafana 10.2.2
    echo - Alertmanager v0.26.0
    echo - ElasticSearch Exporter v1.6.0
    echo - curl ^(latest^)
) > "%MANIFEST_FILE%"

echo Created manifest: %MANIFEST_FILE%
echo.

echo Summary:
echo --------
echo Archive file: %OUTPUT_FILE%
echo Import script: %IMPORT_SCRIPT%
echo Manifest: %MANIFEST_FILE%
echo.
echo To transfer and import:
echo   1. Copy files to target machine:
echo      - %OUTPUT_FILE%
echo      - %IMPORT_SCRIPT%
echo      - %MANIFEST_FILE%
echo.
echo   2. On target machine, run:
echo      %IMPORT_SCRIPT%
echo.

endlocal
