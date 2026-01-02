#!/bin/bash
set -e

echo "==============================================="
echo "Copying SOTA files to Docker directories"
echo "==============================================="
echo ""

# Create java64 directories if they don't exist
echo "Creating java64 directories..."
mkdir -p "git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/docker_maven/java64"
mkdir -p "git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/docker_mulesoft/java64"
echo ""

# Copy Maven files
echo "Copying Maven files..."
echo "  - apache-maven-3.6.3-bin.tar.gz (already exists, skipping)"
# Already exists: cp "CE-Platform/_sota/apache-maven-3.6.3-bin.tar.gz" "git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/docker_maven/images/"
echo ""

# Copy OpenJDK for Maven
echo "Copying OpenJDK to Maven java64..."
cp "CE-Platform/_sota/OpenJDK8U-jdk_x64_linux_hotspot_8u362b09.tar.gz" "git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/docker_maven/java64/"
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to copy OpenJDK for Maven"
    exit 1
fi
echo "  OK: OpenJDK copied to docker_maven/java64/"
echo ""

# Copy OpenJDK for Mulesoft
echo "Copying OpenJDK to Mulesoft java64..."
cp "CE-Platform/_sota/OpenJDK8U-jdk_x64_linux_hotspot_8u362b09.tar.gz" "git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/docker_mulesoft/java64/"
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to copy OpenJDK for Mulesoft"
    exit 1
fi
echo "  OK: OpenJDK copied to docker_mulesoft/java64/"
echo ""

# Copy Mule standalone
echo "Copying Mule standalone runtime..."
cp "CE-Platform/_sota/mule-standalone-4.4.0.tar.gz" "git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice/docker_mulesoft/images/"
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to copy Mule standalone"
    exit 1
fi
echo "  OK: Mule standalone copied to docker_mulesoft/images/"
echo ""

echo "==============================================="
echo "All files copied successfully!"
echo "==============================================="
echo ""
echo "Next steps:"
echo "  3. Create Docker network: docker network create --driver=bridge --subnet=172.42.0.0/16 ce-base-network"
echo "  4. Create volumes: cd git/CE-MULE-4-Platform-Backend-Docker/CE_Microservice"
echo "  5. Run: ./01-create-volumes.sh"
echo "  6. Build: docker compose build"
echo "  7. Start: docker compose --env-file .env up -d"
echo ""
