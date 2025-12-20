#!/bin/bash
# Testskript für die wichtigsten Funktionen des neuen MCP-Servers
# Annahme: Der Server läuft lokal auf Port 8082

BASE_URL="http://localhost:8082"

echo "Test: Enqueue Job via /paperstream_enqueue"
RESPONSE=$(curl -s -X POST "$BASE_URL/paperstream_enqueue" -H "Content-Type: application/json" -d '{"items": [{"paper_url": "https://example.com/paper.pdf", "question": "Was steht auf Seite 1?"}], "k": 1}')
echo "$RESPONSE" | jq
JOB_ID=$(echo "$RESPONSE" | jq -r '.job_id')

echo "-----------------------------"

echo "Test: Ergebnis abliefern via /paper-result (simuliert)"
ASSIGNMENT_ID="a_test_assignment"
RESULT_PAYLOAD='{"assignment_id": "'$ASSIGNMENT_ID'", "job_id": "'$JOB_ID'", "result": {"answer": "Testantwort", "timestamp": 1234567890}, "conf": 1.0, "device_id": "testdevice", "sig": ""}'
curl -s -X POST "$BASE_URL/paper-result" -H "Content-Type: application/json" -d "$RESULT_PAYLOAD" | jq

echo "-----------------------------"

echo "Alle MCP-Tests abgeschlossen."
