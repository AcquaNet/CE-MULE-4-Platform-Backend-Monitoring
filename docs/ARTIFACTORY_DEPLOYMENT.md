# Artifactory (Maven) Deployment

Mule apps are published as Maven artifacts to JFrog Artifactory at `https://jfrog.atina-connection.com`. The
Runtime Manager fetches them from there. No Docker images are pushed: the Runtime Manager builds the Mule
runtime image locally.

| Repository | URL | Server id |
|------------|-----|-----------|
| releases | `https://jfrog.atina-connection.com/artifactory/libs-release` | `acquanet-central` |
| snapshots | `https://jfrog.atina-connection.com/artifactory/libs-snapshot` | `acquanet-snapshots` |

## Publishing an app

The app's `pom.xml` has a `<distributionManagement>` that points at both repositories using these ids. Your own
`~/.m2/settings.xml` needs a `<server>` with your credentials for each id (a template is in
`CE-Platform/_sota/settings.xml`). Never commit credentials.

```bash
cd git/CE-MULE-4-Platform-Backend-Mule
./01-build-and-deploy.sh
```

The script bumps `ce.version` in `src/main/resources/config/common.properties` and the pom version, then commits.
It runs `mvn clean package` and uploads the jar with `mvn deploy:deploy-file`. Push the commit yourself.
A plain `mvn clean deploy` also works (`-SNAPSHOT` versions go to `libs-snapshot`).

## How the Runtime Manager fetches apps

- **Default app:** `MULEAPP_GROUP_ID`, `MULEAPP_ARTIFACT_ID`, `MULEAPP_VERSION` in the root `.env`. It is deployed
  on first start and redeployed when `MULEAPP_VERSION` changes.
- **Other apps:** use "+ Deploy" in the UI, or `PUT /api/apps/<app>` with `group`, `artifact`, `version`
  (see [mule/README.md](../mule/README.md#pipelines)).
- **Version:** a fixed version, `RELEASE`, `LATEST` or `x-SNAPSHOT`. The update mode per app is `auto`,
  `notify` or `off`.
- **Repositories:** `ATINA_REPOSITORY_URL` is tried first, then the repositories of the active profiles in
  `mule/maven-settings.xml`. Credentials come from that file's `<servers>`, which read `${env.ARTIFACTORY_USER}` and
  `${env.ARTIFACTORY_PASSWORD}` from the root `.env`.
- **https only:** the Runtime Manager skips plain `http://` repositories (except localhost), because a jar
  fetched over http could be swapped in transit.

```env
ATINA_REPOSITORY_PROTOCOL=https
ATINA_REPOSITORY_URL=https://jfrog.atina-connection.com/artifactory/libs-release
ARTIFACTORY_USER=acqua-dev
ARTIFACTORY_PASSWORD=<secret>
```

## Problems

| Symptom | Check |
|---------|-------|
| `401` on `mvn deploy` | your `~/.m2/settings.xml` server ids must be `acquanet-central` / `acquanet-snapshots` |
| Snapshot deployed to releases (or the reverse) | the pom version must end in `-SNAPSHOT` for snapshots |
| Runtime Manager can't find the artifact | `docker compose logs ce-base-runtime-manager \| grep -i seed`; check the coordinates, `ARTIFACTORY_*` in `.env`, and that the repo URL is https |
| Repository unreachable | as a workaround, upload the jar in the Runtime Manager (`PUT /api/apps/<app>` with `Content-Type: application/java-archive`) |
