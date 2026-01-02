#!/bin/sh

# Setup APM Integration in Kibana
# This script installs the APM integration package and configures Fleet

set -e

KIBANA_URL="http://kibana:5601"
ELASTICSEARCH_URL="http://elasticsearch:9200"
ELASTIC_USER="elastic"
ELASTIC_PASSWORD="elastic"
MAX_RETRIES=30
RETRY_INTERVAL=10

echo "Waiting for Kibana to be ready..."
for i in $(seq 1 $MAX_RETRIES); do
  if curl -s -f -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" "${KIBANA_URL}/api/status" > /dev/null 2>&1; then
    echo "Kibana is ready!"
    break
  fi

  if [ $i -eq $MAX_RETRIES ]; then
    echo "ERROR: Kibana did not become ready in time"
    exit 1
  fi

  echo "Waiting for Kibana... attempt $i/$MAX_RETRIES"
  sleep $RETRY_INTERVAL
done

echo "Waiting for ElasticSearch to be ready..."
for i in $(seq 1 $MAX_RETRIES); do
  if curl -s -f -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" "${ELASTICSEARCH_URL}/_cluster/health" > /dev/null 2>&1; then
    echo "ElasticSearch is ready!"
    break
  fi

  if [ $i -eq $MAX_RETRIES ]; then
    echo "ERROR: ElasticSearch did not become ready in time"
    exit 1
  fi

  echo "Waiting for ElasticSearch... attempt $i/$MAX_RETRIES"
  sleep $RETRY_INTERVAL
done

# Give Kibana a few more seconds to fully initialize
sleep 10

echo "Setting up Fleet..."

# Step 1: Setup Fleet
echo "Initializing Fleet..."
curl -X POST "${KIBANA_URL}/api/fleet/setup" \
  -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  2>&1 | grep -v "curl: (52)" || true

sleep 5

# Step 2: Install APM integration package
echo "Installing APM integration package..."
curl -X POST "${KIBANA_URL}/api/fleet/epm/packages/apm/8.11.3" \
  -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  2>&1 | grep -v "curl: (52)" || true

sleep 5

# Step 3: Check if APM Policy already exists, if not create it
echo "Checking for existing APM Policy..."
EXISTING_POLICY=$(curl -s -X GET "${KIBANA_URL}/api/fleet/agent_policies" \
  -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
  -H "kbn-xsrf: true" 2>&1 | grep -o '"id":"[^"]*","name":"APM Policy"' | head -1 || echo "")

if [ -n "$EXISTING_POLICY" ]; then
  POLICY_ID=$(echo "$EXISTING_POLICY" | sed 's/"id":"\([^"]*\)".*/\1/')
  echo "Found existing APM Policy with ID: $POLICY_ID"
else
  echo "Creating new APM Policy..."
  POLICY_RESPONSE=$(curl -s -X POST "${KIBANA_URL}/api/fleet/agent_policies" \
    -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
    -H "kbn-xsrf: true" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "APM Policy",
      "namespace": "default",
      "description": "Policy for APM Server - Auto-configured",
      "monitoring_enabled": ["logs", "metrics"]
    }' 2>&1)

  POLICY_ID=$(echo "$POLICY_RESPONSE" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -1)
  echo "Created APM Policy with ID: $POLICY_ID"
fi

sleep 2

# Step 4: Add APM integration to the policy (if not already added)
if [ -n "$POLICY_ID" ] && [ "$POLICY_ID" != "" ]; then
  echo "Checking if APM integration already exists in policy..."
  EXISTING_INTEGRATION=$(curl -s -X GET "${KIBANA_URL}/api/fleet/package_policies" \
    -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
    -H "kbn-xsrf: true" 2>&1 | grep -o '"name":"apm-integration"' || echo "")

  if [ -n "$EXISTING_INTEGRATION" ]; then
    echo "APM integration already exists in policy - skipping creation"
  else
    echo "Adding APM integration to policy..."
    curl -s -X POST "${KIBANA_URL}/api/fleet/package_policies" \
      -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
      -H "kbn-xsrf: true" \
      -H "Content-Type: application/json" \
      -d "{
        \"name\": \"apm-integration\",
        \"namespace\": \"default\",
        \"description\": \"APM integration - Auto-configured\",
        \"policy_id\": \"${POLICY_ID}\",
        \"enabled\": true,
        \"package\": {
          \"name\": \"apm\",
          \"version\": \"8.11.3\"
        },
        \"inputs\": [
          {
            \"type\": \"apm\",
            \"enabled\": true,
            \"streams\": [],
            \"vars\": {
              \"host\": {
                \"value\": \"0.0.0.0:8200\",
                \"type\": \"text\"
              },
              \"url\": {
                \"value\": \"http://apm-server:8200\",
                \"type\": \"text\"
              },
              \"secret_token\": {
                \"type\": \"text\"
              }
            }
          }
        ]
      }" 2>&1 | head -20

    echo ""
    echo "APM integration added successfully"
  fi
else
  echo "ERROR: Could not get valid policy ID"
  exit 1
fi

sleep 5

# Step 5: Verify APM integration installation
echo "Verifying APM integration..."
curl -s "${KIBANA_URL}/api/fleet/epm/packages/apm" \
  -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
  -H "kbn-xsrf: true" 2>&1 | grep -o '"status":"[^"]*"' || echo "Status check failed"

echo ""
echo "=========================================="
echo "APM Integration Setup Complete!"
echo "=========================================="
echo ""
echo "The APM integration has been fully configured in Kibana Fleet."
echo "APM Server should now be recognized by Kibana APM app."
echo ""
echo "Access APM in Kibana:"
echo "  1. Open: http://localhost:9080/kibana"
echo "  2. Login with: elastic / elastic"
echo "  3. Navigate to: Observability → APM"
echo ""
echo "APM Server endpoint: http://localhost:8200"
echo "Via APISIX: http://localhost:9080/apm-server"
echo ""
