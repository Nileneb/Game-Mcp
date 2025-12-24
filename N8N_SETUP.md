# 🔗 n8n MCP Client Setup - Mining Job Server

## Übersicht

Dieser MCP Server stellt Mining-Job-Management-Tools für n8n über das Model Context Protocol (MCP) bereit.

## Server-Konfiguration

### Endpunkt
```
URL: http://192.168.178.12:8082/sse
Transport: SSE (Server-Sent Events)
```

## n8n Setup - Schritt für Schritt

### 1. MCP Client Tool Node hinzufügen

1. Öffne deinen n8n Workflow
2. Füge einen **"MCP Client"** Tool Node hinzu
3. Erstelle eine neue MCP Connection

### 2. Connection konfigurieren

```
Server URL: http://192.168.178.12:8082/sse
Transport: SSE
Name: Mining Pool Server
```

**Wichtig:** Verwende GET /sse, nicht POST /call!

### 3. Verfügbare Tools

#### `create_mining_job`
Erstellt einen neuen Mining Job und verteilt Tasks an Devices.

**Parameter:**
- `num_tasks` (number, optional): Anzahl der Tasks (default: 10)
- `chunk_size` (number, optional): Nonce-Range pro Task (default: 1000000)

**Rückgabe:**
```json
{
  "success": true,
  "job_id": "job_abc123",
  "block_index": 5,
  "difficulty": 4,
  "potential_reward": 50.0,
  "tasks_created": 10,
  "message": "Mining job created for Block #5"
}
```

#### `get_pool_status`
Gibt aktuellen Pool-Status zurück.

**Parameter:** Keine

**Rückgabe:**
```json
{
  "blockchain": {
    "height": 5,
    "current_difficulty": 4,
    "pending_block": true
  },
  "pool": {
    "active_jobs": 2,
    "pending_tasks": 15,
    "total_devices": 10,
    "active_devices": 8
  },
  "recent_blocks": [...]
}
```

#### `get_leaderboard`
Top-10 Miner mit Stats.

**Parameter:** Keine

**Rückgabe:**
```json
{
  "leaderboard": [
    {
      "rank": 1,
      "device_id": "Unity1",
      "coins": 150.5,
      "blocks_found": 3,
      "tasks_completed": 245
    }
  ]
}
```

#### `get_job_details`
Details zu einem spezifischen Job.

**Parameter:**
- `job_id` (string, required): Job ID

**Rückgabe:**
```json
{
  "success": true,
  "job": {
    "job_id": "job_abc123",
    "block_index": 5,
    "difficulty": 4,
    "reward": 50.0,
    "status": "active",
    "tasks_created": 10,
    "tasks_completed": 7,
    "winner": null,
    "created_at": "2025-12-23T12:00:00"
  }
}
```

#### `list_devices`
Alle verbundenen Mining Devices.

**Parameter:** Keine

**Rückgabe:**
```json
{
  "devices": [
    {
      "device_id": "Unity1",
      "inflight_tasks": 2,
      "stats": {
        "coins": 150.5,
        "blocks_found": 3,
        "tasks_completed": 245
      }
    }
  ],
  "count": 10
}
```

## Beispiel-Workflow in n8n

### Mining Job erstellen
```
[Schedule Trigger] 
  → [MCP Client: create_mining_job]
    Parameters:
      num_tasks: 20
      chunk_size: 500000
  → [Code Node: Process Result]
```

### Pool Status überwachen
```
[Schedule Trigger (every 5 min)]
  → [MCP Client: get_pool_status]
  → [IF Node: Check active_devices]
  → [Slack/Email Notification]
```

## Troubleshooting

### "Could not connect to your MCP server"

**Lösung:**
1. Prüfe ob Server läuft: `ss -tulpen | grep 8082`
2. Verwende GET /sse, nicht POST
3. Stelle sicher, dass n8n Zugriff auf den Server hat (Firewall, Netzwerk)
4. Test mit curl:
   ```bash
   curl -N http://192.168.178.12:8082/sse
   ```

### "404 Not Found on /call"

**Problem:** Du verwendest POST /call statt GET /sse

**Lösung:** Stelle die n8n Connection auf GET /sse um.

### Server erreicht aber Tools funktionieren nicht

**Lösung:**
1. Prüfe Server-Logs
2. Stelle sicher, dass FASTMCP_HOST und FASTMCP_PORT in .env gesetzt sind
3. Neustart des Servers: `./start_mining.sh`

## Environment Setup

Die Server-Konfiguration erfolgt über `.env`:

```bash
# FastMCP Job Server (n8n)
FASTMCP_HOST=0.0.0.0
FASTMCP_PORT=8082
# FASTMCP_LOG_LEVEL=INFO

# Device Server (Unity)
DEVICE_SERVER_HOST=0.0.0.0
DEVICE_SERVER_PORT=8083

# Mining Configuration
BASE_DIFFICULTY=4
BLOCK_REWARD=50
TARGET_BLOCK_TIME=60
ASSIGN_TTL=120
MAX_INFLIGHT_PER_DEVICE=2
```

## Server starten

```bash
./start_mining.sh
```

Beide Server starten automatisch:
- Job Server (n8n): Port 8082
- Device Server (Unity): Port 8083

## Support

Bei Problemen prüfe:
1. Server-Logs im Terminal
2. `.env` Konfiguration
3. Netzwerk-Konnektivität zwischen n8n und Server
4. Firewall-Regeln für Port 8082
