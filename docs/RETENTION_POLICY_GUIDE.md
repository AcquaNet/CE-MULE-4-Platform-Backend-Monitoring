# Log and Trace Retention (OpenSearch ISM)

Fluent Bit writes one index per day (`mule-logs-YYYY.MM.DD`, `logstash-YYYY.MM.DD`) and Jaeger does the same
(`jaeger-span-YYYY-MM-DD`, `jaeger-service-YYYY-MM-DD`). Retention is an OpenSearch Index State Management (ISM)
policy that deletes each daily index a number of days after it was created. There is no rollover: the indices are
already daily, and rollover would need write aliases these writers don't use.

## Apply

```bash
./config/scripts/ilm/setup-retention-policy.sh            # create/update the policies
./config/scripts/ilm/setup-retention-policy.sh --verify   # ... and list which index has which policy
```

The script is idempotent: change a value in `.env` and run it again. It

- creates or updates three policies, each with an `ism_template`, so every new daily index gets its policy
  automatically;
- attaches the policy to existing indices, and moves indices on an older version of the policy to the new one;
- sets how often ISM checks indices (`ISM_POLL_INTERVAL`).

| Policy | Indices | `.env` variable | Default |
|---|---|---|---|
| `mule-logs-retention` | `mule-logs-*` | `MULE_LOGS_RETENTION_DAYS` | 730 |
| `logstash-retention` | `logstash-*` | `LOGSTASH_LOGS_RETENTION_DAYS` | 730 |
| `jaeger-retention` | `jaeger-span-*`, `jaeger-service-*` | `JAEGER_RETENTION_DAYS` | 30 |
| (ISM job interval) | | `ISM_POLL_INTERVAL` | `10m` |

Run it once after a fresh install (the policies live in OpenSearch, so `docker compose down -v` removes them).

## Check

```bash
set -a; . ./.env; set +a
O="http://localhost:9080/opensearch"; A="admin:$OPENSEARCH_ADMIN_PASSWORD"
curl -s -u "$A" "$O/_plugins/_ism/policies/mule-logs-retention?pretty"   # the policy
curl -s -u "$A" "$O/_plugins/_ism/explain/mule-logs-*?pretty"            # state of each index
curl -s -u "$A" "$O/_cat/indices/mule-logs-*,jaeger-*?v&s=index"         # what exists, sizes
```

An index is deleted on the first ISM run after it is older than the limit, so deletion can lag by up to
`ISM_POLL_INTERVAL` (plus ISM's own jitter).

Snapshots taken by the backup scripts are not affected by these policies; they have their own retention
(`BACKUP_RETENTION_DAYS`, see [BACKUP_SETUP.md](BACKUP_SETUP.md)).
