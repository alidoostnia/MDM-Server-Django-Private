#!/bin/sh
set -e

echo "Creating MQTT user..."
HTTP_RESPONSE=$(curl -s -w "HTTPSTATUS:%{http_code}" -X POST \
  "http://mqtt:18083/api/v5/authentication/password_based:built_in_database/users" \
  -u "${API_KEY}:${API_SECRET}" \
  -H "Content-Type: application/json" \
  -d "{\"user_id\": \"${MQTT_USERNAME}\", \"password\": \"${MQTT_PASSWORD}\"}")

BODY=$(echo "$HTTP_RESPONSE" | sed -e "s/HTTPSTATUS:.*//")
STATUS=$(echo "$HTTP_RESPONSE" | tr -d "\n" | sed -e "s/.*HTTPSTATUS://")

echo "Response status: $STATUS"
echo "Response body: $BODY"

if echo "$BODY" | grep -q "\"user_id\":\"${MQTT_USERNAME}\""; then
  echo "User already present. Success."
  exit 0
elif echo "$BODY" | grep -q "ALREADY_EXISTS"; then
  echo "User already exists. Success."
  exit 0
else
  echo "Failed to create MQTT user"
  exit 1
fi
