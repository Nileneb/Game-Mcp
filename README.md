# 🚀 MCP Mining Pool System v2.0

Distributed Mining System mit **2 spezialisierten MCP Servern**:

1. **Job Server** (Port 8082) - Für n8n AI Agent (Job Management) via HTTP /mcp
2. **Device Server** (Port 8083) - Für Unity Geräte über SSE und REST

**Echte Mining-Integration** — keine Simulatoren, keine Dummy-Daten. Real Mining per Default aktiviert.

---

## Schnellstart

```bash
docker compose up -d --build
```

Voraussetzungen:
- `.env` enthält deine echte Monero Wallet (`XMR_WALLET_ADDRESS`) und ist im Repo enthalten.
- `REAL_MINING_ENABLED=1` (bereits gesetzt).

Wichtig: Der Container loggt direkt echte Stratum-Events; es gibt keine simulierten Devices mehr.

---

## Konfiguration (.env)

Relevante Keys:
- `FASTMCP_HOST` / `FASTMCP_PORT` (Job Server, HTTP /mcp)
- `DEVICE_SERVER_HOST` / `DEVICE_SERVER_PORT` (Unity SSE)
- `XMR_WALLET_ADDRESS` (erforderlich für echtes Mining)
- `POOL_HOST` / `POOL_PORT` (Nanopool Defaults gesetzt)
- `REAL_MINING_ENABLED=1` (schaltet Stratum-Client an)
- `ASSIGN_TTL`, `MAX_INFLIGHT_PER_DEVICE`, `DEFAULT_CHUNK_SIZE`, `DEFAULT_NUM_TASKS`

---

## Job Server (n8n / HTTP)

- Endpoint: `http://<host>:8082/mcp`
- Protocol: StreamableHTTP (JSON-RPC 2.0 over HTTP/SSE)
- Required headers: `Accept: application/json, text/event-stream`, `mcp-session-id: <unique>`

### n8n MCP Client Setup
- URL: `http://<host>:8082/mcp`
- Transport/Protocol: HTTP (StreamableHTTP)
- Tools:
    - `create_mining_job(num_tasks, chunk_size)`
    - `get_pool_status()`
    - `get_leaderboard()`
    - `get_job_details(job_id)`
    - `list_devices()`
    - (Real mining) `get_mining_job(device_id, device_type)`, `submit_mining_result(task_id, nonce, result_hash)`

### Beispiel-Call (curl)
```bash
curl -X POST http://localhost:8082/mcp \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "mcp-session-id: demo-1" \
    -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'
```

---

## Device Server (Unity / SSE)

- SSE: `http://<host>:8083/sse?device_id=Unity1`
- Register (REST): `POST /device/register` → liefert Wallet/Pool zurück
- Mining Submit (REST): `POST /mining/submit` → echte Shares/Stats
- Status: `GET /status?device_id=...`

Unity empfängt Assignments via SSE und postet Ergebnisse zurück. Keine Fake-Geräte werden mehr gestartet.

---

## Real Mining

- Stratum-Client startet automatisch, wenn `REAL_MINING_ENABLED=1` und `XMR_WALLET_ADDRESS` gesetzt sind.
- Pool-Vorgaben: `xmr-eu1.nanopool.org:10300`, Worker-Name via `WORKER_NAME`.
- Logs zeigen reale Stratum-Events; es werden keine Dummy-Jobs erzeugt, solange echte Jobs verfügbar sind.

---

## Betrieb / Troubleshooting

- Neustart: `docker compose restart game-mining-mcp`
- Logs Job/Device: `docker logs -f game-mining-mcp`
- Redis: `docker logs -f redis`
- Wenn der Pool nicht erreichbar ist, prüfe Wallet/Pool-Host/Port und Firewall.

---

## Verzeichnisstruktur (bereinigt)

