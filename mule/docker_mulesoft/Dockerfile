# Mule 4 CE standalone worker. The runtime is downloaded at build time from MuleSoft's public
# repository (nothing to carry in the repo):
#   MULE_VERSION   4.12.0 (default) | any CE version | latest   (see mule/README.md for Java pairing)
#   JAVA_VERSION   17 (default) | 8 | 11  - Eclipse Temurin JDK base image
# `latest` follows MuleSoft's maven-metadata.xml: when a new release is published the next
# `docker compose build` picks it up on its own (the ADD below busts the cache).
ARG JAVA_VERSION=17
FROM --platform=linux/amd64 eclipse-temurin:${JAVA_VERSION}-jdk-jammy

LABEL maintainer="javier.godino@acqua.net.ar"

ARG MULE_VERSION=4.12.0
ARG MULE_REPO=https://repository.mulesoft.org/nexus/content/repositories/releases/org/mule/distributions/mule-standalone
ARG mule_env=dev

ENV MULE_HOME=/opt/mule/mule-standalone \
    MULE_INIT_HEAP_MB=256 \
    MULE_MAX_HEAP_MB=1024 \
    mule_env=${mule_env} \
    DEBIAN_FRONTEND=noninteractive \
    TZ=America/Buenos_Aires \
    LANG=es_AR.UTF-8 \
    LANGUAGE=es_AR.UTF-8 \
    LC_ALL=es_AR.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget iproute2 net-tools bzip2 unzip curl locales jq tzdata ca-certificates \
        libfreetype6 libfontconfig1 fontconfig fonts-dejavu fonts-dejavu-extra \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && dpkg-reconfigure -f noninteractive tzdata \
    && locale-gen es_AR.UTF-8 && update-locale LANG=es_AR.UTF-8

# Re-fetched on every build: changes (new release) invalidate the download layer below
ADD ${MULE_REPO}/maven-metadata.xml /tmp/mule-metadata.xml

RUN set -eu; \
    v="${MULE_VERSION}"; \
    if [ "$v" = latest ]; then v=$(sed -n 's:.*<release>\(.*\)</release>.*:\1:p' /tmp/mule-metadata.xml); fi; \
    echo "Installing Mule CE $v"; \
    curl -fsSL -o /tmp/mule.tar.gz "${MULE_REPO}/$v/mule-standalone-$v.tar.gz"; \
    echo "$(curl -fsSL "${MULE_REPO}/$v/mule-standalone-$v.tar.gz.sha1" | cut -c1-40)  /tmp/mule.tar.gz" | sha1sum -c -; \
    mkdir -p /opt/mule; \
    tar xzf /tmp/mule.tar.gz -C /opt/mule; \
    mv /opt/mule/mule-standalone-* "$MULE_HOME"; \
    echo "$v" > /opt/mule/mule-version.txt; \
    rm /tmp/mule.tar.gz /tmp/mule-metadata.xml; \
    date +%Y%m%d%H%M%S > /opt/mule/build-date.txt; \
    mkdir -p /tmp/sota /home/sota/mule/logs

# Our JVM/heap settings are appended to the stock wrapper.conf (any runtime version, no replaced file)
COPY images/wrapper-platform.conf images/tls-default.conf ${MULE_HOME}/conf/
RUN cat "$MULE_HOME/conf/wrapper-platform.conf" >> "$MULE_HOME/conf/wrapper.conf"

COPY docker-entrypoint.sh docker-entrypoint-stop.sh /
COPY entypoints/* /docker-entrypoint.d/
RUN chmod +x /docker-entrypoint.sh /docker-entrypoint-stop.sh /docker-entrypoint.d/*.sh

VOLUME ["/opt/mule/mule-standalone/logs", "/opt/mule/mule-standalone/apps", "/home/sota/mule/logs"]

EXPOSE 8081 8082

ENTRYPOINT ["/docker-entrypoint.sh"]
