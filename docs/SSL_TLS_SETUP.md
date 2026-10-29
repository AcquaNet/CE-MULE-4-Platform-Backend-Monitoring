# SSL/TLS

TLS terminates at APISIX on **9443**, which is always on. Behind the gateway, traffic stays on the Docker network.

| Where | Certificate | Trust |
|-------|-------------|-------|
| Gateway 9443 | `certs/apisix/apisix.crt` + `apisix.key` | local CA `certs/ca/ca.crt` (default), your own CA, or Let's Encrypt |
| OpenSearch 9200 (internal) | per-install self-signed node cert, in the `opensearch-data` volume | internal clients don't verify it; not published |
| Node agent 7443 (other servers) | self-signed, made by `node/install-node.sh` | pinned by SHA-256 fingerprint in the Runtime Manager |
| Log intake 9100 | none (plain TCP) | token per event; restrict by IP or VPN |

## Default: local CA (nothing to do)

On its first start, `config/apisix/start.sh` sees that `certs/apisix/apisix.{crt,key}` is missing and creates:
- `certs/ca/ca.crt` + `ca.key`: "CE Platform Local CA" (RSA 4096, 10 years). Created only if `ca.key` doesn't exist.
- `certs/apisix/apisix.crt` + `apisix.key`: RSA 2048, 825 days, SANs `localhost`, `apisix`, `127.0.0.1` plus
  `GATEWAY_HOSTNAMES`, with `keyUsage digitalSignature, keyEncipherment` and `extendedKeyUsage serverAuth`.

At every render, `start.sh` injects the certificate into the live config (`ssls:`; it is never stored in
`apisix.yaml`). The SNIs are every DNS name in the certificate. Clients that send no SNI (plain IPs) get it through
`ssl.fallback_sni: localhost`. Protocols are TLSv1.2 and TLSv1.3, with HTTP/2. When the files change (renewal,
replacement), APISIX picks them up within about 2 s.

Trust the local CA on the machines that call the gateway:

```bash
curl --cacert certs/ca/ca.crt https://localhost:9443/runtime-manager/      # Windows curl: add --ssl-no-revoke
keytool -importcert -alias ce-platform -file certs/ca/ca.crt -keystore truststore.p12 -storepass changeit   # Java clients
```

Browsers: import `certs/ca/ca.crt` as a trusted root (Windows: `certmgr.msc` > Trusted Root Certification
Authorities; macOS: Keychain, "Always Trust"; Linux: `/usr/local/share/ca-certificates/` +
`update-ca-certificates`).

`certs/` is git-ignored. Never commit `ca.key` or `apisix.key`.

## Other names and IPs: GATEWAY_HOSTNAMES

When other machines (worker nodes, users on the LAN) reach the platform at a name or IP other than `localhost`,
list it in `.env`:

```env
GATEWAY_HOSTNAMES=10.0.0.10,platform.example.local
```

Then run `./install.sh`. APISIX is recreated, and `start.sh` re-issues the gateway certificate from the same
local CA with the extra SANs, so clients that already trust `ca.crt` keep working. This happens only for a
certificate issued by the local CA. A replaced certificate (your own CA, Let's Encrypt) is never touched.

## Your own domain: generate-certs.sh

`config/scripts/setup/generate-certs.sh` is a shortcut for the steps above. It edits `.env` and the `certs/`
files, then recreates APISIX, and `start.sh` issues the certificate from the local CA.

```bash
./config/scripts/setup/generate-certs.sh --domain mydomain.local          # adds it (comma list ok) to GATEWAY_HOSTNAMES, re-issues
./config/scripts/setup/generate-certs.sh --force                          # new gateway certificate, same CA
./config/scripts/setup/generate-certs.sh --force --new-ca                 # new CA too: every client and node must trust the new ca.crt
```

The script prints the subject and SANs of the resulting certificate. If you have a certificate from your company
CA, copy it to `certs/apisix/apisix.crt` (full chain) and the key to `apisix.key` (mode 644) instead.

## Public certificate: Let's Encrypt

Use one when CloudHub or other outside clients connect: they don't trust the local CA. Requirements: a DNS name
pointing at the server, and port 80 reachable for the HTTP challenge.

```bash
./config/scripts/setup/setup-letsencrypt.sh --domain platform.example.com --email admin@example.com
#   --staging                     test against Let's Encrypt staging first
#   --standalone | --webroot PATH challenge mode (standalone stops APISIX briefly)
```

The script copies `fullchain.pem` to `certs/apisix/apisix.crt` and `privkey.pem` to `apisix.key`, and sets the key
to 644: APISIX runs as non-root and must be able to read it. It also writes `scripts/renew-letsencrypt.sh` (run it
from cron) and `scripts/copy-certs.sh`. APISIX reloads renewed files by itself.

## Key usage

Server certificates need `keyUsage = digitalSignature, keyEncipherment`. Chrome rejects RSA server certificates
without `digitalSignature` (`ERR_SSL_KEY_USAGE_INCOMPATIBLE`). `start.sh` sets it on the certificates it issues. Check
any certificate you bring yourself:

```bash
openssl x509 -in certs/apisix/apisix.crt -noout -subject -issuer -dates -ext subjectAltName,keyUsage
openssl s_client -connect localhost:9443 -servername localhost </dev/null 2>/dev/null | openssl x509 -noout -subject -dates
```

## OpenSearch's internal certificate

`scripts/opensearch-start.sh` creates a self-signed node certificate with `keytool` (CN `opensearch`, SANs
`opensearch`, `localhost`, `127.0.0.1`) on the first start. It is stored in the data volume (`data/.certs`) and
used for both transport and HTTP. No demo certificates are installed. Fluent Bit, Jaeger, Dashboards, the exporter
and APISIX connect over HTTPS without verifying it. This is acceptable because 9200 is reachable only on the
internal network. Wiping `opensearch-data` creates a new one.

## Worker nodes

- **Runtime Manager to node agent (7443):** the agent's self-signed certificate is pinned by the SHA-256
  fingerprint that `install-node.sh` prints. No CA is involved, and a mismatch is refused.
- **Node workers to the gateway (9443, `/otlp` traces):** the Runtime Manager gives remote workers the platform CA
  as `PLATFORM_CA_PEM`, and the worker start script adds it to the JVM truststore. The address the node uses must
  be in the gateway certificate: set `GATEWAY_HOSTNAMES`.
- Logs from nodes go to `<gateway>:9100` over plain TCP. Keep platform and nodes on a private network.

See [node/README.md](../node/README.md).

## CloudHub

CloudHub sends traces to `https://<gateway>:9443/otlp` (header `x-otlp-token`) and logs to `<gateway>:9100`. It
needs a publicly trusted certificate on 9443 (Let's Encrypt above), and its egress IPs allowed on 9443 and 9100.
Properties: [08-logging-integration.md](setup/08-logging-integration.md#cloudhub-deployment).

## Problems

| Symptom | Fix |
|---------|-----|
| `WARN: /certs/apisix/apisix.crt not found, HTTPS on 9443 disabled` | `certs/` not writable, or the files were removed: `docker compose restart apisix` recreates them |
| HTTPS stops after a certificate change | key permissions: `chmod 644 certs/apisix/apisix.key` |
| `unable to get local issuer certificate` | the client doesn't trust `certs/ca/ca.crt` |
| Name mismatch from a node or LAN client | add the address to `GATEWAY_HOSTNAMES`, then `./install.sh` |
| Windows curl `CRYPT_E_NO_REVOCATION_CHECK` | `--ssl-no-revoke` |