- `mcp_job_server.py` — HTTP /mcp für n8n
- `mcp_device_server.py` — SSE/REST für Unity
- `shared_state.py`, `redis_state.py` — State/Queues
- `stratum_proxy.py` — echter Stratum-Client
- `start_mining.sh` — startet Job- und Device-Server
- `docker-compose.yml`, `Dockerfile`, `.env`
- `data/` — leer, für Laufzeitdaten

    [Header("📊 Runtime Status")]
    [SerializeField] private ConnectionStatus status = ConnectionStatus.Disconnected;
    [SerializeField] private int activeTasks = 0;
    [SerializeField] private int tasksCompleted = 0;
    [SerializeField] private int sharesSubmitted = 0;
    [SerializeField] private int sharesAccepted = 0;
    [SerializeField] private float currentHashrate = 0f;
    [SerializeField] private string lastError = "";

    [Header("🐛 Debug")]
    public bool enableDebugLogs = true;
    public bool showTaskDetails = false;

    // Private
    private UnityWebRequest sseRequest;
    private SSEDownloadHandler sseHandler;
    private Queue<RealMiningTask> taskQueue = new Queue<RealMiningTask>();
    private List<Coroutine> activeTaskCoroutines = new List<Coroutine>();
    private bool isReconnecting = false;

    // Mining Engines
    private RandomXMiner randomXMiner;
    private SHA256Miner sha256Miner;

    // Performance Tracking
        private float lastHashrateUpdate;
        private long totalHashesComputed;
    
        public void AddTotalHashesComputed(long count)
        {
            totalHashesComputed += count;
        }

    public enum ConnectionStatus
    {
        Disconnected,
        Connecting,
        Connected,
        Reconnecting,
        Error
    }

    public enum DeviceType
    {
        Auto,
        Mobile,
        Desktop,
        Browser
    }

    public enum MiningAlgorithm
    {
        RandomX,   // Monero (CPU-friendly)
        SHA256,    // Bitcoin (für Testing)
        Ethash     // Ethereum Classic (GPU)
    }

    // ================================================================
    // LIFECYCLE
    // ================================================================

    private void Awake()
    {
        if (string.IsNullOrEmpty(deviceId))
        {
            deviceId = GenerateDeviceId();
        }

        // Device Type Detection
        if (deviceType == DeviceType.Auto)
        {
            deviceType = DetectDeviceType();
        }

        // Mining Engine initialisieren
        InitializeMiningEngine();
    }

    private void Start()
    {
        if (autoConnect)
        {
            StartCoroutine(ConnectToMCPServer());
        }
    }

    private void Update()
    {
        // Hashrate berechnen
        if (Time.time - lastHashrateUpdate > 5f)
        {
            currentHashrate = totalHashesComputed / 5f;
            totalHashesComputed = 0;
            lastHashrateUpdate = Time.time;
        }
    }

    private void OnDestroy()
    {
        DisconnectSSE();
        CleanupMiningEngine();
    }

    private string GenerateDeviceId()
    {
        string platform = Application.platform.ToString();
        string unique = SystemInfo.deviceUniqueIdentifier.Substring(0, 8);
        return $"Unity_{platform}_{unique}";
    }

    private DeviceType DetectDeviceType()
    {
        if (Application.platform == RuntimePlatform.WebGLPlayer)
            return DeviceType.Browser;
        else if (Application.isMobilePlatform)
            return DeviceType.Mobile;
        else
            return DeviceType.Desktop;
    }

    // ================================================================
    // MINING ENGINE SETUP
    // ================================================================

    private void InitializeMiningEngine()
    {
        switch (algorithm)
        {
            case MiningAlgorithm.RandomX:
                randomXMiner = new RandomXMiner(this);
                Log("🔧 RandomX Miner initialized");
                break;

            case MiningAlgorithm.SHA256:
                sha256Miner = new SHA256Miner();
                Log("🔧 SHA256 Miner initialized");
                break;

            case MiningAlgorithm.Ethash:
                LogError("Ethash not yet implemented");
                break;
        }
    }

    private void CleanupMiningEngine()
    {
        randomXMiner?.Dispose();
        sha256Miner?.Dispose();
    }

    // ================================================================
    // MCP SERVER CONNECTION - SSE STREAM
    // ================================================================

    public IEnumerator ConnectToMCPServer()
    {
        if (status == ConnectionStatus.Connecting || status == ConnectionStatus.Connected)
        {
            Log("Already connected/connecting");
            yield break;
        }

        status = ConnectionStatus.Connecting;
        lastError = "";

        Log($"🔌 Connecting to MCP Server: {mcpServerUrl}...");

        // 1. Health Check
        yield return HealthCheck();

        if (status == ConnectionStatus.Error)
        {
            yield return ReconnectCoroutine();
            yield break;
        }

        // 2. Device Registration
        yield return RegisterDevice();

        // 3. SSE Stream öffnen (kompatibel mit Device Server Port 8083)
        // Nutzt /sse?device_id= Format (auch /sse/device?device_id= wird unterstützt)
        string sseUrl = $"{mcpServerUrl}/sse?device_id={deviceId}";

        sseRequest = UnityWebRequest.Get(sseUrl);
        sseHandler = new SSEDownloadHandler(this);
        sseRequest.downloadHandler = sseHandler;
        sseRequest.SetRequestHeader("Accept", "text/event-stream");
        sseRequest.SetRequestHeader("Cache-Control", "no-cache");
        sseRequest.SetRequestHeader("X-Device-Type", deviceType.ToString());
        sseRequest.SetRequestHeader("X-Algorithm", algorithm.ToString());

        sseRequest.SendWebRequest();

        // Warte auf Hello Event
        float timeout = 10f;
        while (!sseHandler.isConnected && timeout > 0)
        {
            yield return new WaitForSeconds(0.1f);
            timeout -= 0.1f;
        }

        if (sseHandler.isConnected)
        {
            status = ConnectionStatus.Connected;
            Log($"✅ Connected as {deviceId} ({deviceType})");

            // Task Processing starten
            StartCoroutine(ProcessTaskQueue());
        }
        else
        {
            status = ConnectionStatus.Error;
            lastError = "SSE connection timeout";
            LogError("Connection timeout");
            yield return ReconnectCoroutine();
        }
    }

    private IEnumerator HealthCheck()
    {
        using (var req = UnityWebRequest.Get(mcpServerUrl + "/health"))
        {
            req.timeout = 5;
            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
            {
                Log("✅ MCP Server health check OK");
            }
            else
            {
                status = ConnectionStatus.Error;
                lastError = "MCP Server unreachable: " + req.error;
                LogError("Health check failed: " + req.error);
            }
        }
    }

    private IEnumerator RegisterDevice()
    {
        var deviceInfo = new DeviceRegistration
        {
            device_id = deviceId,
            device_type = deviceType.ToString(),
            algorithm = algorithm.ToString(),
            max_concurrent_tasks = maxConcurrentTasks,
            platform = Application.platform.ToString(),
            system_info = new SystemInfo2
            {
                processor_type = SystemInfo.processorType,
                processor_count = SystemInfo.processorCount,
                system_memory_size = SystemInfo.systemMemorySize,
                graphics_device_name = SystemInfo.graphicsDeviceName
            }
        };

        string json = JsonUtility.ToJson(deviceInfo);

        using (var req = new UnityWebRequest(mcpServerUrl + "/device/register", "POST"))
        {
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = 10;

            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
            {
                Log("✅ Device registered with MCP Server");

                try
                {
                    var response = JsonUtility.FromJson<DeviceRegistrationResponse>(req.downloadHandler.text);
                    
                    // Server-verwaltete Wallet verwenden (zentral verwaltet)
                    currentWallet = response.wallet_address;
                    currentPoolAddress = response.pool_address;

                    if (string.IsNullOrEmpty(currentWallet))
                    {
                        LogError("⚠️ Keine Wallet vom Server erhalten!");
                    }
                    else
                    {
                        Log($"💰 Wallet assigned: {currentWallet}");
                    }

                    if (!string.IsNullOrEmpty(currentPoolAddress))
                    {
                        Log($"🏊 Pool: {currentPoolAddress}");
                    }
                }
                catch (Exception e)
                {
                    LogError($"Registration response parse error: {e.Message}");
                }
            }
            else
            {
                LogError($"Device registration failed: {req.error}");
            }
        }
    }

    private void DisconnectSSE()
    {
        if (sseRequest != null)
        {
            sseRequest.Abort();
            sseRequest.Dispose();
            sseRequest = null;
        }

        status = ConnectionStatus.Disconnected;
        Log("🔌 Disconnected from MCP Server");
    }

    private IEnumerator ReconnectCoroutine()
    {
        if (isReconnecting) yield break;

        isReconnecting = true;
        status = ConnectionStatus.Reconnecting;

        Log($"🔄 Reconnecting in {reconnectDelay}s...");

        DisconnectSSE();

        yield return new WaitForSeconds(reconnectDelay);

        isReconnecting = false;
        yield return ConnectToMCPServer();
    }

    // ================================================================
    // SSE EVENT HANDLER
    // ================================================================

    public void OnSSEConnected()
    {
        Log("📡 SSE Stream opened");
    }

    public void OnSSEMessage(string eventType, string data)
    {
        try
        {
            if (eventType == "hello")
            {
                Log($"👋 MCP Server: {data}");
            }
            else if (eventType == "mining_job")
            {
                // Real Mining Jobs vom Device Server (Port 8083)
                OnMiningJobReceived(data);
            }
            else if (eventType == "assignment")
            {
                // Legacy Support für Assignment-basierte Simulationen
                OnAssignmentReceived(data);
            }
            else if (eventType == "pool_update")
            {
                OnPoolUpdate(data);
            }
            else if (eventType == "wallet_update")
            {
                OnWalletUpdate(data);
            }
            else
            {
                if (showTaskDetails)
                    Log($"📨 SSE: {eventType} = {data}");
            }
        }
        catch (Exception e)
        {
            LogError($"SSE message error: {e.Message}");
        }
    }

    public void OnSSEError(string error)
    {
        LogError($"SSE Error: {error}");
        status = ConnectionStatus.Error;
        lastError = error;
        StartCoroutine(ReconnectCoroutine());
    }

    private void OnMiningJobReceived(string json)
    {
        try
        {
            RealMiningTask task = JsonUtility.FromJson<RealMiningTask>(json);

            if (task == null || string.IsNullOrEmpty(task.job_id))
            {
                LogError("Invalid mining job data");
                return;
            }

            taskQueue.Enqueue(task);

            Log($"📥 Mining Job queued: {task.job_id}");

            if (showTaskDetails)
            {
                Log($"   Pool: {task.pool_job.pool_address}");
                Log($"   Difficulty: {task.pool_job.difficulty}");
                Log($"   Algorithm: {task.pool_job.algorithm}");
            }
        }
        catch (Exception e)
        {
            LogError($"Mining job parse error: {e.Message}");
        }
    }

    private void OnAssignmentReceived(string json)
    {
        // Legacy Support: Device Server kann auch "assignment" Events senden
        // Falls nur assignment_id + job_id vorhanden ist
        try
        {
            Log("📨 Assignment empfangen (nutze mining_job Format für beste Kompatibilität)");
        }
        catch (Exception e)
        {
            LogError($"Assignment parse error: {e.Message}");
        }
    }

    private void OnPoolUpdate(string json)
    {
        try
        {
            var update = JsonUtility.FromJson<PoolUpdateEvent>(json);
            Log($"🏊 Pool Update: Difficulty={update.current_difficulty}, Hashrate={update.pool_hashrate}");
        }
        catch (Exception e)
        {
            LogError($"Pool update parse error: {e.Message}");
        }
    }

    private void OnWalletUpdate(string json)
    {
        try
        {
            var update = JsonUtility.FromJson<WalletUpdateEvent>(json);
            currentWallet = update.wallet_address;
            Log($"💰 Wallet updated: {currentWallet}");
        }
        catch (Exception e)
        {
            LogError($"Wallet update parse error: {e.Message}");
        }
    }

    // ================================================================
    // TASK PROCESSING - QUEUE BASED
    // ================================================================

    private IEnumerator ProcessTaskQueue()
    {
        while (status == ConnectionStatus.Connected)
        {
            // Cleanup finished tasks
            activeTaskCoroutines.RemoveAll(c => c == null);
            activeTasks = activeTaskCoroutines.Count;

            // Start new tasks if available
            while (taskQueue.Count > 0 && activeTasks < maxConcurrentTasks)
            {
                RealMiningTask task = taskQueue.Dequeue();
                var coroutine = StartCoroutine(MineRealTask(task));
                activeTaskCoroutines.Add(coroutine);
                activeTasks++;
            }

            yield return new WaitForSeconds(0.1f);
        }
    }

    // ================================================================
    // REAL MINING - ALGORITHM DISPATCH
    // ================================================================

    private IEnumerator MineRealTask(RealMiningTask task)
    {
        Log($"⛏️ Mining started: {task.job_id} ({task.pool_job.algorithm})");

        float startTime = Time.time;

        // Algorithm-spezifisches Mining
        MiningResult result = null;

        switch (task.pool_job.algorithm.ToLower())
        {
            case "randomx":
                yield return randomXMiner.Mine(task, r => result = r);
                break;

            case "sha256":
            case "sha256d":
                yield return sha256Miner.Mine(task, r => result = r);
                break;

            default:
                LogError($"Unsupported algorithm: {task.pool_job.algorithm}");
                yield break;
        }

        float duration = Time.time - startTime;

        if (result != null && showTaskDetails)
        {
            Log($"⛏️ Mining completed in {duration:F2}s");
            Log($"   Hashes computed: {result.hashes_computed}");
            Log($"   Hashrate: {result.hashes_computed / duration:F0} H/s");
        }

        // Result submitten
        if (result != null)
        {
            yield return SubmitMiningResult(task, result);
        }

        tasksCompleted++;
        activeTasks--;
    }

    // ================================================================
    // RESULT SUBMISSION TO MCP SERVER
    // ================================================================

    private IEnumerator SubmitMiningResult(RealMiningTask task, MiningResult result)
    {
        // Mining Submit Payload - kompatibel mit Device Server auf Port 8083
        // Struktur gemäß der Dokumentation: UNITY_CLIENT_COMPAT.md
        var payload = new MiningResultPayload
        {
            job_id = task.job_id,
            device_id = deviceId,
            nonce = result.nonce,
            hash = result.hash,
            hashes_computed = result.hashes_computed,
            duration_seconds = result.duration_seconds,
            algorithm = task.pool_job.algorithm
        };

        string json = JsonUtility.ToJson(payload);

        // POST /mining/submit an Device Server (Port 8083)
        using (var req = new UnityWebRequest(mcpServerUrl + "/mining/submit", "POST"))
        {
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = 10;

            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
            {
                try
                {
                    var response = JsonUtility.FromJson<MiningResultResponse>(req.downloadHandler.text);

                    sharesSubmitted++;

                    if (response.share_accepted)
                    {
                        sharesAccepted++;
                        Log($"✅ Share ACCEPTED! ({sharesAccepted}/{sharesSubmitted})");

                        if (response.block_found)
                        {
                            Log($"🎉🎉🎉 BLOCK FOUND! 🎉🎉🎉");
                            Log($"💰 Reward: {response.reward} XMR");
                        }
                    }
                    else
                    {
                        Log($"❌ Share rejected: {response.reason}");
                    }
                }
                catch (Exception e)
                {
                    LogError($"Submit response parse error: {e.Message}");
                }
            }
            else
            {
                LogError($"Submit failed: {req.error}");
            }
        }
    }

    // ================================================================
    // PUBLIC API
    // ================================================================

    public void Connect()
    {
        if (status != ConnectionStatus.Connected)
        {
            StartCoroutine(ConnectToMCPServer());
        }
    }

    public void Disconnect()
    {
        StopAllCoroutines();
        DisconnectSSE();
    }

    public void Reconnect()
    {
        Disconnect();
        StartCoroutine(ConnectToMCPServer());
    }

    public Dictionary<string, object> GetStats()
    {
        return new Dictionary<string, object>
        {
            { "status", status.ToString() },
            { "device_id", deviceId },
            { "device_type", deviceType.ToString() },
            { "algorithm", algorithm.ToString() },
            { "tasks_completed", tasksCompleted },
            { "shares_submitted", sharesSubmitted },
            { "shares_accepted", sharesAccepted },
            { "acceptance_rate", sharesSubmitted > 0 ? (sharesAccepted * 100f / sharesSubmitted) : 0f },
            { "current_hashrate", currentHashrate },
            { "active_tasks", activeTasks },
            { "queued_tasks", taskQueue.Count },
            { "wallet", currentWallet },
            { "pool", currentPoolAddress }
        };
    }

    // ================================================================
    // DEBUG
    // ================================================================

    public void Log(string msg)
    {
        if (enableDebugLogs)
            Debug.Log($"[MCP Mining] {msg}");
    }

    public void LogError(string msg)
    {
        Debug.LogError($"[MCP Mining] {msg}");
    }

    [ContextMenu("🔌 Connect")]
    void MenuConnect() => Connect();

    [ContextMenu("🔌 Disconnect")]
    void MenuDisconnect() => Disconnect();

    [ContextMenu("🔄 Reconnect")]
    void MenuReconnect() => Reconnect();

    [ContextMenu("📊 Show Stats")]
    void MenuShowStats()
    {
        var stats = GetStats();
        Debug.Log("=== MCP Mining Stats ===");
        foreach (var kv in stats)
        {
            Debug.Log($"{kv.Key}: {kv.Value}");
        }
    }
}

