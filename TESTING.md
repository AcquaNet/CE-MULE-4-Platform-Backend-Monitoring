# Testing

One command runs everything, from the repository root, with the platform up (`./install.sh`):

```bash
tests/run.sh            # every suite (~30-40 min: the Runtime Manager suites create pools and deploy apps)
tests/run.sh unit       # self-tests only, no running stack needed (seconds)
tests/run.sh stack      # or: api | ui | home  -> one live suite
```

Each suite prints one `PASS`/`FAIL`/`SKIP` line per check and a summary, writes its full output to
`tests/out/<suite>.log` (failure screenshots of the browser suites go there too), and exits 1 on any failure.
Every suite also runs on its own, e.g. `python tests/test_stack.py`.

## Suites

| Suite | File | Needs | What it covers |
|-------|------|-------|----------------|
| unit | `mule/runtime-manager/test_app.py`, `node/agent/test_agent.py`, `config/log-archiver/test_archiver.py`, `config/apisix/test_home_link.py`, `otel-mule4-agent` (`mvn test`, skipped without Maven) | Python, Java | Runtime Manager logic with Docker/Maven faked (pools, placement, properties, Maven updates, nodes, APISIX rendering, API docs vs routes), node agent allowlist, log-archiver (index selection, archive count check, SigV4 vector), agent cross-app trace context and JVM metrics, worker metrics env per profile, Grafana dashboards parse, Home-link rule (page regex in sync, which paths get it); plus `docker compose config` for every profile and `bash -n` on every script |
| stack | `tests/test_stack.py` | live stack | containers healthy, published ports, TLS (CA chain, SANs, keyUsage, HTTP/2), every gateway route by auth case (none, admin, developer, other client, garbage, forged headers), 9443 vs 9080, Keycloak (brute force, grants, claims, master realm settings), SSO for admin and developer, Mule API (404/405, round robin), log ingestion (token, routing, tenant cleaning), tenant from token end to end, DLS and `manage-tenants.sh`, OpenSearch settings/log-archiver/demo users, OTLP intake to Jaeger, Prometheus targets and rules, Grafana, ActiveMQ (console, AMQP auth), MySQL, ops scripts (health, backup/restore on a throwaway index) |
| api | `tests/test_rm_api.py` | live stack | every Runtime Manager endpoint in `openapi.json` with its error paths: auth (Basic, API tokens, revocation), pools (create, validation, rolling edit, heap/JVM flags in the worker, delete guard), apps (Maven and jar deploys, properties incl. secure ones at rest and in the worker, update modes, check, restart, overview, logs, worker placement, gateway routes), settings, nodes (a real node agent on its own Docker-in-Docker) |
| home | `tests/test_home_ui.py` | live stack, Playwright | home page per role (cards hidden/greyed/clickable, one sign-in for every tool), Keycloak consoles, each tool's UI renders, sign-out, phone width |
| ui | `tests/test_rm_ui.py` | live stack, Playwright | the Runtime Manager in a browser: every button, checkbox, radio, select, link and dialog (sign-in and role refusal, navigation and deep links, dark mode, phone width, pools and nodes, deploy dialog validation, Maven and jar deploys, updates switch/check/update, restart, properties editor, overview ranges and charts, log search in both modes, settings and discard, delete confirms, API tokens, docs links, update interval, sign-out). States that can't be produced safely (a pool in error, a failed update check, tracing off) are rendered from mocked responses |

Checks for a compose profile that is off in `.env` are skipped, not failed.

## Test resources and cleanup

The live suites create throwaway resources and delete them at the start and end of every run (a crashed run is
cleaned by the next one): `t-stack-*` (Keycloak users, tenants, indices), `t-api-*` and `t-ui-*` (pools, apps,
nodes, tokens, node-agent containers). They never modify the `default` pool, the `ce-mule-base` app or real users.
The Runtime Manager suites briefly add 2-4 Mule workers: allow ~3 GB of free memory for Docker.

## Browser suites

`tests/run.sh` creates `tests/.venv` with Playwright (`tests/requirements.txt`) on first use and drives the installed
Chrome, or Playwright's own Chromium where Chrome isn't installed (it installs it then). Run one by hand with
`tests/.venv/Scripts/python tests/test_rm_ui.py` (Windows) or `tests/.venv/bin/python ...`.

## Writing checks

Shared helpers are in `tests/lib.py` (`.env` loading, `check`/`skip`/`section`, HTTP with Basic/Bearer, Keycloak
tokens, Runtime Manager/OpenSearch calls, waits). Never print secret values; a failing check prints a truncated detail.
