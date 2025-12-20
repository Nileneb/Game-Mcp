#!/usr/bin/env python3
"""
Simuliert ein IoT-Device, das sich per SSE mit dem MCP verbindet und Assignments empfängt.
Sendet anschließend ein Ergebnis zurück.
"""
import sseclient
import json
import time
import requests

MCP_SSE_URL = "http://192.168.178.12:8082/sse-paperstream?client_id=testdevice"
MCP_RESULT_URL = "http://192.168.178.12:8082/paper-result"

def send_result(assignment):
    payload = {
        "assignment_id": assignment["assignment_id"],
        "job_id": assignment["job_id"],
        "result": {"answer": "Simuliertes Ergebnis", "timestamp": time.time()},
        "conf": 1.0,
        "device_id": "testdevice",
        "sig": assignment.get("sig", "")
    }
    print(f"Sende Ergebnis: {json.dumps(payload)}")
    r = requests.post(MCP_RESULT_URL, json=payload)
    print(f"Server-Antwort: {r.text}")

if __name__ == "__main__":
    print(f"Verbinde zu {MCP_SSE_URL} ...")
    client = sseclient.SSEClient(MCP_SSE_URL)
    for event in client:
        print(f"Empfangen: {event.data}")
        data = json.loads(event.data)
        if data.get("type") == "assignment":
            send_result(data)
            break
