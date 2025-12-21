# 🚀 MCP Mining Pool System v2.0

Distributed Mining System mit **2 spezialisierten MCP Servern**:

1. **Job Server** (Port 8082) - Für n8n AI Agent (Job Management)
2. **Device Server** (Port 8083) - Für Unity Devices (Task Distribution via SSE)

---

## 📐 ARCHITEKTUR

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌────────────────┐                    ┌────────────────────┐   │
│  │  n8n AI Agent  │                    │  Unity Devices     │   │
│  │                │                    │                    │   │
│  │  SSE ↔ MCP     │                    │  SSE ↔ Tasks       │   │
│  └────────┬───────┘                    └────────┬───────────┘   │
│           │                                     │               │
│           ▼                                     ▼               │
│  ┌─────────────────┐              ┌──────────────────────────┐ │
│  │  Job Server     │              │  Device Server           │ │
│  │  Port 8082      │              │  Port 8083               │ │
│  │                 │              │                          │ │
│  │  Tools:         │              │  SSE Push ─► Unity       │ │
│  │  - create_job   │              │  POST ◄─── Results       │ │
│  │  - get_status   │              │                          │ │
│  │  - leaderboard  │              │  Auto-Retry bei Timeout  │ │
│  └────────┬────────┘              └────────┬─────────────────┘ │
│           │                                │                   │
│           └──────────┬─────────────────────┘                   │
│                      │                                         │
│              ┌───────▼────────┐                                │
│              │  shared_state  │                                │
│              │                │                                │
│              │  - Blockchain  │                                │
│              │  - Jobs        │                                │
│              │  - Task Queue  │                                │
│              │  - Leaderboard │                                │
│              └────────────────┘                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 INSTALLATION

### 1. Dateien

Alle 5 Dateien in einem Verzeichnis:
- `shared_state.py` - Gemeinsamer State
- `mcp_job_server.py` - Job Management
- `mcp_device_server.py` - Device Distribution
- `requirements.txt` - Dependencies
- `start_mining.sh` - Startup Script

### 2. Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start

```bash
chmod +x start_mining.sh
./start_mining.sh
```

Oder manuell:
```bash
# Terminal 1
python3 mcp_job_server.py

# Terminal 2  
python3 mcp_device_server.py
```

---

## 📋 JOB SERVER (n8n AI Agent)

**Port:** 8082  
**SSE Endpoint:** `http://192.168.178.12:8082/sse`

### n8n MCP Client Tool Setup

```json
{
  "name": "Mining Pool",
  "transport": "sse",
  "url": "http://192.168.178.12:8082/sse"
}
```

### MCP Tools

#### create_mining_job
```javascript
{
  "num_tasks": 10,        // Anzahl Tasks (optional)
  "chunk_size": 1000000   // Nonces pro Task (optional)
}
```
→ Erstellt Mining Job für nächsten Block  
→ Tasks werden automatisch an Unity Devices verteilt!

#### get_pool_status
```javascript
{}
```
→ Blockchain Höhe, Difficulty, aktive Jobs, verbundene Devices

#### get_leaderboard
```javascript
{}
```
→ Top 10 Miner mit Coins, gefundenen Blocks

#### get_job_details
```javascript
{
  "job_id": "job_abc123"
}
```
→ Details zu einem Job

#### list_devices
```javascript
{}
```
→ Alle verbundenen Unity Devices + Stats

---

## 🎮 DEVICE SERVER (Unity)

**Port:** 8083

### Unity Connection (C#)

