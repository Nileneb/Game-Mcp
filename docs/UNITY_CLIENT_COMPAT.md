# Unity MCP Client – Compatibility Notes (Device Server 8083)

This document summarizes required adjustments to the Unity client so it interoperates with the MCP Device Server on port 8083 using a single, centrally managed wallet.

## Server URLs
- Device Server base URL: `http://<host>:8083`
- Health: `GET /health`
- Device Registration: `POST /device/register`
- SSE stream: `GET /sse?device_id=<ID>` (also supported: `GET /sse/device?device_id=<ID>`)
- Real‑Mining Submit (shares): `POST /mining/submit`

## Unity Script Changes (UnityMCPClient)
- Set `mcpServerUrl` to the Device Server URL on port 8083.
- Keep the health check as `GET {mcpServerUrl}/health`.
- Registration: `POST {mcpServerUrl}/device/register` with JSON body:
  ```json
  {
    "device_id": "Unity_<platform>_<unique>",
    "device_type": "Mobile|Desktop|Browser",
    "algorithm": "randomx|sha256",
    "max_concurrent_tasks": 1,
    "platform": "<Unity platform>",
    "system_info": { /* optional hardware info */ }
  }
  ```
  - Response contains:
    - `wallet_address` (server‑managed, use this)
    - `pool_address` (e.g. `xmr-eu1.nanopool.org:10300`)
- SSE: open `GET {mcpServerUrl}/sse?device_id=<ID>` with headers:
  - `Accept: text/event-stream`
  - Optional: `X-Device-Type`, `X-Algorithm`
  - First message is `{"type":"hello", "device_id":"..."}`.
- Share submission: `POST {mcpServerUrl}/mining/submit` with JSON body:
  ```json
  {
    "job_id": "...",          // from received task
    "device_id": "Unity_...",
    "nonce": 12345,
    "hash": "...",
    "hashes_computed": 123456,
    "duration_seconds": 1.23,
    "algorithm": "randomx|sha256"
  }
  ```
  - Response example:
  ```json
  {
    "share_accepted": true,
    "block_found": false,
    "reward": 0.0,
    "reason": "ok",
    "current_balance": 0.0
  }
  ```

## Wallet Handling (Centralized)
- Do not hardcode a wallet in the Unity client.
- Use the wallet provided by the server on `/device/register`.
- The pool address is provided together with the wallet and should be used for display or internal state.

## Notes on SSE Events
- Server emits a `hello` event upon connection.
- For simulated tasks, messages currently include `{"type":"assignment", ...}`.
- For real mining, messages should be `{"type":"mining_job", ...}` with the structure:
  ```json
  {
    "type": "mining_job",
    "job_id": "...",
    "wallet_address": "...",
    "pool_job": {
      "pool_address": "host:port",
      "blob": "<hex>",
      "target": 0,
      "difficulty": 0,
      "algorithm": "randomx|sha256",
      "height": 0
    },
    "nonce_start": 0,
    "nonce_end": 0
  }
  ```

## Troubleshooting
- 404 on `/device/register` or `/sse/device`: ensure the Device Server is at 8083; both endpoints are now supported.
- SSE reset with curl: use `curl -N -H "Accept: text/event-stream" http://<host>:8083/sse?device_id=Unity_Test` to observe streaming.
- No tasks received: verify job creation on the server side and that Redis queues contain assignments for the device ID.
