#!/bin/bash

# Wait for Kibana to be ready
echo "Waiting for Kibana to be ready..."
until curl -s http://kibana:5601/api/status | grep -q '"level":"available"'; do
  echo "Kibana is not ready yet, waiting..."
  sleep 5
done

echo "Kibana is ready!"
sleep 10  # Give Kibana a bit more time to fully initialize

# Create the Mule Logs data view
echo "Creating Mule Logs data view..."
curl -X POST "http://kibana:5601/api/data_views/data_view" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -d '{
    "data_view": {
      "title": "mule-logs-*",
      "name": "Mule Logs",
      "timeFieldName": "@timestamp"
    }
  }'

echo ""
echo "Mule Logs data view created successfully!"

# Create the general Logstash data view
echo "Creating Logstash data view..."
curl -X POST "http://kibana:5601/api/data_views/data_view" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -d '{
    "data_view": {
      "title": "logstash-*",
      "name": "Logstash Logs",
      "timeFieldName": "@timestamp"
    }
  }'

echo ""
echo "Logstash data view created successfully!"
echo "Kibana setup complete!"