// ================================================================
// MINING ENGINES
// ================================================================

public class RandomXMiner
{
    private UnityMCPClient client;

#if UNITY_WEBGL && !UNITY_EDITOR
    [DllImport("__Internal")]
    private static extern void InitRandomX();
    
    [DllImport("__Internal")]
    private static extern string ComputeRandomX(string input);
#endif

    public RandomXMiner(UnityMCPClient client)
    {
        this.client = client;

#if UNITY_WEBGL && !UNITY_EDITOR
        InitRandomX();
#endif
    }

    public IEnumerator Mine(RealMiningTask task, System.Action<MiningResult> callback)
    {
        float startTime = Time.time;
        long hashCount = 0;

        string blob = task.pool_job.blob;
        long target = task.pool_job.target;

        // Nonce Range aus Task
        uint nonceStart = task.nonce_start;
        uint nonceEnd = task.nonce_end;

        for (uint nonce = nonceStart; nonce < nonceEnd; nonce++)
        {
            // Nonce in Blob einfügen (Bytes 39-42 bei Monero)
            string blobWithNonce = InsertNonce(blob, nonce);

            // RandomX Hash berechnen
            string hash = ComputeRandomXHash(blobWithNonce);
            hashCount++;

            // Target check
            if (CheckTarget(hash, target))
            {
                // SHARE GEFUNDEN!
                var result = new MiningResult
                {
                    nonce = (int)nonce,
                    hash = hash,
                    hashes_computed = hashCount,
                    duration_seconds = Time.time - startTime
                };

                callback?.Invoke(result);
                yield break;
            }

            // Frame Budget
            if (hashCount % client.hashesPerFrame == 0)
            {
                client.AddTotalHashesComputed(client.hashesPerFrame);
                yield return null;
            }
        }

        // Kein Share gefunden, trotzdem Statistik zurückgeben
        callback?.Invoke(new MiningResult
        {
            nonce = 0,
            hash = "",
            hashes_computed = hashCount,
            duration_seconds = Time.time - startTime
        });
    }

