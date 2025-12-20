
# Game-Mining MCP

Ein moderner MCP-Server für GameMining-IoT-Orchestrierung mit Redis-Cache, Docker-Stack und automatisierten Tests.

## Voraussetzungen
- Docker & Docker Compose
- curl und jq (für das Testskript)

## Starten des Stacks

```bash
docker compose up -d --build
```

Der MCP-Server läuft standardmäßig auf `http://localhost:8082`.

## Architektur
- **game-mining-mcp**: MCP-Server (Port 8082)
- **redis**: Cache für schnelle Aufgaben- und Statusverwaltung
- **iot-test**: Simuliert ein IoT-Device (verbindet sich per SSE, liefert Ergebnisse ab)

## Verbindung zum MCP-Server

### Aufgaben einstellen (Job enqueuen)
```bash
curl -X POST http://localhost:8082/paperstream_enqueue \
   -H "Content-Type: application/json" \
   -d '{"items": [{"paper_url": "https://example.com/paper.pdf", "question": "Was steht auf Seite 1?"}], "k": 1}'
```

### Ergebnis abliefern
```bash
curl -X POST http://localhost:8082/paper-result \
   -H "Content-Type: application/json" \
   -d '{"assignment_id": "a_test_assignment", "job_id": "j_123", "result": {"answer": "Testantwort", "timestamp": 1234567890}, "conf": 1.0, "device_id": "testdevice", "sig": ""}'
```

### Aufgaben als Device abholen (SSE)
```bash
curl -N http://localhost:8082/sse-paperstream?client_id=testdevice
```

## Testskript

Das Skript `test_mcp.sh` testet Enqueue und Ergebnis-POST automatisch:

```bash
./test_mcp.sh
```

## Dateien
- `server.py` – MCP-Server (FastAPI/Starlette)
- `requirements.txt` – Python-Abhängigkeiten
- `Dockerfile` – Container-Build
- `docker-compose.yml` – Multi-Container-Setup inkl. Redis & IoT-Test
- `test_mcp.sh` – Testskript für die API
- `simulate_iot_device.py` – Simuliert ein IoT-Device

---

Fragen? Melde dich gerne!
