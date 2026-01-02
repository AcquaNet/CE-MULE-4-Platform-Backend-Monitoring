# Log Retention Policy Configuration Guide

This guide explains how to configure automatic log retention policies for your ElasticSearch indices in production environments.

## Quick Start

### Option 1: Configure via .env File (Recommended)

Edit your `.env` file to set retention periods:

```bash
# Enable ILM
ILM_ENABLED=true

# Retention periods (in days)
MULE_LOGS_RETENTION_DAYS=730        # 2 years (default)
LOGSTASH_LOGS_RETENTION_DAYS=730    # 2 years (default)

# Rollover settings
ROLLOVER_SIZE=1gb                   # Rollover at 1GB
ROLLOVER_MAX_AGE=1d                 # Rollover daily
```

Then run the setup script:

```bash
./scripts/setup-retention-policy.sh
```

**Example configurations:**

```bash
# Development (short retention)
MULE_LOGS_RETENTION_DAYS=30         # 1 month
LOGSTASH_LOGS_RETENTION_DAYS=14     # 2 weeks
ROLLOVER_SIZE=500mb

# Production (long retention)
MULE_LOGS_RETENTION_DAYS=365        # 1 year
LOGSTASH_LOGS_RETENTION_DAYS=90     # 3 months
ROLLOVER_SIZE=5gb
```

### Option 2: Use Default Settings

Run the setup script without customization (uses defaults from `.env.example`):

```bash
./scripts/setup-retention-policy.sh
```

Default: 2 years retention, 1GB rollover

### Option 3: Use Kibana UI

1. Navigate to: **http://localhost:9080/kibana** (via APISIX)
2. Go to: **☰ Menu → Management → Stack Management**
3. Under **Data**, click **Index Lifecycle Policies**
4. Click **Create policy** and configure retention rules
5. Apply policies to index templates under **Index Management → Index Templates**

## What the Script Does

The automated script configures Index Lifecycle Management (ILM) policies that:

1. **Automatically delete old logs** after the specified retention period
2. **Rollover indices daily** or when they reach the configured size (default 1GB)
3. **Optimize performance** by prioritizing hot (recent) data
4. **Apply to all future indices** via index templates

## Default Configuration

| Index Pattern | Retention Period | Rollover Size | Policy Name |
|--------------|------------------|---------------|-------------|
| `mule-logs-*` | 2 years (730 days) | 1GB | `mule-logs-policy` |
| `logstash-*` | 2 years (730 days) | 1GB | `logstash-logs-policy` |

## How It Works

### Index Lifecycle Phases

1. **Hot Phase** (Active indices)
   - New data is written here
   - Highest priority for query performance
   - Rollovers daily or at 1GB (configurable)

2. **Delete Phase** (After retention period)
   - Indices older than retention period are automatically deleted
   - Frees up disk space

### Example Timeline

For a 2-year retention policy:

```
Day 0:   mule-logs-2025.12.26 created → HOT phase
Day 1:   mule-logs-2025.12.27 created → mule-logs-2025.12.26 becomes read-only
Day 730: mule-logs-2025.12.26 → DELETED automatically (2 years later)
```

## Verifying Configuration

### Check ILM Policies via API

```bash
# List all ILM policies
curl http://localhost:9080/elasticsearch/_ilm/policy?pretty

# Check specific policy
curl http://localhost:9080/elasticsearch/_ilm/policy/mule-logs-policy?pretty
```

### Check in Kibana

1. Open: **http://localhost:9080/kibana**
2. Go to: **Management → Stack Management → Index Lifecycle Policies**
3. You should see:
   - `mule-logs-policy`
   - `logstash-logs-policy`

### View Index Status

```bash
# List all indices with ILM status
curl http://localhost:9080/elasticsearch/_cat/indices?v&h=index,docs.count,store.size,creation.date.string

# Check ILM explain for specific index
curl http://localhost:9080/elasticsearch/mule-logs-*/_ilm/explain?pretty
```

## Modifying Retention Policies

### Via .env File (Recommended)

Edit your `.env` file with new values and re-run the script:

```bash
# Edit .env file
nano .env

# Update values:
MULE_LOGS_RETENTION_DAYS=365    # 1 year
LOGSTASH_LOGS_RETENTION_DAYS=90 # 3 months
ROLLOVER_SIZE=5gb               # 5GB rollover

# Apply changes
./scripts/setup-retention-policy.sh
```

This will update the existing policies without affecting current data.

### Via Kibana UI

1. Go to: **Management → Stack Management → Index Lifecycle Policies**
2. Click on the policy name (e.g., `mule-logs-policy`)
3. Click **Edit policy**
4. Modify the **Delete phase** → **Timing for delete phase**
5. Click **Save policy**

### Via API (Manual)

Update the policy directly:

```bash
curl -X PUT "http://localhost:9080/elasticsearch/_ilm/policy/mule-logs-policy" \
  -H 'Content-Type: application/json' \
  -d '{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_age": "1d",
            "max_primary_shard_size": "1gb"
          }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'
```

## Advanced Configuration

### Adding Warm/Cold Phases (Cost Optimization)