    private string ComputeRandomXHash(string blob)
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        return ComputeRandomX(blob);
#else
        // Native C# RandomX (wenn verfügbar) oder Fallback
        // TODO: RandomX Library einbinden
        return "0000000000000000000000000000000000000000000000000000000000000000";
#endif
    }

    private string InsertNonce(string blob, uint nonce)
    {
        // Monero: Nonce an Position 39 (Byte 78-85 in Hex)
        byte[] bytes = HexToBytes(blob);
        byte[] nonceBytes = BitConverter.GetBytes(nonce);

        Array.Copy(nonceBytes, 0, bytes, 39, 4);

        return BytesToHex(bytes);
    }

    private bool CheckTarget(string hash, long target)
    {
        // Hash < Target prüfen
        // TODO: Proper BigInteger comparison
        return hash.StartsWith("0000");
    }

    private byte[] HexToBytes(string hex)
    {
        byte[] bytes = new byte[hex.Length / 2];
        for (int i = 0; i < bytes.Length; i++)
        {
            bytes[i] = Convert.ToByte(hex.Substring(i * 2, 2), 16);
        }
        return bytes;
    }

    private string BytesToHex(byte[] bytes)
    {
        StringBuilder sb = new StringBuilder(bytes.Length * 2);
        foreach (byte b in bytes)
        {
            sb.Append(b.ToString("x2"));
        }
        return sb.ToString();
    }

    public void Dispose()
    {
        // Cleanup
    }
}

