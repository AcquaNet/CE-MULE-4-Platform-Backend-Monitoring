# Security Setup Guide

Quick reference for configuring secure credentials in the ELK stack.

## Quick Start

### 1. Generate Secure Credentials

```bash
# Generate all passwords and keys automatically
./scripts/generate-secrets.sh

# This creates a .env file with secure random values
```

### 2. Review Generated Credentials

The script will display all generated credentials. **Save these in a secure password manager!**

Example output:
```
ElasticSearch Credentials:
  Username: elastic
  Password: swCiSuGZvacKT10yfaiSmknDbeSrvttt

Kibana System User:
  Username: kibana_system
  Password: VJb66ciegtqPulFWajD8Bw3B4GPo3g5a

APISIX Admin:
  API Key: 065f4bca05dbdfef37218b738ede4e5f...

Grafana Admin:
  Username: admin
  Password: oOFHOWoOrs64U9rOYVxN0l6NTZc1CTcM
```

### 3. Customize Configuration (Optional)

Edit `.env` to customize settings:

```bash
# Edit memory allocation
ES_JAVA_OPTS=-Xms4g -Xmx4g  # Increase ElasticSearch heap
LS_JAVA_OPTS=-Xms2g -Xmx2g  # Increase Logstash heap

# Set client information
CLIENT_NAME=acme-corp
ENVIRONMENT=production
RETENTION_DAYS=90
```

### 4. Start the Stack

```bash
docker-compose up -d
```

---

## Manual Setup

If you prefer to set credentials manually:

### 1. Copy the Template

```bash
cp .env.example .env
```

### 2. Generate Individual Passwords

```bash
# Generate a 32-character password
openssl rand -base64 32 | tr -d "=+/" | cut -c1-32

# Generate a 48-character encryption key
openssl rand -base64 48 | tr -d "=+/" | cut -c1-48

# Generate a hex key (for APISIX)
openssl rand -hex 32
```

### 3. Edit .env File

Replace all `CHANGE_ME_PLEASE` values with your generated passwords:

```bash
ELASTIC_PASSWORD=YOUR_GENERATED_PASSWORD
KIBANA_PASSWORD=YOUR_GENERATED_PASSWORD
KIBANA_ENCRYPTION_KEY=YOUR_GENERATED_KEY
# ... etc
```

### 4. Secure the File

```bash
chmod 600 .env
```

---

## Production Security Recommendations

For production deployments:

- Create `.env` file with secure passwords (not `CHANGE_ME_PLEASE`)
- Set restricted permissions on `.env` file: `chmod 600 .env`
- Verify `.env` file is in `.gitignore` (never commit to version control)
- Save credentials in secure password manager
- Change default passwords in all services
- Enable SSL/TLS (see [SSL_TLS_SETUP.md](SSL_TLS_SETUP.md))
- Configure firewall to restrict access
- Configure APISIX IP whitelist (change from `0.0.0.0/0`)

---

## Credential Reference

### ElasticSearch

| Purpose | Username | Password Variable |
|---------|----------|-------------------|
| Superuser | `elastic` | `ELASTIC_PASSWORD` |
| Kibana Internal | `kibana_system` | `KIBANA_PASSWORD` |

**Default ElasticSearch Users:**
- `elastic` - Superuser with all privileges
- `kibana_system` - Used by Kibana to connect to ElasticSearch
- `logstash_system` - Used by Logstash (optional, we use elastic user)
- `apm_system` - Used by APM Server (optional, we use elastic user)

### APISIX

| Purpose | Credential | Variable |
|---------|-----------|----------|
| Admin API | API Key | `APISIX_ADMIN_KEY` |
| Dashboard | Password | `APISIX_DASHBOARD_PASSWORD` |

**APISIX Dashboard Access:**
- URL: `http://localhost:9000`
- Username: `admin`
- Password: Value of `APISIX_DASHBOARD_PASSWORD`

### Grafana

| Purpose | Username | Password Variable |
|---------|----------|-------------------|
| Admin User | `admin` | `GRAFANA_ADMIN_PASSWORD` |

**Grafana Access:**
- URL: `http://localhost:9080/grafana`
- Username: `admin`
- Password: Value of `GRAFANA_ADMIN_PASSWORD`

---

## Password Rotation

To rotate passwords:

### 1. Generate New Credentials

```bash
./scripts/generate-secrets.sh --force
```

### 2. Update ElasticSearch Users

```bash
# Update kibana_system password
curl -X POST "http://localhost:9200/_security/user/kibana_system/_password" \
  -u elastic:${OLD_ELASTIC_PASSWORD} \
  -H 'Content-Type: application/json' \
  -d "{\"password\": \"${NEW_KIBANA_PASSWORD}\"}"
```

### 3. Restart Services

```bash
docker-compose restart
```

### 4. Update Credentials in Password Manager

Save the new credentials securely.

---

## Troubleshooting

### "Authentication failed" Error

