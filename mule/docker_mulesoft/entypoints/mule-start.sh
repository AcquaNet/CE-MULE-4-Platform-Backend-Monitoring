#!/bin/bash
echo '---------------------------------------------'
echo 'Starting Mule Server'
echo '          Mule CE: ' $(cat /opt/mule/mule-version.txt) '  build date: ' $(cat /opt/mule/build-date.txt)
echo '          Mule Environment: ' ${mule_env}
echo '---------------------------------------------'
# The healthcheck greps mule.log for "Mule is up and kicking": move the previous run's log aside so a
# restart isn't reported healthy before Mule is up.
mv -f "$MULE_HOME/logs/mule.log" "$MULE_HOME/logs/mule.log.prev" 2>/dev/null
# Workers on other servers (Runtime Manager nodes) reach the platform gateway over HTTPS signed by its
# local CA: add it to a copy of the JVM truststore (public CAs stay trusted).
if [ -n "${PLATFORM_CA_PEM:-}" ]; then
    cacerts=$(find "$JAVA_HOME" -name cacerts -path '*security*' | head -n 1)
    cp "$cacerts" /tmp/truststore && printf '%s\n' "$PLATFORM_CA_PEM" > /tmp/platform-ca.pem &&
        keytool -importcert -noprompt -alias platform-ca -file /tmp/platform-ca.pem -keystore /tmp/truststore \
            -storepass changeit >/dev/null 2>&1 &&
        MULE_ARGS="$MULE_ARGS -M-Djavax.net.ssl.trustStore=/tmp/truststore -M-Djavax.net.ssl.trustStorePassword=changeit"
fi
# -M passes JVM flags (any Mule version). Metaspace: every redeploy leaks some in CE and the Runtime Manager
# redeploys on auto-update; 512m (stock 256m, last flag wins). ponytail: raises the ceiling, a restart reclaims it
# -AlwaysPreTouch: stock wrapper.conf touches the whole initial heap at boot, so it all counts as used at once
# MULE_ARGS: the runtime pool's JVM options (set by the Runtime Manager), last so they win. The pool's heap
# comes in as MULE_INIT_HEAP_MB / MULE_MAX_HEAP_MB (wrapper-platform.conf).
# shellcheck disable=SC2086 # word-split on purpose: one -M<option> per word, options contain no spaces
exec "$MULE_HOME/bin/mule" -dmule_env=${mule_env} \
    -M-Dmule.verbose.exceptions=true -M-Djava.awt.headless=true -M-XX:MaxMetaspaceSize=512m \
    -M-XX:-AlwaysPreTouch $MULE_ARGS
