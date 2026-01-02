# ElasticSearch Backup Setup Guide

Complete guide for configuring and managing automated backups for the ELK stack.

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Backup Operations](#backup-operations)
- [Restore Operations](#restore-operations)
- [Automated Backups](#automated-backups)
- [Cloud Storage Setup](#cloud-storage-setup)
- [Monitoring and Troubleshooting](#monitoring-and-troubleshooting)
- [Best Practices](#best-practices)

---

## Quick Start

### 1. Configure Backup Settings

Edit your `.env` file (copy from `.env.example` if needed):

```bash
cp .env.example .env
```

Set backup configuration:

```bash
# Enable backups
BACKUP_ENABLED=true

# Backup schedule (daily at 2 AM)
BACKUP_SCHEDULE=0 2 * * *

# Retention policy
BACKUP_RETENTION_DAYS=30
BACKUP_MAX_COUNT=30  # Match retention days for daily backups

# Repository type (fs, s3, azure, gcs)
BACKUP_REPOSITORY_TYPE=fs
SNAPSHOT_REPOSITORY_PATH=/mnt/elasticsearch-backups
```

### 2. Start ElasticSearch with Backup Volume

The backup volume is automatically mounted when you start the stack:

```bash
docker-compose up -d
```

### 3. Configure Backup Repository

```bash
./scripts/configure-backup.sh --verify
```

This creates the snapshot repository in ElasticSearch.

### 4. Create Your First Backup

```bash
./scripts/backup.sh
```

### 5. Set Up Automated Backups (Optional)

```bash
./scripts/setup-backup-cron.sh
```

---

## Configuration

### Backup Settings in `.env`

#### Core Settings

```bash
# Enable/disable automated backups
BACKUP_ENABLED=true

# Cron schedule for automated backups
# Format: minute hour day month weekday
# Examples:
#   0 2 * * *        = Daily at 2:00 AM
#   0 */6 * * *      = Every 6 hours
#   0 0 * * 0        = Weekly on Sunday at midnight
#   0 3 */2 * *      = Every 2 days at 3:00 AM
BACKUP_SCHEDULE=0 2 * * *
```

#### Repository Configuration

```bash
# Repository type
# Options: fs (filesystem), s3 (AWS S3), azure (Azure Blob), gcs (Google Cloud Storage)
BACKUP_REPOSITORY_TYPE=fs

# Repository name (shown in ElasticSearch)
BACKUP_REPOSITORY_NAME=backup-repo

# Filesystem path (for fs type)
SNAPSHOT_REPOSITORY_PATH=/mnt/elasticsearch-backups
```

#### Retention Policy

```bash
# Delete snapshots older than this many days
BACKUP_RETENTION_DAYS=30

# Maximum number of snapshots to keep (regardless of age)
BACKUP_MAX_COUNT=50

# Compress snapshots (reduces storage, increases CPU usage)
BACKUP_COMPRESS=true
```

#### Index Selection

```bash
# Backup mode - what indices to include in each snapshot
# Options:
#   daily  = Only today's indices (recommended - compartmentalized, independent snapshots)
#   *      = All indices (legacy - creates interdependent snapshots)
#   Custom = Use specific pattern like "mule-logs-*"
BACKUP_INDICES=daily

# Indices to exclude from backups
BACKUP_EXCLUDE_INDICES=.monitoring-*,.watcher-*,.security-*

# Verify snapshot integrity after creation
BACKUP_VERIFY=true
```

**Important: Daily vs Full Backup Mode**

- **Daily Mode (Recommended)**: `BACKUP_INDICES=daily`
  - Backs up only the current day's indices: `mule-logs-2024.12.29`, `logstash-2024.12.29`
  - Each snapshot is self-contained and independent
  - Deleting old snapshots frees the full disk space
  - Perfect for size-based retention
  - **Example**: 30 days × 10GB/day = 300GB total (predictable)

- **Full Backup Mode**: `BACKUP_INDICES=*`
  - Backs up all indices every time
  - Snapshots share data segments (incremental)
  - Deleting old snapshots may not free much space
  - Use only if you need full historical snapshots
  - **Example**: Day 1 = 100GB, Day 2 = +5GB, Day 3 = +5GB (cumulative)

#### Notifications

```bash
# Send notifications on backup completion/failure
BACKUP_NOTIFICATIONS_ENABLED=false

# Webhook URL (Slack, Discord, custom endpoint)
BACKUP_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### Repository Types

#### Filesystem (Default)

Stores snapshots in a local directory or mounted volume.

```bash
BACKUP_REPOSITORY_TYPE=fs
SNAPSHOT_REPOSITORY_PATH=/mnt/elasticsearch-backups
BACKUP_COMPRESS=true
```

**Pros:**
- Simple setup
- No external dependencies
- Fast local access

**Cons:**
- Limited to local storage
- No off-site backup
- Vulnerable to hardware failure

**Best for:** Development, testing, small deployments

#### AWS S3

Stores snapshots in Amazon S3 bucket.

```bash
BACKUP_REPOSITORY_TYPE=s3
AWS_S3_BUCKET=my-elasticsearch-backups
AWS_S3_REGION=us-east-1
AWS_S3_BASE_PATH=elasticsearch-backups
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_S3_STORAGE_CLASS=STANDARD_IA
```

**Pros:**
- Off-site backup
- Highly durable (99.999999999%)
- Automatic encryption
- Cost-effective with IA/Glacier

**Cons:**
- Requires AWS account
- Additional costs
- Network dependency

**Best for:** Production, multi-site deployments

#### Azure Blob Storage

Stores snapshots in Azure Blob Storage.

```bash
BACKUP_REPOSITORY_TYPE=azure
AZURE_STORAGE_ACCOUNT=mystorageaccount
AZURE_STORAGE_KEY=your-storage-key
AZURE_CONTAINER=elasticsearch-backups
AZURE_BASE_PATH=
```

**Pros:**
- Azure ecosystem integration
- High durability
- Geo-redundancy options

**Cons:**
- Requires Azure account
- Additional costs

**Best for:** Azure-based infrastructure

#### Google Cloud Storage

Stores snapshots in Google Cloud Storage.

```bash
BACKUP_REPOSITORY_TYPE=gcs
GCS_BUCKET=my-elasticsearch-backups
GCS_BASE_PATH=elasticsearch-backups
GCS_CREDENTIALS_FILE=/path/to/service-account-key.json
```

**Pros:**
- GCP ecosystem integration
- High durability
- Multi-region support

**Cons:**
- Requires GCP account
- Additional costs

**Best for:** Google Cloud-based infrastructure

---

## Backup Operations

### Configure Repository

Set up the ElasticSearch snapshot repository:

```bash
# Configure repository
./scripts/configure-backup.sh

# Force recreate (deletes existing repository)
./scripts/configure-backup.sh --force

# Configure and verify
./scripts/configure-backup.sh --verify
```

**What it does:**
1. Reads configuration from `.env`
2. Creates snapshot repository in ElasticSearch
3. Optionally verifies repository accessibility

### Create Manual Backup

Create a snapshot manually:

```bash
# Auto-generated snapshot name
./scripts/backup.sh

# Custom snapshot name
./scripts/backup.sh my-backup-20241228
```

**What it does:**
1. Checks cluster health
2. Creates snapshot with configured indices
3. Waits for completion
4. Verifies snapshot integrity (if enabled)
5. Sends notification (if enabled)

**Output:**
```
════════════════════════════════════════════════════════════
   ElasticSearch Snapshot Backup
════════════════════════════════════════════════════════════

Checking ElasticSearch connectivity...
✓ Connected to ElasticSearch

Checking snapshot repository...
✓ Repository 'backup-repo' found

Backup Configuration:
  Snapshot Name: snapshot-20241228-120000
  Repository: backup-repo
  Include Indices: *
  Exclude Indices: .monitoring-*,.watcher-*,.security-*
  Verify: true

  Cluster Status: green

Creating snapshot 'snapshot-20241228-120000'...
✓ Snapshot creation started

Waiting for snapshot to complete...
(This may take a while depending on data size)

...

✓ Snapshot completed successfully

  Duration: 2m 34s
  Total Shards: 45
  Successful: 45
  Failed: 0

Verifying snapshot integrity...
✓ Snapshot verified successfully

════════════════════════════════════════════════════════════
  Backup Complete
════════════════════════════════════════════════════════════

Snapshot: snapshot-20241228-120000
Repository: backup-repo
```

### View Snapshots

List all snapshots:

```bash
curl -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo/_all?pretty"
```

View specific snapshot:

```bash
curl -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo/snapshot-20241228-120000?pretty"
```

Get snapshot status:

```bash
curl -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo/snapshot-20241228-120000/_status?pretty"
```

### Clean Up Old Snapshots

Remove snapshots based on retention policy:

```bash
# Dry run (show what would be deleted)
./scripts/backup-cleanup.sh --dry-run

# Actually delete old snapshots
./scripts/backup-cleanup.sh
```

**What it does:**
1. Fetches all snapshots
2. Identifies snapshots older than `BACKUP_RETENTION_DAYS`
3. Enforces `BACKUP_MAX_COUNT` limit
4. Deletes oldest snapshots
5. Sends notification (if enabled)

**Output:**
```
════════════════════════════════════════════════════════════
   ElasticSearch Snapshot Cleanup
════════════════════════════════════════════════════════════

Checking ElasticSearch connectivity...
✓ Connected to ElasticSearch

Fetching snapshot list...
✓ Found 45 snapshot(s)

Retention Policy:
  Maximum Age: 30 days
  Maximum Count: 50
  Cutoff Date: 2024-11-28 00:00:00

Snapshots to keep: 30
Snapshots to delete: 15
  ✗ snapshot-20241101-020000
  ✗ snapshot-20241102-020000
  ...

Delete 15 snapshot(s)? (yes/no): yes

Deleting: snapshot-20241101-020000
✓ Deleted
...

════════════════════════════════════════════════════════════
  Cleanup Complete
════════════════════════════════════════════════════════════

Summary:
  Deleted: 15 snapshot(s)
  Failed: 0 snapshot(s)
  Remaining: 30 snapshot(s)
```

---

## Restore Operations

### Restore All Indices

Restore all indices from a snapshot:

```bash
./scripts/restore.sh snapshot-20241228-120000
```

### Restore Specific Indices

Restore only specific indices:

```bash
# Single index
./scripts/restore.sh snapshot-20241228-120000 "mule-logs-2024.12.28"

# Multiple indices with wildcard
./scripts/restore.sh snapshot-20241228-120000 "mule-logs-*"

# Multiple index patterns
./scripts/restore.sh snapshot-20241228-120000 "mule-logs-*,logstash-*"
```

### Restore to Different Index Name

Manually restore with rename:

```bash
curl -X POST -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo/snapshot-20241228-120000/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "mule-logs-2024.12.28",
    "rename_pattern": "(.+)",
    "rename_replacement": "restored-$1"
  }'
```

This restores `mule-logs-2024.12.28` as `restored-mule-logs-2024.12.28`.

### Restore Process

**What happens during restore:**

1. **Validation**: Checks if snapshot exists and is valid
2. **Index Closure**: Closes existing indices with same names (if they exist)
3. **Data Transfer**: Copies data from snapshot to cluster
4. **Index Opening**: Opens restored indices
5. **Verification**: Optionally verifies data integrity

**Important Notes:**

⚠️ **Existing Indices**: Indices with the same names will be closed during restore. Make sure this is intentional.

⚠️ **Cluster Resources**: Restore operations consume cluster resources. Avoid running during peak load.

⚠️ **Partial Restore**: You can restore individual indices without affecting others.

---

## Automated Backups

### Set Up Cron Jobs

Install automated backup cron jobs:

```bash
./scripts/setup-backup-cron.sh
```

**What it installs:**

1. **Backup Job**: Runs `backup.sh` on the schedule defined in `BACKUP_SCHEDULE`
2. **Cleanup Job**: Runs `backup-cleanup.sh` daily at 3:00 AM

**Output:**
```
════════════════════════════════════════════════════════════
   Setup Automated ElasticSearch Backups
════════════════════════════════════════════════════════════

Backup Configuration:
  Enabled: true
  Schedule: 0 2 * * *
  Retention: 30 days
  Project: /mnt/c/work/Aqua/Docker ElasticSearch

Adding cron jobs...

Backup Job:
  Schedule: 0 2 * * *
  Script: /mnt/c/work/Aqua/Docker ElasticSearch/scripts/backup.sh
  Log: /mnt/c/work/Aqua/Docker ElasticSearch/logs/backup.log

Cleanup Job:
  Schedule: 0 3 * * * (daily at 3:00 AM)
  Script: /mnt/c/work/Aqua/Docker ElasticSearch/scripts/backup-cleanup.sh
  Log: /mnt/c/work/Aqua/Docker ElasticSearch/logs/cleanup.log

✓ Cron jobs installed successfully
```

### View Cron Jobs

```bash
crontab -l
```

### View Backup Logs

```bash
# Follow backup log in real-time
tail -f logs/backup.log

# Follow cleanup log in real-time
tail -f logs/cleanup.log

# View last 100 lines of backup log
tail -100 logs/backup.log
```

### Remove Cron Jobs

```bash
./scripts/setup-backup-cron.sh --remove
```

### Manual Cron Schedule Examples

```bash
# Every hour
BACKUP_SCHEDULE="0 * * * *"

# Every 6 hours
BACKUP_SCHEDULE="0 */6 * * *"

# Daily at 2:00 AM
BACKUP_SCHEDULE="0 2 * * *"

# Weekly on Sunday at midnight
BACKUP_SCHEDULE="0 0 * * 0"

# Monthly on the 1st at 3:00 AM
BACKUP_SCHEDULE="0 3 1 * *"

# Every 2 days at 3:00 AM
BACKUP_SCHEDULE="0 3 */2 * *"

# Business hours only (9 AM - 5 PM, every hour, weekdays)
BACKUP_SCHEDULE="0 9-17 * * 1-5"
```

---

## Cloud Storage Setup

### AWS S3 Setup

#### 1. Create S3 Bucket

```bash
aws s3 mb s3://my-elasticsearch-backups --region us-east-1
```

#### 2. Create IAM User

Create IAM user with S3 permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-elasticsearch-backups",
        "arn:aws:s3:::my-elasticsearch-backups/*"
      ]
    }
  ]
}
```

#### 3. Install S3 Plugin in ElasticSearch

```bash
docker exec elasticsearch bin/elasticsearch-plugin install repository-s3
docker-compose restart elasticsearch
```

#### 4. Configure AWS Credentials

Add to `.env`:

```bash
BACKUP_REPOSITORY_TYPE=s3
AWS_S3_BUCKET=my-elasticsearch-backups
AWS_S3_REGION=us-east-1
AWS_S3_BASE_PATH=elasticsearch-backups
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_S3_STORAGE_CLASS=STANDARD_IA
```

#### 5. Configure Repository

```bash
./scripts/configure-backup.sh
```

### Azure Blob Setup

#### 1. Create Storage Account

```bash
az storage account create \
  --name mystorageaccount \
  --resource-group myresourcegroup \
  --location eastus \
  --sku Standard_LRS
```

#### 2. Create Container

```bash
az storage container create \
  --name elasticsearch-backups \
  --account-name mystorageaccount
```

#### 3. Install Azure Plugin

```bash
docker exec elasticsearch bin/elasticsearch-plugin install repository-azure
docker-compose restart elasticsearch
```

#### 4. Configure Azure Credentials

Add to `.env`:

```bash
BACKUP_REPOSITORY_TYPE=azure
AZURE_STORAGE_ACCOUNT=mystorageaccount
AZURE_STORAGE_KEY=your-storage-key-here
AZURE_CONTAINER=elasticsearch-backups
AZURE_BASE_PATH=
```

#### 5. Configure Repository

```bash
./scripts/configure-backup.sh
```

### Google Cloud Storage Setup

#### 1. Create GCS Bucket

```bash
gsutil mb -l us-east1 gs://my-elasticsearch-backups
```

#### 2. Create Service Account

```bash
gcloud iam service-accounts create elasticsearch-backup \
  --display-name "ElasticSearch Backup Service Account"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:elasticsearch-backup@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

gcloud iam service-accounts keys create key.json \
  --iam-account=elasticsearch-backup@PROJECT_ID.iam.gserviceaccount.com
```

#### 3. Install GCS Plugin

```bash
docker exec elasticsearch bin/elasticsearch-plugin install repository-gcs
docker-compose restart elasticsearch
```

#### 4. Configure GCS Credentials

Add to `.env`:

```bash
BACKUP_REPOSITORY_TYPE=gcs
GCS_BUCKET=my-elasticsearch-backups
GCS_BASE_PATH=elasticsearch-backups
GCS_CREDENTIALS_FILE=/path/to/key.json
```

Mount credentials file in `docker-compose.yml`:

```yaml
elasticsearch:
  volumes:
    - ./key.json:/usr/share/elasticsearch/config/key.json:ro
```

#### 5. Configure Repository

```bash
./scripts/configure-backup.sh
```

---

## Monitoring and Troubleshooting

### Check Repository Status

```bash
curl -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo?pretty"
```

### Verify Repository

```bash
curl -X POST -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo/_verify?pretty"
```

### Monitor Backup Progress

```bash
# Get current snapshot status
curl -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/_status?pretty"

# Get specific snapshot status
curl -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo/snapshot-name/_status?pretty"
```

### Check Disk Space

```bash
# Check Docker volume usage
docker system df -v

# Check ElasticSearch data usage
curl -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_cat/allocation?v&h=node,disk.total,disk.used,disk.avail,disk.percent"

# Check backup repository size (filesystem)
docker exec elasticsearch du -sh /mnt/elasticsearch-backups
```

### Common Issues

#### Issue: "Repository verification failed"

**Cause:** ElasticSearch cannot access the repository location.

**Solution:**
1. Check volume mount in docker-compose.yml
2. Verify path permissions: `chmod 777 /path/to/backups`
3. Ensure Docker volume exists: `docker volume ls`

#### Issue: "No such file or directory" when creating snapshot

**Cause:** Repository path not configured in elasticsearch.yml

**Solution:**
Add to ElasticSearch environment in docker-compose.yml:

```yaml
elasticsearch:
  environment:
    - path.repo=/mnt/elasticsearch-backups
```

#### Issue: Backup fails with "cluster_block_exception"

**Cause:** Cluster is in read-only mode due to disk space.

**Solution:**
1. Free up disk space
2. Remove read-only block:
```bash
curl -X PUT -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_cluster/settings" \
  -H 'Content-Type: application/json' \
  -d '{"transient":{"cluster.routing.allocation.disk.threshold_enabled":false}}'
```

#### Issue: S3 backup fails with "Access Denied"

**Cause:** Insufficient IAM permissions.

**Solution:**
1. Verify IAM policy includes PutObject, GetObject, DeleteObject, ListBucket
2. Check bucket policy doesn't deny access
3. Verify AWS credentials in .env

#### Issue: Restore fails with "index already exists"

**Cause:** Trying to restore to existing index.

**Solution:**
1. Close index first: `curl -X POST "localhost:9080/elasticsearch/index-name/_close"`
2. Or delete index: `curl -X DELETE "localhost:9080/elasticsearch/index-name"`
3. Or use rename during restore (see Restore to Different Index Name)

---

## Best Practices

### Backup Schedule

**Development:**
- Frequency: Daily or every few days
- Retention: 7-14 days
- Storage: Filesystem

**Staging:**
- Frequency: Daily
- Retention: 14-30 days
- Storage: S3/Azure/GCS

**Production:**
- Frequency: Every 6-12 hours
- Retention: 30-90 days
- Storage: S3/Azure/GCS with versioning
- Off-site: Enable cross-region replication

### Retention Strategy

**3-2-1 Rule:**
- **3** copies of data (original + 2 backups)
- **2** different storage types (e.g., disk + S3)
- **1** off-site backup

**Example:**
```bash
# On-site backups (fast restore)
BACKUP_REPOSITORY_TYPE=fs
BACKUP_RETENTION_DAYS=7

# Off-site backups (disaster recovery)
# Run separate backup job to S3 with longer retention
BACKUP_REPOSITORY_TYPE=s3
BACKUP_RETENTION_DAYS=90
```

### Security

**Encrypt Snapshots:**

For filesystem:
```bash
# Use LUKS encryption on backup volume
cryptsetup luksFormat /dev/sdb
cryptsetup luksOpen /dev/sdb encrypted_backups
mkfs.ext4 /dev/mapper/encrypted_backups
```

For S3:
```bash
# Enable server-side encryption
AWS_S3_SERVER_SIDE_ENCRYPTION=AES256
```

**Protect Credentials:**
```bash
# Secure .env file
chmod 600 .env

# Never commit credentials
echo ".env" >> .gitignore

# Use secrets management in production
# - AWS Secrets Manager
# - HashiCorp Vault
# - Azure Key Vault
```

### Testing Restores

**Test restore monthly:**

```bash
# 1. Restore to temporary index
curl -X POST -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo/latest/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "mule-logs-*",
    "rename_pattern": "(.+)",
    "rename_replacement": "test-restore-$1"
  }'

# 2. Verify data integrity
curl "http://localhost:9080/elasticsearch/test-restore-mule-logs-*/_count?pretty"

# 3. Delete test indices
curl -X DELETE "http://localhost:9080/elasticsearch/test-restore-*"
```

### Performance

**Optimize Backup Speed:**

1. **Increase threads:**
```yaml
elasticsearch:
  environment:
    - snapshot.max_concurrent_operations=5
```

2. **Use compression:**
```bash
BACKUP_COMPRESS=true
```

3. **Limit network bandwidth (if needed):**
```bash
# For S3
AWS_S3_MAX_RETRIES=3
```

**Optimize Storage:**

1. **Incremental snapshots:** ElasticSearch automatically uses incremental snapshots (only changed data)
2. **Compression:** Enable `BACKUP_COMPRESS=true` (reduces size by 50-70%)
3. **Index lifecycle:** Use ILM to move old data to warm/cold tiers before backup

### Monitoring

**Set up alerts for:**

1. **Backup failures:**
```bash
# Enable notifications
BACKUP_NOTIFICATIONS_ENABLED=true
BACKUP_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK
```

2. **Repository health:**
```bash
# Run verification daily
0 4 * * * /path/to/scripts/configure-backup.sh --verify >> /var/log/backup-verify.log 2>&1
```

3. **Disk space:**
```bash
# Alert when backup volume > 80% full
df -h /mnt/elasticsearch-backups | awk '{if ($5+0 > 80) print "WARNING: Backup volume is "$5" full"}'
```

### Documentation

**Maintain backup inventory:**

```bash
# Generate backup report
echo "# Backup Inventory - $(date)" > backup-inventory.md
echo "" >> backup-inventory.md
curl -u elastic:${ELASTIC_PASSWORD} \
  "http://localhost:9080/elasticsearch/_snapshot/backup-repo/_all" | \
  python3 -m json.tool >> backup-inventory.md
```

**Document restore procedures:**
- Create runbook for disaster recovery
- Include credentials location
- List restore time objectives (RTO)
- Document recovery point objectives (RPO)

---

## Summary

You now have a complete backup solution with:

✅ **Configuration** via `.env` file
✅ **Manual backups** with `backup.sh`
✅ **Automated backups** via cron jobs
✅ **Retention management** with cleanup script
✅ **Restore capabilities** for disaster recovery
✅ **Multiple storage options** (filesystem, S3, Azure, GCS)
✅ **Monitoring and notifications**

For questions or issues, refer to the troubleshooting section or check ElasticSearch logs:

```bash
docker-compose logs -f elasticsearch
```
