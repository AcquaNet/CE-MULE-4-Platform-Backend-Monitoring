@echo off
REM
REM Export all Docker images used in the ELK Stack + APISIX setup
REM
REM This script saves all Docker images to tar files for offline distribution.
REM The exported images can be loaded on another machine using import-images.bat
REM
REM Usage:
REM   export-images.bat [output-directory]
REM
REM Default output directory: .\docker-images-export
REM

setlocal enabledelayedexpansion

REM Default output directory
set "OUTPUT_DIR=%~1"
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=docker-images-export"

REM Create output directory
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

echo ================================
echo Docker Images Export Tool
echo ================================
echo.
echo Output directory: %OUTPUT_DIR%
echo.

REM Define all images
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
set CURRENT=0
set EXPORTED=0
set SKIPPED=0
set FAILED=0

echo Found %TOTAL% images to export
echo.

REM Export each image
for /L %%i in (0,1,11) do (
    set /a CURRENT+=1
    set "IMAGE=!IMAGES[%%i]!"

    REM Sanitize filename
    set "FILENAME=!IMAGE!"
    set "FILENAME=!FILENAME::=_!"
    set "FILENAME=!FILENAME:/=_!"
    set "FILENAME=!FILENAME:.=_!"
    set "FILEPATH=%OUTPUT_DIR%\!FILENAME!.tar"

    echo [!CURRENT!/%TOTAL%] Processing: !IMAGE!

    REM Check if tar file already exists
    if exist "!FILEPATH!" (
        echo   File already exists. Skipping.
        set /a SKIPPED+=1
    ) else (
        REM Check if image exists locally
        docker image inspect "!IMAGE!" >nul 2>&1
        if errorlevel 1 (
            echo   Image not found locally. Pulling...
            docker pull "!IMAGE!"
            if errorlevel 1 (
                echo   Failed to pull image
                set /a FAILED+=1
                goto :continue
            )
            echo   Pulled successfully
        )

        REM Export image
        echo   Exporting to: !FILENAME!.tar
        docker save -o "!FILEPATH!" "!IMAGE!"
        if errorlevel 1 (
            echo   Failed to export
            set /a FAILED+=1
            if exist "!FILEPATH!" del "!FILEPATH!"
        ) else (
            echo   Exported successfully
            set /a EXPORTED+=1
        )
    )
    :continue
    echo.
)

REM Generate manifest file
set "MANIFEST_FILE=%OUTPUT_DIR%\MANIFEST.txt"
echo Generating manifest file: %MANIFEST_FILE%

(
    echo Docker Images Export Manifest
    echo =============================
    echo.
    echo Export Date: %DATE% %TIME%
    echo Total Images: %TOTAL%
    echo Exported: %EXPORTED%
    echo Skipped: %SKIPPED%
    echo Failed: %FAILED%
    echo.
    echo Images:
    echo -------
    for /L %%i in (0,1,11) do echo   - !IMAGES[%%i]!
    echo.
    echo Files:
    echo ------
    dir /b "%OUTPUT_DIR%\*.tar" 2>nul
) > "%MANIFEST_FILE%"

REM Generate import batch script
set "IMPORT_SCRIPT=%OUTPUT_DIR%\import-images.bat"
echo Generating import script: %IMPORT_SCRIPT%