For larger deployments, you can add intermediate phases:

```json
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_age": "1d",
            "max_primary_shard_size": "1gb"
          },
          "set_priority": {
            "priority": 100
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "set_priority": {
            "priority": 50
          },
          "allocate": {
            "number_of_replicas": 0
          }
        }
      },
      "cold": {
        "min_age": "14d",
        "actions": {
          "set_priority": {
            "priority": 0
          },
          "freeze": {}
        }
      },
      "delete": {
        "min_age": "30d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

### Custom Rollover Conditions

Modify rollover triggers based on your needs:

```json
"rollover": {
  "max_age": "7d",           // Rollover every 7 days
  "max_primary_shard_size": "100gb",  // Or when reaching 100GB
  "max_docs": 1000000        // Or when reaching 1M documents
}
```

## Monitoring

### Check Policy Execution

Monitor ILM execution in Kibana:

1. Go to: **Management → Stack Management → Index Lifecycle Policies**
2. Click on a policy to see which indices are using it
3. View the lifecycle phase of each index

### Check Deleted Indices

View ILM actions in ElasticSearch logs:

```bash
docker-compose logs elasticsearch | grep -i "ilm"
```

### Disk Space Monitoring

Monitor disk usage to ensure policies are working:

```bash
# Check cluster disk usage
curl http://localhost:9080/elasticsearch/_cat/allocation?v

# Check index sizes
curl http://localhost:9080/elasticsearch/_cat/indices?v&h=index,store.size&s=store.size:desc
```

## Troubleshooting

### Policies Not Applying

**Issue**: New indices don't have ILM policy attached

**Solution**: Ensure index templates are correctly configured:

```bash
# Check index template
curl http://localhost:9080/elasticsearch/_index_template/mule-logs-template?pretty

# Recreate template
./scripts/setup-retention-policy.sh
```

### Indices Not Being Deleted

**Issue**: Old indices remain after retention period

**Solution**: Check ILM execution status:

```bash
# Check if ILM is enabled
curl http://localhost:9080/elasticsearch/_ilm/status?pretty

# If stopped, start it
curl -X POST http://localhost:9080/elasticsearch/_ilm/start

# Check specific index status
curl http://localhost:9080/elasticsearch/mule-logs-2025.12.01/_ilm/explain?pretty
```

### Manual Index Deletion

**Emergency cleanup** (if ILM is not working):

```bash
# Delete indices older than 30 days
# WARNING: This permanently deletes data!

# List old indices first
curl http://localhost:9080/elasticsearch/_cat/indices/mule-logs-* | awk '{print $3}' | grep "2025.11"

# Delete specific index
curl -X DELETE http://localhost:9080/elasticsearch/mule-logs-2025.11.26
```

## Production Best Practices

1. **Set Conservative Retention Periods Initially**
   - Start with longer retention (60-90 days)
   - Monitor disk usage and adjust downward if needed
   - Easier to reduce than to recover deleted data

2. **Monitor Disk Space Regularly**
   - Set up alerts for disk usage > 80%
   - Review retention policies quarterly

3. **Different Policies for Different Log Types**
   - Error logs: Keep longer (90+ days)
   - Debug logs: Keep shorter (7-14 days)
   - Audit logs: Keep longest (365+ days, or use archives)

4. **Test Before Production**
   - Test retention policies in dev/staging first
   - Verify deletion timing is correct
   - Ensure no critical data is lost

5. **Document Your Policies**
   - Keep a record of retention periods for compliance
   - Document any exceptions or special cases
   - Review policies during security audits

## Compliance Considerations

### GDPR / Data Privacy

- Set appropriate retention for personal data (typically 30-90 days)
- Implement data anonymization if longer retention needed
- Document retention policies for audit purposes

### SOC 2 / Industry Standards

- Security logs: Typically 90-365 days
- Application logs: 30-90 days
- Audit trails: 1-7 years (depending on industry)

### Custom Requirements

For specific compliance needs, adjust retention periods accordingly and document the reasoning in your security policies.

## Summary

- **Configuration**: All ILM settings are configured in `.env` file for consistency
- **Default Retention**: 2 years (730 days) for both Mule and Logstash logs
- **Setup**: Run `./scripts/setup-retention-policy.sh` after configuring `.env`
- **Visual Management**: Use Kibana UI at **http://localhost:9080/kibana → Management → Index Lifecycle Policies**
- **Monitoring**: Check **Stack Management → Index Lifecycle Policies** in Kibana
- **Verification**: Run `curl http://localhost:9080/elasticsearch/_ilm/policy?pretty`

### Quick Reference

**Configuration file:** `.env`

**Required settings:**
```bash
ILM_ENABLED=true
MULE_LOGS_RETENTION_DAYS=730
LOGSTASH_LOGS_RETENTION_DAYS=730
ROLLOVER_SIZE=1gb
ROLLOVER_MAX_AGE=1d
```

**Setup command:**
```bash
./scripts/setup-retention-policy.sh --verify
```

For questions or issues, refer to the [ElasticSearch ILM documentation](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/index-lifecycle-management.html).
