# JFrog Artifactory Deployment Guide

This guide covers deploying both Maven artifacts and Docker images to the company's JFrog Artifactory repository.

## Table of Contents

- [Artifactory Configuration](#artifactory-configuration)
- [Deploying Maven Artifacts](#deploying-maven-artifacts)
- [Deploying Docker Images](#deploying-docker-images)
- [CI/CD Integration](#cicd-integration)
- [Management Commands](#management-commands)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)

## Artifactory Configuration

### Repository Details

- **Host**: `<ARTIFACTORY_HOST>:<PORT>` (configured in settings.xml)
- **Base URL**: `http://<ARTIFACTORY_HOST>:<PORT>/artifactory/`
- **Maven Releases**: `libs-release` (Repository ID: `acquanet-central`)
- **Maven Snapshots**: `libs-snapshot` (Repository ID: `acquanet-snapshots`)
- **Docker Registry**: `<ARTIFACTORY_HOST>:<PORT>/artifactory/docker-local/`

### Credentials

- Configured in `CE-Platform/_sota/settings.xml`
- Repository IDs: `acquanet-central`, `acquanet-snapshots`
- **IMPORTANT**: Never commit credentials to version control. Use environment variables or secrets management in production.

### Maven Settings

- Location: `CE-Platform/_sota/settings.xml`
- Install to: `~/.m2/settings.xml` (Linux/Mac) or `%USERPROFILE%\.m2\settings.xml` (Windows)

## Deploying Maven Artifacts

### 1. Configure Maven Settings

Copy the provided settings.xml to your Maven configuration directory:

```bash
# Linux/Mac
cp "CE-Platform/_sota/settings.xml" ~/.m2/settings.xml

# Windows
copy "CE-Platform\_sota\settings.xml" "%USERPROFILE%\.m2\settings.xml"
```

### 2. Configure POM for Deployment

Add distribution management to your `pom.xml`:

```xml
<distributionManagement>
    <repository>
        <id>acquanet-central</id>
        <name>Company Release Repository</name>
        <url>http://${env.ARTIFACTORY_HOST}:${env.ARTIFACTORY_PORT}/artifactory/libs-release</url>
    </repository>
    <snapshotRepository>
        <id>acquanet-snapshots</id>
        <name>Company Snapshot Repository</name>
        <url>http://${env.ARTIFACTORY_HOST}:${env.ARTIFACTORY_PORT}/artifactory/libs-snapshot</url>
    </snapshotRepository>
</distributionManagement>
```

Or with hardcoded values (retrieve from settings.xml):
```xml
<distributionManagement>
    <repository>
        <id>acquanet-central</id>
        <name>Company Release Repository</name>
        <url><!-- URL from settings.xml --></url>
    </repository>
    <snapshotRepository>
        <id>acquanet-snapshots</id>
        <name>Company Snapshot Repository</name>
        <url><!-- URL from settings.xml --></url>
    </snapshotRepository>
</distributionManagement>
```

**IMPORTANT**: The `<id>` values (`acquanet-central` and `acquanet-snapshots`) must match the server IDs in your `settings.xml`. This is how Maven maps the credentials to the repository.

### 3. Deploy Maven Artifacts

Deploy a release version:
```bash
# Ensure version in pom.xml does NOT end with -SNAPSHOT
mvn clean deploy
```

Deploy a snapshot version:
```bash
# Ensure version in pom.xml ends with -SNAPSHOT
mvn clean deploy
```

Deploy without running tests:
```bash
mvn clean deploy -DskipTests
```

### 4. Automated Deployment (Mule Application)

The Mule application includes an automated build script:

```bash
cd "git/CE-MULE-4-Platform-Backend-Mule"
./01-build-and-deploy.sh
```

This script automatically:
1. Reads the current version from `src/main/resources/config/common.properties`
2. Auto-increments the patch version (e.g., 1.0.8 → 1.0.9)
3. Updates `common.properties` with the new version
4. Commits the version change to git
5. Builds the artifact with `mvn clean package`
6. Deploys to Artifactory using `mvn deploy`

### 5. Download Artifacts from Artifactory

Using Maven coordinates in Docker Compose:
```yaml
environment:
  - MULEAPP_GROUP_ID=com.company
  - MULEAPP_ARTIFACT_ID=app-name
  - MULEAPP_VERSION=1.0.8
  - ATINA_REPOSITORY_URL=${ARTIFACTORY_URL}/libs-release
```

Manual download using Maven:
```bash
mvn dependency:get \
  -DremoteRepositories=${ARTIFACTORY_URL}/libs-release \
  -DgroupId=com.company \
  -DartifactId=app-name \
  -Dversion=1.0.8 \
  -Dpackaging=jar
```

Direct download via HTTP (credentials from settings.xml):
```bash
curl -u ${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD} \
  "${ARTIFACTORY_URL}/libs-release/com/company/app-name/1.0.8/app-name-1.0.8.jar" \
  -o app-name-1.0.8.jar
```

## Deploying Docker Images

### 1. Configure Docker for Artifactory

Login to the Docker registry:
```bash
docker login ${ARTIFACTORY_HOST}:${ARTIFACTORY_PORT}
# Username: (from settings.xml)
# Password: (from settings.xml or environment variable)
```

For non-HTTPS registries, configure Docker daemon to allow insecure registry. Edit `/etc/docker/daemon.json`:
```json
{
  "insecure-registries": ["<ARTIFACTORY_HOST>:<PORT>"]
}
```

Restart Docker:
```bash
# Linux
sudo systemctl restart docker

# Windows/Mac
# Restart Docker Desktop
```

### 2. Tag Docker Images

Tag your image for Artifactory:
```bash
# Format: [registry]/[repository]/[image]:[tag]
docker tag mule-backend:latest ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:latest
docker tag mule-backend:latest ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:1.0.8
```

### 3. Push Docker Images

Push to Artifactory:
```bash
# Push latest tag
docker push ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:latest

# Push version tag
docker push ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:1.0.8
```

Push all tags:
```bash
docker push --all-tags ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend
```

### 4. Pull Docker Images from Artifactory

Pull from Artifactory:
```bash
# Pull specific version
docker pull ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:1.0.8

# Pull latest
docker pull ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:latest
```

### 5. Automated Docker Build and Deploy

Example script for building and deploying Docker images:

```bash
#!/bin/bash
# 01-build-and-push-docker.sh

set -e

# Configuration (set these as environment variables or in .env file)
REGISTRY="${ARTIFACTORY_REGISTRY}/docker-local"
IMAGE_NAME="mule-backend"
VERSION=$(cat src/main/resources/config/common.properties | grep "app.version" | cut -d'=' -f2)

# Build the Docker image
echo "Building Docker image..."
docker build -t ${IMAGE_NAME}:${VERSION} .

# Tag for Artifactory
echo "Tagging image for Artifactory..."
docker tag ${IMAGE_NAME}:${VERSION} ${REGISTRY}/${IMAGE_NAME}:${VERSION}
docker tag ${IMAGE_NAME}:${VERSION} ${REGISTRY}/${IMAGE_NAME}:latest

# Push to Artifactory
echo "Pushing to Artifactory..."
docker push ${REGISTRY}/${IMAGE_NAME}:${VERSION}
docker push ${REGISTRY}/${IMAGE_NAME}:latest

echo "Successfully deployed ${IMAGE_NAME}:${VERSION} to Artifactory"
```

Make it executable:
```bash
chmod +x 01-build-and-push-docker.sh
./01-build-and-push-docker.sh
```

### 6. Using Artifactory Images in Docker Compose

Update `docker-compose.yml` to use images from Artifactory:

```yaml
services:
  ce-base-mule-backend:
    image: ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:1.0.8
    # ... rest of configuration
```

Or use version from environment variable:
```yaml
services:
  ce-base-mule-backend:
    image: ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:${MULE_VERSION:-latest}
    # ... rest of configuration
```

## CI/CD Integration

### Maven CI/CD Example (Jenkins/GitLab CI)

```yaml
# .gitlab-ci.yml
stages:
  - build
  - deploy

build:
  stage: build
  script:
    - mvn clean package -DskipTests

deploy:
  stage: deploy
  script:
    - mvn deploy -DskipTests
  only:
    - main
    - develop
```

### Docker CI/CD Example

```yaml
# .gitlab-ci.yml
stages:
  - build
  - push

docker-build:
  stage: build
  script:
    - docker build -t ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA} .
    - docker tag ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA} ${CI_REGISTRY_IMAGE}:latest

docker-push:
  stage: push
  before_script:
    - docker login -u ${ARTIFACTORY_USER} -p ${ARTIFACTORY_PASSWORD} ${ARTIFACTORY_REGISTRY}
  script:
    - docker push ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:${VERSION}
    - docker push ${ARTIFACTORY_REGISTRY}/docker-local/mule-backend:latest
  only:
    - main
```

## Management Commands

### List Repository Contents

List Maven artifacts via REST API:
```bash
curl -u ${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD} \
  "${ARTIFACTORY_URL}/api/storage/libs-release/com/company/app-name"
```

List Docker images via REST API:
```bash
curl -u ${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD} \
  "${ARTIFACTORY_URL}/api/docker/docker-local/v2/_catalog"
```

### Search for Artifacts

Search by name:
```bash
curl -u ${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD} \
  "${ARTIFACTORY_URL}/api/search/artifact?name=app-name&repos=libs-release"
```

Search by Maven coordinates:
```bash
curl -u ${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD} \
  "${ARTIFACTORY_URL}/api/search/gavc?g=com.company&a=app-name&v=1.0.8&repos=libs-release"
```

### Delete Artifacts (Careful!)

Delete specific Maven version:
```bash
curl -u ${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD} -X DELETE \
  "${ARTIFACTORY_URL}/libs-release/com/company/app-name/1.0.7"
```

Delete Docker image tag:
```bash
curl -u ${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD} -X DELETE \
  "${ARTIFACTORY_URL}/docker-local/image-name/1.0.7"
```

## Troubleshooting

### Maven Deployment Failures

#### Issue: `401 Unauthorized` error
```
[ERROR] Failed to execute goal org.apache.maven.plugins:maven-deploy-plugin:2.7:deploy
Return code is: 401, ReasonPhrase: Unauthorized
```

**Solution**:
1. Verify credentials in `~/.m2/settings.xml`
2. Ensure server `<id>` matches distributionManagement `<id>`
3. Test authentication:
```bash
curl -u ${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD} ${ARTIFACTORY_URL}/api/system/ping
```

#### Issue: `Could not transfer artifact` or connection timeout

**Solution**:
1. Check network connectivity to Artifactory:
```bash
curl -v ${ARTIFACTORY_URL}/
```
2. Verify repository URLs in `pom.xml` and `settings.xml`
3. Check firewall/proxy settings

#### Issue: Snapshot version deployed to release repository (or vice versa)

**Solution**:
- Release versions: Remove `-SNAPSHOT` suffix from `<version>` in pom.xml
- Snapshot versions: Add `-SNAPSHOT` suffix to `<version>` in pom.xml
- Maven automatically routes based on version suffix

### Docker Deployment Failures

#### Issue: `x509: certificate signed by unknown authority`

**Solution**:
Add registry to insecure registries in `/etc/docker/daemon.json`:
```json
{
  "insecure-registries": ["<ARTIFACTORY_HOST>:<PORT>"]
}
```
Restart Docker daemon.

#### Issue: `denied: requested access to the resource is denied`

**Solution**:
1. Login again with correct credentials:
```bash
docker logout ${ARTIFACTORY_REGISTRY}
docker login ${ARTIFACTORY_REGISTRY}
```
2. Verify image name includes full registry path
3. Check user permissions in Artifactory

#### Issue: Push succeeds but image not visible in Artifactory

**Solution**:
1. Check repository configuration in Artifactory UI
2. Verify Docker repository type (must be "Docker" type, not "Generic")
3. Check repository path: Should be `docker-local` or your configured Docker repository name

## Best Practices

### Version Management
- Use semantic versioning: `MAJOR.MINOR.PATCH` (e.g., 1.0.8)
- Release versions: No `-SNAPSHOT` suffix
- Development versions: Use `-SNAPSHOT` suffix (e.g., 1.0.9-SNAPSHOT)
- Tag Docker images with both version and `latest`

### Security
- **Never commit credentials** to version control
- Use environment variables or CI/CD secrets for passwords
- Rotate passwords regularly
- Use HTTPS for production deployments
- Consider using API keys instead of username/password

### Cleanup and Retention
- Implement retention policies to remove old snapshots
- Keep release versions longer than snapshots
- Document which versions are deployed to which environments
- Tag production images clearly (e.g., `prod-1.0.8`)

### Repository Organization
```
libs-release/
  └── com/acqua/
      ├── ce-mule-base/          # Mule application artifacts
      ├── common-utils/          # Shared utility libraries
      └── connectors/            # Custom connectors

docker-local/
  ├── mule-backend/              # Mule runtime images
  ├── activemq/                  # ActiveMQ images
  └── mysql/                     # Database images
```

## Quick Reference

### Common Tasks

| Task | Command |
|------|---------|
| Deploy Maven Release | `mvn clean deploy` (no -SNAPSHOT in version) |
| Deploy Maven Snapshot | `mvn clean deploy` (with -SNAPSHOT in version) |
| Tag Docker Image | `docker tag image:tag ${REGISTRY}/repo/image:tag` |
| Push Docker Image | `docker push ${REGISTRY}/repo/image:tag` |
| Pull Docker Image | `docker pull ${REGISTRY}/repo/image:tag` |
| Test Authentication | `curl -u user:pass ${ARTIFACTORY_URL}/api/system/ping` |

### Environment Variables

```bash
export ARTIFACTORY_HOST="<host>"
export ARTIFACTORY_PORT="<port>"
export ARTIFACTORY_URL="http://${ARTIFACTORY_HOST}:${ARTIFACTORY_PORT}/artifactory"
export ARTIFACTORY_REGISTRY="${ARTIFACTORY_HOST}:${ARTIFACTORY_PORT}"
export ARTIFACTORY_USER="<username>"
export ARTIFACTORY_PASSWORD="<password>"
```