**Symptom:** Cannot access ElasticSearch, Kibana, or Grafana after starting

**Solution:**
1. Check if `.env` file exists: `ls -la .env`
2. Verify credentials are set (not `CHANGE_ME_PLEASE`): `cat .env | grep PASSWORD`
3. Restart services: `docker-compose restart`

### "Invalid encryption key" Error

**Symptom:** Kibana fails to start with encryption key error

**Solution:**
Encryption keys must be at least 32 characters long:

```bash
# Generate valid keys
KIBANA_ENCRYPTION_KEY=$(openssl rand -base64 48 | tr -d "=+/" | cut -c1-48)
KIBANA_REPORTING_ENCRYPTION_KEY=$(openssl rand -base64 48 | tr -d "=+/" | cut -c1-48)

# Update .env file
sed -i "s|KIBANA_ENCRYPTION_KEY=.*|KIBANA_ENCRYPTION_KEY=$KIBANA_ENCRYPTION_KEY|" .env
sed -i "s|KIBANA_REPORTING_ENCRYPTION_KEY=.*|KIBANA_REPORTING_ENCRYPTION_KEY=$KIBANA_REPORTING_ENCRYPTION_KEY|" .env
```

### ".env file not loaded" Error

**Symptom:** Services start but use default passwords

**Solution:**
Docker Compose automatically loads `.env` if it's in the same directory as `docker-compose.yml`:

```bash
# Verify .env is in the correct location
ls -la .env docker-compose.yml

# Both files should be in the same directory
```

### "Permission denied" Error

**Symptom:** Cannot read or modify `.env` file

**Solution:**
```bash
# Fix permissions
chmod 600 .env
```

---

## Best Practices

### 1. Never Commit Credentials

The `.env` file is in `.gitignore`. Never use `git add -f .env`!

### 2. Use Strong Passwords

All generated passwords are:
- 32+ characters long
- Cryptographically random
- Contain alphanumeric characters

### 3. Limit Access

Protect the `.env` file:
```bash
chmod 600 .env        # Only owner can read/write
chown root:root .env  # Only root can access (optional)
```

### 4. Separate Environments

Use different credentials for each environment:

```bash
# Development
cp .env .env.dev
./scripts/generate-secrets.sh --force

# Production
cp .env .env.prod
./scripts/generate-secrets.sh --force
```

Then symlink based on environment:
```bash
ln -sf .env.prod .env  # Use production credentials
```

### 5. Backup Credentials

Store credentials in multiple secure locations:
- Password manager (1Password, LastPass, BitWarden)
- Encrypted backup file
- Secrets management service (HashiCorp Vault, AWS Secrets Manager)

**Never backup credentials in:**
- Plain text files
- Email
- Slack/chat
- Version control (git)
- Shared drives without encryption

---

## Advanced Configuration

### Using External Secrets Management

#### HashiCorp Vault

```yaml
# docker-compose.yml
services:
  elasticsearch:
    environment:
      - ELASTIC_PASSWORD=${VAULT_SECRET_ELASTIC_PASSWORD}
```

```bash
# Retrieve from Vault
export VAULT_SECRET_ELASTIC_PASSWORD=$(vault kv get -field=password secret/elk/elastic)
```

#### AWS Secrets Manager

```bash
# Retrieve from AWS
export ELASTIC_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id elk/elastic/password \
  --query SecretString \
  --output text)
```

### Using Docker Secrets (Swarm Mode)

```yaml
# docker-compose.yml
secrets:
  elastic_password:
    external: true

services:
  elasticsearch:
    secrets:
      - elastic_password
    environment:
      - ELASTIC_PASSWORD_FILE=/run/secrets/elastic_password
```

```bash
# Create secret
echo "your-secure-password" | docker secret create elastic_password -
```

---

## Security Incident Response

If credentials are compromised:

### 1. Immediate Actions

```bash
# Stop all services
docker-compose down

# Generate new credentials
./scripts/generate-secrets.sh --force

# Restart with new credentials
docker-compose up -d
```

### 2. Audit Access

```bash
# Check ElasticSearch access logs
docker exec elasticsearch cat /usr/share/elasticsearch/logs/elasticsearch.log | grep -i "authentication"

# Check APISIX access logs
docker exec apisix cat /usr/local/apisix/logs/access.log
```

### 3. Rotate All Credentials

Follow the "Password Rotation" section above.

### 4. Review Security

- Update firewall rules
- Enable IP whitelisting
- Enable SSL/TLS
- Review user permissions
- Check for unauthorized indices/data

---

## Related Documentation

- **SSL/TLS Setup**: [SSL_TLS_SETUP.md](SSL_TLS_SETUP.md)
- **Environment Configuration**: `.env.example`
- **Docker Compose**: `docker-compose.yml`
- **APISIX Security**: `apisix-config/config/config.yaml`

---

**Last Updated:** 2025-12-28
**Version:** 1.0