```csharp
using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

public class MiningClient : MonoBehaviour
{
    private string deviceId = "Unity1";
    private string sseUrl = "http://192.168.178.12:8083/sse";
    
    void Start()
    {
        StartCoroutine(ConnectSSE());
    }
    
    IEnumerator ConnectSSE()
    {
        string url = $"{sseUrl}?device_id={deviceId}";
        
        using (UnityWebRequest www = UnityWebRequest.Get(url))
        {
            www.downloadHandler = new SSEDownloadHandler(this);
            yield return www.SendWebRequest();
        }
    }
    
    void OnAssignment(string json)
    {
        var task = JsonUtility.FromJson<MiningTask>(json);
        
        Debug.Log($"📥 New task: Block {task.block_header}, " +
                  $"Nonces {task.nonce_range_start}-{task.nonce_range_end}");
        
        StartCoroutine(MineTask(task));
    }
    
    IEnumerator MineTask(MiningTask task)
    {
        // SHA256 Mining
        for (int nonce = task.nonce_range_start; nonce < task.nonce_range_end; nonce++)
        {
            string input = $"{task.block_header}:{nonce}";
            string hash = ComputeSHA256(input);
            
            // Check difficulty
            string required = new string('0', task.difficulty);
            if (hash.StartsWith(required))
            {
                // WINNER!
                yield return SubmitResult(task, nonce, hash);
                yield break;
            }
            
            if (nonce % 10000 == 0)
                yield return null; // Don't freeze Unity
        }
        
        // No solution found in range
        yield return SubmitResult(task, 0, "");
    }
    
    IEnumerator SubmitResult(MiningTask task, int nonce, string hash)
    {
        var result = new {
            assignment_id = task.assignment_id,
            job_id = task.job_id,
            device_id = deviceId,
            nonce = nonce,
            hash = hash,
            conf = 1.0
        };
        
        string json = JsonUtility.ToJson(result);
        
        using (UnityWebRequest www = UnityWebRequest.Post(
            "http://192.168.178.12:8083/result", json, "application/json"))
        {
            yield return www.SendWebRequest();
            
            if (www.result == UnityWebRequest.Result.Success)
            {
                var response = JsonUtility.FromJson<ResultResponse>(www.downloadHandler.text);
                if (response.winner)
                {
                    Debug.Log($"🎉 WINNER! Block {response.block_index}, " +
                              $"Reward: {response.reward} coins!");
                }
            }
        }
    }
    
    string ComputeSHA256(string input)
    {
        using (var sha256 = System.Security.Cryptography.SHA256.Create())
        {
            byte[] bytes = System.Text.Encoding.UTF8.GetBytes(input);
            byte[] hash = sha256.ComputeHash(bytes);
            return BitConverter.ToString(hash).Replace("-", "").ToLower();
        }
    }
}

// Custom SSE Download Handler
class SSEDownloadHandler : DownloadHandlerScript
{
    private MiningClient client;
    private string buffer = "";
    
    public SSEDownloadHandler(MiningClient client) : base()
    {
        this.client = client;
    }
    
    protected override bool ReceiveData(byte[] data, int dataLength)
    {
        string text = System.Text.Encoding.UTF8.GetString(data, 0, dataLength);
        buffer += text;
        
        // Parse SSE events
        string[] lines = buffer.Split(new[] { "\n\n" }, StringSplitOptions.None);
        
        for (int i = 0; i < lines.Length - 1; i++)
        {
            string line = lines[i];
            if (line.StartsWith("data: "))
            {
                string json = line.Substring(6);
                var msg = JsonUtility.FromJson<SSEMessage>(json);
                
                if (msg.type == "assignment")
                {
                    client.OnAssignment(json);
                }
            }
        }
        
        buffer = lines[lines.Length - 1];
        return true;
    }
}

[Serializable]
class SSEMessage
{
    public string type;
}

[Serializable]
class MiningTask
{
    public string assignment_id;
    public string job_id;
    public string block_header;
    public int difficulty;
    public int nonce_range_start;
    public int nonce_range_end;
    public string algorithm;
}

[Serializable]
class ResultResponse
{
    public bool ok;
    public bool winner;
    public int block_index;
    public float reward;
}
```

### REST API (Alternative zu SSE)

Falls SSE nicht funktioniert, kann Unity auch pollen:

```bash
# Status abrufen
curl "http://192.168.178.12:8083/status?device_id=Unity1"
```

---

## 🔄 WORKFLOW

### 1. n8n AI Agent erstellt Job

```
AI Agent: "Erstelle einen Mining Job mit 20 Tasks"
  ↓
Tool: create_mining_job(num_tasks=20)
  ↓
Server: Block #5 wird generiert, 20 Tasks erstellt
  ↓
Tasks landen in Queue
```

### 2. Unity Devices bekommen Tasks (via SSE!)

```
Unity1 verbindet zu SSE
  ↓
Bekommt sofort Task 1 gepusht
  ↓
Beginnt Mining (nonce 0-1000000)
  ↓
Während dem Mining bekommt Unity1 Task 2 gepusht
  (wenn max_inflight=2)
```

### 3. Result Submission

