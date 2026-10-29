FROM eclipse-temurin:17-jre-noble
#
# ActiveMQ Classic 5.19.x (supported line; 5.16-5.18 are end of life: Jolokia RCE CVE-2026-34197 and later).
# Stock 5.19 config, changed only where noted below (no copied conf folder to drift out of date).
#
ENV ACTIVEMQ_VERSION=5.19.11
ENV ACTIVEMQ_HOME=/opt/activemq
ENV DEBIAN_FRONTEND=noninteractive

RUN ln -fs /usr/share/zoneinfo/America/Argentina/Buenos_Aires /etc/localtime && \
    apt-get update && apt-get install -y --no-install-recommends tzdata wget locales iproute2 net-tools jq && \
    locale-gen es_ES.UTF-8 && \
    rm -rf /var/lib/apt/lists/*
ENV LANG=es_ES.UTF-8 LANGUAGE=es_ES.UTF-8 LC_ALL=es_ES.UTF-8

# current releases are on dlcdn, older ones only on archive.apache.org; the sha512 is checked either way
RUN f=apache-activemq-${ACTIVEMQ_VERSION}-bin.tar.gz; \
    for base in https://dlcdn.apache.org/activemq https://archive.apache.org/dist/activemq; do \
      wget -q "$base/${ACTIVEMQ_VERSION}/$f" && wget -q "$base/${ACTIVEMQ_VERSION}/$f.sha512" && break; rm -f "$f" "$f.sha512"; \
    done && \
    echo "$(cut -d' ' -f1 $f.sha512)  $f" | sha512sum -c - && \
    tar -xzf $f && mv apache-activemq-${ACTIVEMQ_VERSION} ${ACTIVEMQ_HOME} && rm $f $f.sha512 && \
    mkdir -p ${ACTIVEMQ_HOME}/data

# Config changes against stock:
# - web console listens on all interfaces (container; the host port is 127.0.0.1 only, APISIX proxies /activemq) and
#   its client allow list (5.19: loopback only) also takes APISIX (172.42.0.20) and the host via the published port
#   (172.42.0.1, the network gateway); every other container is refused
# - broker clients must authenticate (user from credentials.properties, written by the entrypoint)
# - transports: OpenWire 61616 + AMQP 5672 only (STOMP/MQTT/WS stay off: their frame-size DoS CVEs, unused)
RUN cd ${ACTIVEMQ_HOME}/conf && \
    sed -i 's|<property name="host" value="127.0.0.1"/>|<property name="host" value="0.0.0.0"/>|' jetty.xml && \
    for ip in 172.42.0.20 172.42.0.1; do \
      sed -i "s|^\( *\)<bean id=\"Server\" depends-on|\1<bean id=\"inetAccessInclude$ip\" class=\"org.springframework.beans.factory.config.MethodInvokingFactoryBean\" depends-on=\"inetAccessIncludeLoopbackV6\">\n\1    <property name=\"targetObject\" ref=\"inetAccessHandler\"/>\n\1    <property name=\"targetMethod\" value=\"include\"/>\n\1    <property name=\"arguments\"><list><value>$ip</value></list></property>\n\1</bean>\n&|" jetty.xml; \
    done && grep -q 'inetAccessInclude172.42.0.20' jetty.xml && \
    sed -i 's|<!-- <transportConnector name="amqp" \(.*\)/> -->|<transportConnector name="amqp" \1/>|' activemq.xml && \
    sed -i 's|^\( *\)<transportConnectors>|\1<plugins>\n\1    <simpleAuthenticationPlugin anonymousAccessAllowed="false">\n\1        <users>\n\1            <authenticationUser username="${activemq.username}" password="${activemq.password}" groups="admins"/>\n\1        </users>\n\1    </simpleAuthenticationPlugin>\n\1</plugins>\n\n&|' activemq.xml && \
    grep -q '<transportConnector name="amqp"' activemq.xml && grep -q simpleAuthenticationPlugin activemq.xml && \
    grep -q 'value="0.0.0.0"' jetty.xml && \
    useradd -r -d ${ACTIVEMQ_HOME} activemq && chown -R activemq:activemq ${ACTIVEMQ_HOME}

USER activemq
EXPOSE 61616 8161 5672
# user admin gets ACTIVEMQ_ADMIN_PASSWORD (random when unset) for the web console and the broker; the stock users
# (console user/user, broker system/manager, guest) are removed
ENTRYPOINT ["sh", "-c", "pw=${ACTIVEMQ_ADMIN_PASSWORD:-$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')}; c=${ACTIVEMQ_HOME}/conf; sed -i -e \"s|^admin:.*|admin: $pw, admin|\" -e '/^user:/d' $c/jetty-realm.properties && printf 'activemq.username=admin\\nactivemq.password=%s\\n' \"$pw\" > $c/credentials.properties && exec ${ACTIVEMQ_HOME}/bin/activemq console"]
