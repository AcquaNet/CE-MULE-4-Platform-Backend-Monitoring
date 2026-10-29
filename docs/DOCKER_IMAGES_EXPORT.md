# Offline Install (Docker image export/import)

For a server without internet: export every image on a machine that has it, copy one tar file over, load it, and
install without building or downloading anything.

## 1. Export (machine with internet, project checked out)

```bash
scripts/docker-images/export-images.sh                 # writes platform-images.tar
scripts/docker-images/export-images.sh my-images.tar   # other file name
scripts/docker-images/export-images.sh --list          # only show what would be exported
```

It exports the images of **all** compose profiles (`docker compose --profile "*" config --images`), pulling
or building any that are missing, plus every `ce-mule-runtime:*` image. Those Mule runtime images are built by
the Runtime Manager (it downloads Mule CE), so start the platform once on this machine first, with the pools'
Mule/Java versions, or the offline server cannot create workers. Expect several GB.

## 2. Copy

Copy the tar and the project directory (a git clone or archive, without `.env`, `certs/` or `mule/volumes/`)
to the offline server.

## 3. Import and install (offline server)

```bash
scripts/docker-images/import-images.sh platform-images.tar   # docker load
NO_BUILD=1 ./install.sh                                      # .env with new secrets, start with the loaded images
```

`NO_BUILD=1` makes `install.sh` run `docker compose up --no-build`: it uses the loaded images instead of
rebuilding (the builds download packages). Without it the install fails offline.

## Notes

- The Runtime Manager names runtime images `ce-mule-runtime:<mule>-java<java>-<hash of mule/docker_mulesoft>`.
  The export only helps if the offline server's `mule/docker_mulesoft` is identical; any change there means a
  new build, which needs internet.
- Mule apps come from Artifactory (`ATINA_REPOSITORY_URL`, `mule/maven-settings.xml`). Offline, upload jars
  instead (`PUT /api/apps/<app>` with `Content-Type: application/java-archive`, see CLAUDE.md).
- Node servers (`node/`) need the `ce-rm-node-agent` image built on them (`node/install-node.sh` builds it) and
  the same `ce-mule-runtime` images: load the tar there too.
