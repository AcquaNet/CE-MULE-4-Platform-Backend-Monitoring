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

Grafana is provisioned from `config/grafana/provisioning/` (Prometheus datasource; folder Platform: APISIX and Mule
JVM dashboards).

### Mule JVM

The Mule workers aren't scraped: the agent in each app (otel-mule4-agent) **pushes** JVM metrics every 15 s over
OTLP to Prometheus' OTLP receiver (`--web.enable-otlp-receiver`). Metric names as Prometheus stores them:

| Metric | What |
|---|---|
| `jvm_memory_used_bytes`, `jvm_memory_committed_bytes`, `jvm_memory_limit_bytes` | per pool (`jvm_memory_pool_name`), `jvm_memory_type` heap / non_heap |
| `jvm_gc_duration_seconds_*` | GC pauses (histogram, per `jvm_gc_name`) |
| `jvm_thread_count`, `jvm_class_count`, `jvm_cpu_recent_utilization_ratio`, `jvm_cpu_time_seconds_total` | threads, classes, CPU |

Labels: `job` = app name, `worker_id` = container, `rm_pool`, `deployment_environment`. Apps sharing a worker report
the same JVM, so the **Mule JVM** dashboard shows `max by (worker_id)`. Filters at the top: **App** (label `job`)
and **Worker** (only the workers running the chosen apps).

Unlike CloudHub, apps here can share workers (an app goes to every worker of its pool by default), and a shared JVM
can't be split per app: every app on `mule-default-1` reports the same heap/CPU/GC. The top row says which case you
are looking at: **Shared workers** (orange when > 0: workers of the chosen apps that also run other apps), **Workers
of the chosen apps** (apps per worker, orange from 2) and **Apps on those workers** (every app on them, including ones
outside the App filter). For per-app numbers give the app its own pool (dedicated workers, as on CloudHub). Workers on nodes and CloudHub apps send to
`https://<gateway>:9443/otlp/v1/metrics` (`x-otlp-token`); an app outside the platform opts in with
`-Dotel.metrics.exporter=otlp` (the agent's default is `none`). No monitoring/alerting profile: workers get
`OTEL_METRICS_EXPORTER=none`.

The Runtime Manager's app **Overview** shows the same data for that app's workers (Workers table: Heap used / limit,
highlighted from 85%, CPU, GC time over the last 5 min), queried from Prometheus (`RM_PROMETHEUS_URL`).

```bash
curl -sk -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://localhost:9443/prometheus/api/v1/query?query=jvm_memory_used_bytes%7Bjvm_memory_type%3D%22heap%22%7D"
```

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
