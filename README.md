# Game-Mcp

Ein MCP-Server für Entity-Management und mehr.

## Voraussetzungen
- Docker und Docker Compose
- curl und jq (für das Testskript)

## Starten des Servers

1. Baue und starte die Container:

   ```bash
   docker compose up -d --build
   ```

2. Der Server läuft standardmäßig auf `http://localhost:5000`.

## Verbindung zum MCP-Server herstellen

Du kannst mit jedem HTTP-Client (z.B. curl, Postman, Python requests) auf die API zugreifen. Beispiel mit curl:

```bash
curl -X GET http://localhost:5000/entities
```

### Beispiel: Entity anlegen

```bash
curl -X POST http://localhost:5000/entities \
     -H "Content-Type: application/json" \
     -d '{"name": "TestEntity", "type": "test"}'
```

## Testskript

Das Skript `test_mcp.sh` testet alle Hauptfunktionen automatisch:

```bash
./test_mcp.sh
```

## Dateien
- `server.py` – MCP-Server (Flask/FastAPI o.ä.)
- `requirements.txt` – Python-Abhängigkeiten
- `Dockerfile` – Container-Build
- `docker-compose.yml` – Multi-Container-Setup
- `test_mcp.sh` – Testskript für die API

---

Fragen? Melde dich gerne!