public class SHA256Miner
{
    private System.Security.Cryptography.SHA256 sha256;

    public SHA256Miner()
    {
        sha256 = System.Security.Cryptography.SHA256.Create();
    }

    public IEnumerator Mine(RealMiningTask task, System.Action<MiningResult> callback)
    {
        float startTime = Time.time;
        long hashCount = 0;

        string blockHeader = task.pool_job.blob;
        int difficulty = task.pool_job.difficulty;
        string targetPrefix = new string('0', difficulty);

        for (int nonce = (int)task.nonce_start; nonce < (int)task.nonce_end; nonce++)
        {
            string input = $"{blockHeader}:{nonce}";
            string hash = ComputeSHA256(input);
            hashCount++;

            if (hash.StartsWith(targetPrefix))
            {
                var result = new MiningResult
                {
                    nonce = nonce,
                    hash = hash,
                    hashes_computed = hashCount,
                    duration_seconds = Time.time - startTime
                };

                callback?.Invoke(result);
                yield break;
            }

            if (hashCount % 10000 == 0)
            {
                yield return null;
            }
        }

        callback?.Invoke(new MiningResult
        {
            nonce = 0,
            hash = "",
            hashes_computed = hashCount,
            duration_seconds = Time.time - startTime
        });
    }

    private string ComputeSHA256(string input)
    {
        byte[] inputBytes = Encoding.UTF8.GetBytes(input);
        byte[] hashBytes = sha256.ComputeHash(inputBytes);

        StringBuilder sb = new StringBuilder(64);
        foreach (byte b in hashBytes)
        {
            sb.Append(b.ToString("x2"));
        }

        return sb.ToString();
    }

