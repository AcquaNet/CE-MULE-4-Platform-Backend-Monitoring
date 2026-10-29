# Worker nodes (horizontal scaling)

A node is another server that hosts Mule pool workers for the platform's Runtime Manager. The node only
runs the **node agent** (~20 MB); the Runtime Manager creates, updates and removes the workers there, the
same way it does on its own server.

## Add a node

On the new server (Docker + Compose v2, a copy of this `node/` folder):

```bash
./install-node.sh
```

It creates `node/.env` (a random `NODE_TOKEN`), starts the agent and prints:

```
WARNING: NODE_ALLOW_FROM is empty in node/.env: any host that reaches this server can call the workers directly (no gateway auth)
==> Node ready. Register it in the Runtime Manager (Runtime pools > Nodes > Add node, or PUT /api/nodes/<name>):

  Name         a short name, e.g. node-b
  Address      https://10.0.0.21:7443     (this server as the platform reaches it)
  Token        577c48a3...
  Fingerprint  sha256:6b5f2194...
  Gateway      the platform server's address as THIS server reaches it (must be in its gateway
               certificate: GATEWAY_HOSTNAMES in the platform's .env)
  ...
```

With `NODE_ALLOW_FROM` set (the platform IP), the warning becomes `==> Worker ports 18000-18999 accept only <ip>`
(an iptables `DOCKER-USER` rule).

On the platform:

1. Put the platform's address as the nodes reach it into `GATEWAY_HOSTNAMES` in the root `.env`
   (e.g. `GATEWAY_HOSTNAMES=10.0.0.10`) and re-run `./install.sh`: the generated gateway certificate is
   re-issued with that name/IP (same local CA).
2. Runtime Manager > **Runtime pools > Nodes > Add node**: the values above (Gateway = that address).
   The Runtime Manager connects first and only saves a node it can reach with that token and certificate.
3. Edit a pool and give it workers on the node (*Workers per server*), e.g. 2 on this server, 2 on node-b.

The node builds the pool's runtime image itself the first time (a few minutes: Mule is downloaded there),
then the workers start and get the pool's apps. Same through the API:

```bash
curl -X PUT $RM/api/nodes/node-b -H "Authorization: Bearer $RM_TOKEN" -H "Content-Type: application/json" \
  -d '{"address": "https://10.0.0.21:7443", "token": "...", "fingerprint": "sha256:...", "gateway": "10.0.0.10"}'
curl -X PUT $RM/api/pools/default -H "Authorization: Bearer $RM_TOKEN" -H "Content-Type: application/json" \
  -d '{"mule_version": "4.12.0", "heap_mb": 1024, "nodes": {"local": 2, "node-b": 2}}'
```

## Network

| From | To | Port | What |
|------|----|------|------|
| platform | node | 7443 | Runtime Manager -> node agent (HTTPS, token, pinned cert) |
| platform | node | 18000-18999 | APISIX -> workers (each worker publishes 8081-8090 on a block of 10 ports); `NODE_ALLOW_FROM` in node/.env = platform IP, install-node.sh drops everyone else) |
| node | platform | 9443 | traces: `https://<gateway>:9443/otlp` (token `OTLP_INGEST_TOKEN`) |
| node | platform | 9100 | logs: JSON over TCP to Fluent Bit (token `LOG_INGEST_TOKEN`) |

APISIX talks plain HTTP to the workers: keep platform and nodes on a private network (VPC, VLAN, WireGuard).
`NODE_BIND_IP` in `node/.env` publishes the worker ports on that private IP only.

## Security

- The agent forwards only the Docker API calls the Runtime Manager uses, and only for its workers:
  containers named `mule-*` with label `rm.pool`, images `ce-mule-runtime:*`. No host mounts, privileged
  mode, host network or extra networks are accepted, so the token lets someone run Mule workers on the node,
  not take over the server.
- The Runtime Manager pins the agent's certificate by its SHA-256 fingerprint (no CA to manage) and stores
  the node token encrypted (`RM_SECRETS_KEY`).
- `node/.env` and `node/certs/` hold secrets and are git-ignored. New token: delete `node/.env`, re-run
  `install-node.sh`, then *Edit* the node in the Runtime Manager with the new token.

## When a node goes away

- The gateway keeps serving from the other workers (APISIX health checks drop the dead ones).
- The Runtime Manager marks the node unreachable (Nodes page), skips it for 30 s at a time, and leaves its
  workers exactly as they are: a pool change while the node is down is applied to the other servers and
  retried on the node once it answers again.
- Restarting the platform's Runtime Manager restarts its local workers but never the nodes' workers.
- Removing a node is refused while a pool still has workers on it: set its count to 0 first.

## Limits

- Per-app gateway routes only reach node workers on ports 8081-8090.
- Workers are spread by the counts you set per server; there is no automatic placement by free memory yet.
- Memory per node: the agent ~20 MB plus ~0.6 GB per idle worker (pool `heap_mb` caps a busy one).
