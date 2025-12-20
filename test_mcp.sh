#!/bin/bash
# Testskript für alle Funktionen des MCP-Servers
# Annahme: Der Server läuft lokal auf Port 5000

BASE_URL="http://localhost:5000"

# Test: /entities (GET)
echo "Test: GET /entities"
curl -s -X GET "$BASE_URL/entities" | jq

echo "-----------------------------"

# Test: /entities (POST)
echo "Test: POST /entities"
RESPONSE=$(curl -s -X POST "$BASE_URL/entities" -H "Content-Type: application/json" -d '{"name": "TestEntity", "type": "test"}')
echo "$RESPONSE" | jq
ENTITY_ID=$(echo "$RESPONSE" | jq -r '.id')

echo "-----------------------------"

# Test: /entities/<id> (GET)
echo "Test: GET /entities/$ENTITY_ID"
curl -s -X GET "$BASE_URL/entities/$ENTITY_ID" | jq

echo "-----------------------------"

# Test: /entities/<id> (PUT)
echo "Test: PUT /entities/$ENTITY_ID"
curl -s -X PUT "$BASE_URL/entities/$ENTITY_ID" -H "Content-Type: application/json" -d '{"name": "UpdatedEntity", "type": "test"}' | jq

echo "-----------------------------"

# Test: /entities/<id> (DELETE)
echo "Test: DELETE /entities/$ENTITY_ID"
curl -s -X DELETE "$BASE_URL/entities/$ENTITY_ID" | jq

echo "-----------------------------"

echo "Alle MCP-Tests abgeschlossen."