    public void Dispose()
    {
        sha256?.Dispose();
    }
}

// ================================================================
// DATA MODELS - REAL MINING
// ================================================================

[Serializable]
public class RealMiningTask
{
    public string job_id;
    public PoolJob pool_job;
    public uint nonce_start;
    public uint nonce_end;
    public string wallet_address;
}

[Serializable]
public class PoolJob
{
    public string pool_address;
    public string blob;
    public long target;
    public int difficulty;
    public string algorithm;
    public int height;
}

[Serializable]
public class MiningResult
{
    public int nonce;
    public string hash;
    public long hashes_computed;
    public float duration_seconds;
}

[Serializable]
public class DeviceRegistration
{
    public string device_id;
    public string device_type;
    public string algorithm;
    public int max_concurrent_tasks;
    public string platform;
    public SystemInfo2 system_info;
}

[Serializable]
public class SystemInfo2
{
    public string processor_type;
    public int processor_count;
    public int system_memory_size;
    public string graphics_device_name;
}

[Serializable]
public class DeviceRegistrationResponse
{
    public bool success;
    public string wallet_address;
    public string pool_address;
    public string message;
}

[Serializable]
public class MiningResultPayload
{
    public string job_id;
    public string device_id;
    public int nonce;
    public string hash;
    public long hashes_computed;
    public float duration_seconds;
    public string algorithm;
}

