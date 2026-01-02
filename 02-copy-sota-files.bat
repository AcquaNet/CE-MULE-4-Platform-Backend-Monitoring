@echo off
echo ===============================================
echo Copying SOTA files to Docker directories
echo ===============================================
echo.

REM Create java64 directories if they don't exist
echo Creating java64 directories...
if not exist "git\CE-MULE-4-Platform-Backend-Docker\CE_Microservice\docker_maven\java64" mkdir "git\CE-MULE-4-Platform-Backend-Docker\CE_Microservice\docker_maven\java64"
if not exist "git\CE-MULE-4-Platform-Backend-Docker\CE_Microservice\docker_mulesoft\java64" mkdir "git\CE-MULE-4-Platform-Backend-Docker\CE_Microservice\docker_mulesoft\java64"
echo.

REM Copy Maven files
echo Copying Maven files...
echo   - apache-maven-3.6.3-bin.tar.gz (already exists, skipping)
REM Already exists: copy "CE-Platform\_sota\apache-maven-3.6.3-bin.tar.gz" "git\CE-MULE-4-Platform-Backend-Docker\CE_Microservice\docker_maven\images\"
echo.

REM Copy OpenJDK for Maven
echo Copying OpenJDK to Maven java64...
copy "CE-Platform\_sota\OpenJDK8U-jdk_x64_linux_hotspot_8u362b09.tar.gz" "git\CE-MULE-4-Platform-Backend-Docker\CE_Microservice\docker_maven\java64\"
if errorlevel 1 (
    echo [ERROR] Failed to copy OpenJDK for Maven
    pause
    exit /b 1
)
echo   OK: OpenJDK copied to docker_maven\java64\
echo.

REM Copy OpenJDK for Mulesoft
echo Copying OpenJDK to Mulesoft java64...
copy "CE-Platform\_sota\OpenJDK8U-jdk_x64_linux_hotspot_8u362b09.tar.gz" "git\CE-MULE-4-Platform-Backend-Docker\CE_Microservice\docker_mulesoft\java64\"
if errorlevel 1 (
    echo [ERROR] Failed to copy OpenJDK for Mulesoft
    pause
    exit /b 1
)
echo   OK: OpenJDK copied to docker_mulesoft\java64\
echo.

REM Copy Mule standalone
echo Copying Mule standalone runtime...
copy "CE-Platform\_sota\mule-standalone-4.4.0.tar.gz" "git\CE-MULE-4-Platform-Backend-Docker\CE_Microservice\docker_mulesoft\images\"
if errorlevel 1 (
    echo [ERROR] Failed to copy Mule standalone
    pause
    exit /b 1
)
echo   OK: Mule standalone copied to docker_mulesoft\images\
echo.

echo ===============================================
echo All files copied successfully!
echo ===============================================
echo.
echo Next steps:
echo   3. Create Docker network: docker network create --driver=bridge --subnet=172.42.0.0/16 ce-base-network
echo   4. Create volumes: cd git\CE-MULE-4-Platform-Backend-Docker\CE_Microservice
echo   5. Run: 01-create-volumes.bat
echo   6. Build: docker compose build
echo   7. Start: docker compose --env-file .env up -d
echo.
pause
