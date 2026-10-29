#!/usr/bin/env bash
# Make this server a Runtime Manager worker node:  ./install-node.sh
# Needs Docker + Compose v2. Creates node/.env (NODE_TOKEN) on first run, starts the node agent and prints
# what to enter in the Runtime Manager (Runtime pools > Nodes > Add node). Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

docker info >/dev/null 2>&1 || die "Docker is not running on this server."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required ('docker compose ...')."

if [ ! -f .env ]; then
    token=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    # worker ports skip APISIX's auth: publish them on one (private) IP, not every interface
    bind=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    printf 'NODE_TOKEN=%s\n# private IP of this server that the platform reaches workers on ("" = all interfaces: avoid)\nNODE_BIND_IP=%s\nNODE_AGENT_PORT=7443\n# platform (APISIX) IP: the only source allowed to reach the worker ports 18000-18999 (iptables DOCKER-USER)\nNODE_ALLOW_FROM=\n' "$token" "$bind" > .env
    chmod 600 .env
    say "Created node/.env with a new NODE_TOKEN"
fi
env_get() { sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r'; }

say "Starting the node agent"
docker compose up -d --build --wait --wait-timeout 300

# Worker ports have no auth of their own (APISIX's is skipped when called directly): only the platform may reach them.
# Docker's DNAT has already rewritten the port when DOCKER-USER runs, so match the original one via conntrack.
# ponytail: not persistent across reboots; re-run this script (or save the rule with iptables-persistent)
allow=$(env_get NODE_ALLOW_FROM)
if [ -n "$allow" ]; then
    sudo=""; [ "$(id -u)" = 0 ] || sudo=sudo
    # ctorigsrc, not -s: the workers' replies (source = container IP) belong to the same connection and must pass
    rule="-p tcp -m conntrack --ctorigdstport 18000:18999 ! --ctorigsrc $allow -j DROP"
    $sudo iptables -C DOCKER-USER $rule 2>/dev/null || $sudo iptables -I DOCKER-USER $rule         || die "could not add the iptables DOCKER-USER rule (needs root and iptables)"
    say "Worker ports 18000-18999 accept only $allow"
else
    printf '[1;33mWARNING:[0m NODE_ALLOW_FROM is empty in node/.env: any host that reaches this server can call the workers directly (no gateway auth)
' >&2
fi

fp=""
for _ in $(seq 1 30); do
    fp=$(docker compose logs rm-node-agent 2>/dev/null | grep -o 'NODE-FINGERPRINT sha256:[0-9a-f]*' | tail -n 1 | cut -d' ' -f2 || true)
    [ -n "$fp" ] && break
    sleep 1
done
[ -n "$fp" ] || die "the agent did not report its certificate fingerprint (docker compose logs rm-node-agent)"

host=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
[ -n "$host" ] || host=$(hostname)
port=$(env_get NODE_AGENT_PORT); port=${port:-7443}
bind=$(env_get NODE_BIND_IP); [ -n "$bind" ] && host=$bind
[ -n "$bind" ] || printf '[1;33mWARNING:[0m NODE_BIND_IP is empty: worker ports are open on every interface of this server
' >&2

say "Node ready. Register it in the Runtime Manager (Runtime pools > Nodes > Add node, or PUT /api/nodes/<name>):"
cat <<EOF

  Name         a short name, e.g. $(hostname | tr 'A-Z_' 'a-z-' | cut -c1-30)
  Address      https://$host:$port     (this server as the platform reaches it)
  Token        $(env_get NODE_TOKEN)
  Fingerprint  $fp
  Gateway      the platform server's address as THIS server reaches it (must be in its gateway
               certificate: GATEWAY_HOSTNAMES in the platform's .env)

  Network:
    platform -> this server   TCP $port (agent) and 18000-18999 (worker HTTP ports, APISIX)
    this server -> platform   TCP 9443 (traces, /otlp) and 9100 (logs)
  Keep these on a private network/VPN: APISIX talks plain HTTP to the workers.

EOF