```
Unity1 findet Hash "0000abc..."
  ↓
POST /result {nonce: 123456, hash: "0000..."}
  ↓
Server prüft Hash
  ↓
WINNER! 50 Coins für Unity1
  ↓
Block #5 zur Blockchain hinzugefügt
  ↓
Job als "completed" markiert
  ↓
Alle anderen Tasks cancelled
```

### 4. Timeout & Retry

```
Unity2 bekommt Task 5
  ↓
120 Sekunden vergehen
  ↓
Unity2 antwortet nicht
  ↓
Task 5 wird automatisch neu vergeben
  ↓
Unity3 bekommt Task 5
```

---

## 🎯 VORTEILE DIESER ARCHITEKTUR

### ✅ Push statt Poll
- Unity wartet nicht, bekommt Tasks sofort
- Kein `/next` Polling mehr
- Effizienter!

### ✅ Saubere Trennung
- Job Management ≠ Task Distribution
- Verschiedene Sicherheit möglich
- Unabhängig skalierbar

### ✅ Auto-Retry
- Timeouts werden automatisch behandelt
- Keine verlorenen Tasks
- Wie im Beispiel-Code!

### ✅ In-Memory Queue
- `asyncio.Queue` für Devices
- Schnell und einfach
- Perfekt für Prototyping

---

## 📊 MONITORING

### Job Server Health
```bash
curl http://192.168.178.12:8082/health
```

### Device Server Health
```bash
curl http://192.168.178.12:8083/health
```

### Device Status
```bash
curl "http://192.168.178.12:8083/status?device_id=Unity1"
```

---

## 🔐 OPTIONAL: HMAC Signature

Für Produktiv-Umgebung kannst du HMAC aktivieren:

1. `.env` erstellen:
```bash
HMAC_SECRET=your_secret_key_here
```

2. Unity muss dann Signatures senden:
```csharp
string sig = ComputeHMAC(assignmentId, secret);
```

---

## 🐛 DEBUGGING

### Logs

Beide Server loggen ausführlich:
```
📨 MCP: tools/call
🔧 Tool: create_mining_job({'num_tasks': 10})
📋 Job job_abc123: Block #5, 10 tasks, diff=4
🎮 Device connected: Unity1
📤 Unity1: Assignment sent
🎉 POTENTIAL WINNER: Unity1 found hash!
🏆 WINNER CONFIRMED: Unity1 - Block #5 - Reward: 50.0 coins
```

### Test ohne Unity

```bash
# SSE verbinden (Terminal)
curl -N "http://192.168.178.12:8083/sse?device_id=test1"

# In anderem Terminal: Result senden
curl -X POST http://192.168.178.12:8083/result \
  -H "Content-Type: application/json" \
  -d '{
    "assignment_id": "asg_xxx",
    "job_id": "job_xxx",
    "device_id": "test1",
    "nonce": 0,
    "hash": "",
    "conf": 1.0
  }'
```

---

## 🚀 NEXT STEPS

1. **Start Server:**
   ```bash
   ./start_mining.sh
   ```

2. **n8n MCP Tool:**
   - SSE Endpoint: `http://192.168.178.12:8082/sse`
   - Test: `create_mining_job`

3. **Unity SSE:**
   - Kopiere C# Code oben
   - Verbinde zu: `http://192.168.178.12:8083/sse?device_id=Unity1`

4. **AI Agent Prompt:**
   ```
   Erstelle einen Mining Job mit 10 Tasks.
   Wie ist der Pool Status?
   Zeige mir das Leaderboard.
   ```

---

## 📝 DATEIEN ÜBERSICHT

```
mining-pool/
├── shared_state.py          # Gemeinsamer State (Blockchain, Jobs, Queue)
├── mcp_job_server.py        # Job Management für n8n (Port 8082)
├── mcp_device_server.py     # Task Distribution für Unity (Port 8083)
├── requirements.txt         # Python Dependencies
├── start_mining.sh          # Startup Script
└── mining.env               # Config (optional)
```

---

## 💡 TIPPS

- **Difficulty anpassen:** In `shared_state.py` → `base_difficulty`
- **Mehr Devices:** Einfach mehrere Unity Clients mit verschiedenen `device_id`
- **Production:** Redis statt In-Memory für Multi-Server Setup
- **Monitoring:** Prometheus Metrics hinzufügen

---

**Viel Erfolg beim Minen! ⛏️**
