# Monitoring and Alerting

What runs is chosen by `COMPOSE_PROFILES` in `.env` (then `docker compose up -d` or `./install.sh`):

| Profile | Services | Access |
|---|---|---|
| `monitoring` (default) | Prometheus, Grafana | `https://localhost:9443/prometheus/` and `https://localhost:9443/grafana/`: Keycloak sign-in, realm role `admin` (no anonymous access). Grafana break-glass: `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` at `/grafana/login?disableAutoLogin=true` |
| `alerting` | Alertmanager | https://localhost:9443/alertmanager/ (admin SSO) |
| `opensearch-monitoring` | OpenSearch exporter | scraped by Prometheus; OpenSearch is in this profile too, so it works alone |

Don't use `docker compose --profile x up` for this: on the command line `--profile` replaces `COMPOSE_PROFILES`.

## What is collected

`config/prometheus/prometheus.yml` scrapes APISIX (`apisix:9091`), Grafana, Fluent Bit (`fluent-bit:2020`),
Jaeger, Prometheus itself and, when their profiles run, the OpenSearch exporter and Alertmanager (DNS discovery: a
missing service is simply no target). Retention: `PROMETHEUS_RETENTION` (default `30d`).

Grafana is provisioned from `config/grafana/provisioning/` (Prometheus datasource, APISIX dashboard).

Alert rules are in `config/prometheus/rules/opensearch-alerts.yml`: OpenSearch cluster health, disk, JVM heap,
shards, snapshots; APISIX down/latency/errors; Jaeger; Prometheus, Grafana and Alertmanager down. Thresholds
are in the rule file itself (edit it, then reload). The OpenSearch rules use the exporter's metrics, so they
only fire with the `opensearch-monitoring` profile.

## Alert notifications

By default Alertmanager receives alerts and sends them nowhere. For e-mail:

1. Add `alerting` to `COMPOSE_PROFILES` in `.env`.
2. Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS`, `SMTP_USE_TLS` (and
   optionally `ALERT_GROUP_BY`, `ALERT_GROUP_WAIT`, `ALERT_GROUP_INTERVAL`, `ALERT_REPEAT_INTERVAL`).
3. Add the recipients in the `receivers` section of `config/alertmanager/alertmanager.yml.template` (the
   receivers are empty until you do), e.g. under `default-receiver`:
   ```yaml
   email_configs:
     - to: 'ops@example.com'
       send_resolved: true
   ```
4. Run `./config/scripts/monitoring/setup-monitoring.sh`. It renders `config/alertmanager/alertmanager.yml`
   from the template (chmod 600: it contains the SMTP password) and restarts Alertmanager.

Slack, PagerDuty or webhooks: add a receiver to the template by hand.

## Scripts

```bash
./config/scripts/monitoring/check-health.sh            # every compose healthcheck, the Mule pool workers, OpenSearch status; exit 1 on a problem
./config/scripts/monitoring/check-health.sh --watch    # refresh every 10 s
./config/scripts/monitoring/setup-monitoring.sh        # render alertmanager.yml (alerting profile) + status
./config/scripts/monitoring/setup-monitoring.sh --reload   # also restart Prometheus after editing prometheus.yml or rules
```

`check-health.sh` is suitable for cron or an external monitor: it only uses `docker` and the loopback gateway.