(
    echo @echo off
    echo REM Import all Docker images from exported tar files
    echo setlocal enabledelayedexpansion
    echo.
    echo echo ================================
    echo echo Docker Images Import Tool
    echo echo ================================
    echo echo.
    echo.
    echo set TOTAL=0
    echo set IMPORTED=0
    echo set FAILED=0
    echo.
    echo for %%%%f in ^(*.tar^) do set /a TOTAL+=1
    echo.
    echo if %%TOTAL%%==0 ^(
    echo     echo No tar files found in current directory
    echo     exit /b 1
    echo ^)
    echo.
    echo echo Found %%TOTAL%% image files to import
    echo echo.
    echo.
    echo set CURRENT=0
    echo for %%%%f in ^(*.tar^) do ^(
    echo     set /a CURRENT+=1
    echo     echo [!CURRENT!/%%TOTAL%%] Importing: %%%%f
    echo     docker load -i "%%%%f"
    echo     if errorlevel 1 ^(
    echo         echo   Failed to import
    echo         set /a FAILED+=1
    echo     ^) else ^(
    echo         echo   Imported successfully
    echo         set /a IMPORTED+=1
    echo     ^)
    echo     echo.
    echo ^)
    echo.
    echo echo ================================
    echo echo Import Summary:
    echo echo   Total: %%TOTAL%%
    echo echo   Imported: %%IMPORTED%%
    echo echo   Failed: %%FAILED%%
    echo echo ================================
    echo echo.
    echo.
    echo if %%FAILED%%==0 ^(
    echo     echo All images imported successfully!
    echo     echo.
    echo     echo Next steps:
    echo     echo   1. Create networks:
    echo     echo      docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet
    echo     echo      docker network create ce-base-network
    echo     echo   2. Configure: copy .env.example .env
    echo     echo   3. Generate secrets: config\scripts\setup\generate-secrets.sh
    echo     echo   4. Start: docker-compose up -d
    echo ^) else ^(
    echo     echo Some images failed to import
    echo     exit /b 1
    echo ^)
) > "%IMPORT_SCRIPT%"

REM Generate README
set "README_FILE=%OUTPUT_DIR%\README.txt"
echo Generating README: %README_FILE%

(
    echo Docker Images Export Package for ELK Stack + APISIX Gateway
    echo ===========================================================
    echo.
    echo CONTENTS
    echo --------
    echo - Docker Images: All images exported as .tar files
    echo - MANIFEST.txt: List of all images and export details
    echo - import-images.bat: Automated import script for Windows
    echo - import-images.sh: Automated import script for Linux/Mac
    echo - README.txt: This file
    echo.
    echo IMPORT INSTRUCTIONS - WINDOWS
    echo -----------------------------
    echo 1. Open Command Prompt or PowerShell
    echo 2. Navigate to this directory
    echo 3. Run: import-images.bat
    echo.
    echo IMPORT INSTRUCTIONS - LINUX/MAC
    echo -------------------------------
    echo 1. Make import script executable: chmod +x import-images.sh
    echo 2. Run: ./import-images.sh
    echo.
    echo MANUAL IMPORT
    echo -------------
    echo For each .tar file, run:
    echo   docker load -i filename.tar
    echo.
    echo NEXT STEPS AFTER IMPORT
    echo -----------------------
    echo 1. Create Docker networks:
    echo    docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet
    echo    docker network create ce-base-network
    echo.
    echo 2. Configure environment:
    echo    copy .env.example .env
    echo    config\scripts\setup\generate-secrets.bat
    echo.
    echo 3. Start services:
    echo    docker-compose up -d
    echo.
    echo 4. Verify:
    echo    docker-compose ps
    echo.
    echo 5. Access services:
    echo    - Kibana: http://localhost:9080/kibana
    echo    - APISIX Dashboard: http://localhost:9000
    echo    - Grafana: http://localhost:9080/grafana
    echo.
    echo See MANIFEST.txt for complete image list and details.
) > "%README_FILE%"

echo.
echo ================================
echo Export Summary
echo ================================
echo Total Images: %TOTAL%
echo Exported: %EXPORTED%
echo Skipped: %SKIPPED%
echo Failed: %FAILED%
echo.
echo Output directory: %OUTPUT_DIR%
echo.
echo Generated files:
echo   - MANIFEST.txt (image list and details)
echo   - README.txt (setup instructions)
echo   - import-images.bat (automated import script)
echo   - import-images.sh (Linux/Mac import script)
echo.

if %FAILED%==0 (
    echo All images exported successfully!
    echo.
    echo Next steps:
    echo   1. Copy the entire %OUTPUT_DIR% directory to target machine
    echo   2. Run: cd %OUTPUT_DIR% ^&^& import-images.bat
    echo.
    echo Or create a zip file for easier transfer:
    echo   - Right-click %OUTPUT_DIR% folder
    echo   - Send to ^> Compressed (zipped) folder
) else (
    echo Some images failed to export. Check the errors above.
    exit /b 1
)

endlocal