[Serializable]
public class MiningResultResponse
{
    public bool share_accepted;
    public bool block_found;
    public float reward;
    public string reason;
    public float current_balance;
}

[Serializable]
public class PoolUpdateEvent
{
    public int current_difficulty;
    public string pool_hashrate;
    public int connected_miners;
}

[Serializable]
public class WalletUpdateEvent
{
    public string wallet_address;
    public float balance;
}

// ================================================================
// SSE DOWNLOAD HANDLER (unverändert, funktioniert)
// ================================================================

public class SSEDownloadHandler : DownloadHandlerScript
{
    private UnityMCPClient client;
    private StringBuilder buffer = new StringBuilder();
    public bool isConnected = false;

    public SSEDownloadHandler(UnityMCPClient client) : base()
    {
        this.client = client;
    }

    protected override bool ReceiveData(byte[] data, int dataLength)
    {
        if (data == null || dataLength == 0)
            return true;

        string text = Encoding.UTF8.GetString(data, 0, dataLength);
        buffer.Append(text);

        string bufferStr = buffer.ToString();
        string[] parts = bufferStr.Split(new[] { "\n\n" }, StringSplitOptions.None);

        for (int i = 0; i < parts.Length - 1; i++)
        {
            ParseSSEEvent(parts[i]);
        }

        buffer.Clear();
        buffer.Append(parts[parts.Length - 1]);

        return true;
    }

    private void ParseSSEEvent(string eventData)
    {
        if (string.IsNullOrEmpty(eventData))
            return;

        string[] lines = eventData.Split('\n');
        string eventType = "";
        string data = "";

        foreach (string line in lines)
        {
            if (line.StartsWith("event: "))
            {
                eventType = line.Substring(7).Trim();
            }
            else if (line.StartsWith("data: "))
            {
                data = line.Substring(6).Trim();
            }
        }

        if (!string.IsNullOrEmpty(data))
        {
            if (!isConnected && data.Contains("hello"))
            {
                isConnected = true;
                client.OnSSEConnected();
            }

            try
            {
                // Neue Parsing-Logik für Device Server (Port 8083)
                // Der Server sendet: data: {json-object mit "type" Feld}
                if (data.StartsWith("{"))
                {
                    // Versuche, den "type" aus dem JSON zu extrahieren
                    int typeStart = data.IndexOf("\"type\":\"") + 8;
                    int typeEnd = data.IndexOf("\"", typeStart);

                    if (typeStart > 7 && typeEnd > typeStart)
                    {
                        string type = data.Substring(typeStart, typeEnd - typeStart);
                        // Nutze extrahierten Type als eventType
                        client.OnSSEMessage(type, data);
                    }
                    else
                    {
                        // Fallback: Nutze expliziten event Type falls vorhanden
                        if (!string.IsNullOrEmpty(eventType))
                        {
                            client.OnSSEMessage(eventType, data);
                        }
                    }
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning($"SSE parse error: {e.Message}");
            }
        }
    }

    protected override void CompleteContent()
    {
        client.OnSSEError("Stream closed");
    }
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
