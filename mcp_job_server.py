#!/usr/bin/env python3
"""
MCP Job Server - FastMCP mit http_app() + uvicorn
============================================================

Tools:
- create_mining_job
- get_pool_status
- get_leaderboard
- get_job_details
- list_devices

Port: 8082
SSE Endpoint: http://192.168.178.12:8082/sse
"""

from __future__ import annotations
import os, json, time, asyncio, uuid
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# Redis helpers for shared state
from redis_state import (
    get_redis,
    get_connected_devices,
    get_all_inflight,
    get_device_stats,
    get_leaderboard as redis_get_leaderboard,
    ensure_device_idx,
    next_seq,
)

# Stratum (real mining) helpers
from stratum_proxy import (
    StratumClient,
    get_current_job as stratum_get_current_job,
    get_pool_stats as stratum_get_pool_stats,
    submit_result as stratum_submit_result,
)


# Import shared state
from shared_state import state, Assignment, Job

load_dotenv()

mcp = FastMCP(
    name="mining-jobs",
    instructions="Mining Pool Manager over HTTP. SSE für n8n AI Agent.",
    version="1.0.0",
)

# =========================
# Config / ENV
# =========================
HOST = os.getenv("FASTMCP_HOST", "0.0.0.0")
PORT = int(os.getenv("FASTMCP_PORT", "8082"))
REAL_MINING_ENABLED = os.getenv("REAL_MINING_ENABLED", "0") == "1"
XMR_WALLET = os.getenv("XMR_WALLET_ADDRESS", "")
POOL_HOST = os.getenv("POOL_HOST", "xmr-eu1.nanopool.org")
POOL_PORT = int(os.getenv("POOL_PORT", "10300"))
WORKER_NAME = os.getenv("WORKER_NAME", "game-mcp")

# =========================
# Pydantic Models for Tool Schemas (n8n compatibility)
# =========================

class JobResponse(BaseModel):
    """Response model for job creation"""
    success: bool = Field(description="Whether job was created successfully")
    job_id: str = Field(description="Unique job ID")
    block_index: int = Field(description="Block index number")
    difficulty: int = Field(description="Mining difficulty")
    potential_reward: float = Field(description="Potential block reward")
    tasks_created: int = Field(description="Number of tasks created")
    message: str = Field(description="Human-readable status message")
    error: str = Field(default="", description="Error message if failed")

class PoolStatus(BaseModel):
    """Response model for pool status"""
    success: bool
    blockchain: dict = Field(description="Blockchain status")
    pool: dict = Field(description="Pool statistics")
    recent_blocks: list = Field(description="Recent blocks")

class LeaderboardEntry(BaseModel):
    """Single leaderboard entry"""
    rank: int
    device_id: str
    coins: float
    blocks_found: int
    tasks_completed: int

class LeaderboardResponse(BaseModel):
    """Response model for leaderboard"""
    success: bool
    leaderboard: List[LeaderboardEntry]
    total_miners: int

class DeviceInfo(BaseModel):
    """Single device info"""
    device_id: str
    status: str
    inflight: int
    coins: float
    blocks_found: int
    tasks_completed: int

class DeviceListResponse(BaseModel):
    """Response model for device list"""
    success: bool
    total_devices: int
    active_devices: int
    devices: List[DeviceInfo]

class JobDetails(BaseModel):
    """Job details response"""
    job_id: str
    block_index: int
    difficulty: int
    reward: float
    status: str
    tasks_created: int
    tasks_completed: int
    progress: float
    winner: str = ""
    winning_hash: str = ""
    created_at: str

class JobDetailsResponse(BaseModel):
    """Response model for job details"""
    success: bool
    job: JobDetails | None = None
    error: str = ""

# =========================
# MCP Tools
# =========================

@mcp.tool()
async def create_mining_job(num_tasks: float = 10, chunk_size: float = 1000000) -> JobResponse:
    """
    Erstellt einen neuen Mining Job und verteilt Tasks an verbundene Devices.
    
    Args:
        num_tasks: Anzahl der Mining Tasks (default: 10, max: 100)
        chunk_size: Nonce-Range pro Task (default: 1000000)
    
    Returns:
        JobResponse: Job-Details mit success, job_id, block_index, difficulty, reward, tasks_created
    """
    try:
        # Validiere Input
        num_tasks_int = max(1, min(int(num_tasks), 100))  # Limit 1-100
        chunk_size_int = max(1000, min(int(chunk_size), 10000000))  # Limit 1k-10M
        
        # Hole nächsten Block
        block = state.blockchain.get_next_block()
        
        # Erstelle Job (mit numeric idx)
        job_idx = await next_seq("job")
        job_id = f"job_{job_idx}"
        job = Job(job_id, block, num_tasks_int, chunk_size_int)
        state.jobs[job_id] = job
        
        # Erstelle und verteile Assignments
        for i in range(num_tasks_int):
            asg_idx = await next_seq("asg")
            asg_id = f"asg_{asg_idx}"
            task_data = {
                "block_header": block.header,
                "difficulty": block.difficulty,
                "nonce_start": i * chunk_size_int,
                "nonce_end": (i + 1) * chunk_size_int,
                "algorithm": "sha256"
            }
            asg = Assignment(job_id, asg_id, task_data)
            state.assignments[asg_id] = asg
            await state.assign_to_device_or_pending(asg)
            job.tasks_created += 1
        # Best-effort pending drain
        try:
            await state.drain_pending()
        except Exception:
            pass
        
        print(f"✅ Created job {job_id} for block #{block.index}")
        return JobResponse(
            success=True,
            job_id=job_id,
            block_index=block.index,
            difficulty=block.difficulty,
            potential_reward=float(block.reward),
            tasks_created=num_tasks_int,
            message=f"Mining job created for Block #{block.index} with {num_tasks_int} tasks"
        )
        
    except Exception as e:
        error_msg = f"Failed to create mining job: {str(e)}"
        print(f"❌ {error_msg}")
        return JobResponse(
            success=False,
            job_id="",
            block_index=0,
            difficulty=0,
            potential_reward=0.0,
            tasks_created=0,
            message=error_msg,
            error=error_msg
        )

@mcp.tool()
async def get_pool_status() -> PoolStatus:
    """
    Gibt den aktuellen Status des Mining Pools zurück.
    
    Returns:
        PoolStatus: Pool-Status mit blockchain, pool und recent_blocks Informationen
    """
    try:
        active_jobs = [j for j in state.jobs.values() if j.status == "active"]
        r = get_redis()
        connected = await get_connected_devices()
        inflight = await get_all_inflight()
        pending_count = int(await r.llen("assignments:pending"))
        
        return PoolStatus(
            success=True,
            blockchain={
                "height": len(state.blockchain.chain),
                "current_difficulty": state.blockchain.base_difficulty,
                "pending_block": state.blockchain.pending_block is not None
            },
            pool={
                "active_jobs": len(active_jobs),
                "pending_tasks": pending_count,
                "total_devices": len(connected),
                "active_devices": sum(1 for d in connected if inflight.get(d, 0) > 0)
            },
            recent_blocks=[
                {
                    "index": b.index,
                    "miner": b.miner or "unknown",
                    "reward": float(b.reward),
                    "difficulty": b.difficulty
                }
                for b in state.blockchain.chain[-5:]
            ]
        )
        
    except Exception as e:
        error_msg = f"Failed to get pool status: {str(e)}"
        print(f"❌ {error_msg}")
        return PoolStatus(
            success=False,
            blockchain={},
            pool={},
            recent_blocks=[]
        )

@mcp.tool()
async def get_leaderboard() -> LeaderboardResponse:
    """
    Gibt die Top-10 Miner mit ihren Stats zurück.
    
    Returns:
        LeaderboardResponse: Leaderboard mit Top-Minern sortiert nach Coins
    """
    try:
        leaders = await redis_get_leaderboard(10)
        return LeaderboardResponse(
            success=True,
            leaderboard=[LeaderboardEntry(**entry) for entry in leaders],
            total_miners=len(leaders)
        )
        
    except Exception as e:
        error_msg = f"Failed to get leaderboard: {str(e)}"
        print(f"❌ {error_msg}")
        return LeaderboardResponse(
            success=False,
            leaderboard=[],
            total_miners=0
        )

@mcp.tool()
async def get_job_details(job_id: str) -> JobDetailsResponse:
    """
    Gibt Details zu einem spezifischen Mining Job zurück.
    
    Args:
        job_id: Die Job-ID (z.B. 'job_1', 'job_2')
    
    Returns:
        JobDetailsResponse: Job-Details oder Fehlermeldung
    """
    try:
        if not job_id or not isinstance(job_id, str):
            return JobDetailsResponse(
                success=False,
                error="Invalid job_id provided"
            )
        
        if job_id not in state.jobs:
            return JobDetailsResponse(
                success=False,
                error=f"Job '{job_id}' not found"
            )
        
        job = state.jobs[job_id]
        return JobDetailsResponse(
            success=True,
            job=JobDetails(
                job_id=job.job_id,
                block_index=job.block_index,
                difficulty=job.difficulty,
                reward=float(job.reward),
                status=job.status,
                tasks_created=job.tasks_created,
                tasks_completed=job.tasks_completed,
                progress=round((job.tasks_completed / job.tasks_created * 100) if job.tasks_created > 0 else 0, 2),
                winner=job.winner,
                winning_hash=job.winning_hash,
                created_at=job.created_at
            )
        )
        
    except Exception as e:
        error_msg = f"Failed to get job details: {str(e)}"
        print(f"❌ {error_msg}")
        return JobDetailsResponse(
            success=False,
            error=error_msg
        )

@mcp.tool()
async def list_devices() -> DeviceListResponse:
    """
    Listet alle aktuell verbundenen Mining Devices.
    
    Returns:
        DeviceListResponse: Liste aller Devices mit Stats und Status
    """
    try:
        connected = await get_connected_devices()
        if not connected:
            return DeviceListResponse(
                success=True,
                total_devices=0,
                active_devices=0,
                devices=[]
            )

        inflight = await get_all_inflight()
        devices_info: List[DeviceInfo] = []
        for device_id in connected:
            stats = await get_device_stats(device_id)
            devices_info.append(DeviceInfo(
                device_id=device_id,
                status="active" if inflight.get(device_id, 0) > 0 else "idle",
                inflight=inflight.get(device_id, 0),
                coins=stats.get("coins", 0.0),
                blocks_found=stats.get("blocks_found", 0),
                tasks_completed=stats.get("tasks_completed", 0)
            ))

        devices_info.sort(key=lambda d: d.coins, reverse=True)

        print(f"🎮 Devices: {len(connected)} connected, {sum(1 for d in devices_info if d.status == 'active')} active")
        return DeviceListResponse(
            success=True,
            total_devices=len(devices_info),
            active_devices=sum(1 for d in devices_info if d.status == "active"),
            devices=devices_info
        )
        
    except Exception as e:
        error_msg = f"Failed to list devices: {str(e)}"
        print(f"❌ {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "devices": [],
            "count": 0
        }


# =========================
# Real Mining (Stratum) Tools
# =========================

_stratum_client: StratumClient | None = None
_stratum_started = False


def _ensure_stratum_started() -> None:
    """Start Stratum client once in a background thread (compatible with older fastmcp)."""
    import threading
    global _stratum_client, _stratum_started
    if _stratum_started:
        return
    if not REAL_MINING_ENABLED:
        print("ℹ️ Real mining disabled. Set REAL_MINING_ENABLED=1 to enable.")
        _stratum_started = True  # avoid repeated logging
        return
    if not XMR_WALLET:
        print("❌ REAL_MINING_ENABLED=1 but XMR_WALLET_ADDRESS is missing. Skipping Stratum start.")
        _stratum_started = True
        return
    try:
        _stratum_client = StratumClient(
            pool_host=POOL_HOST,
            pool_port=POOL_PORT,
            wallet_address=XMR_WALLET,
            worker_name=WORKER_NAME,
        )
        print(f"🚀 Starting Stratum client to {POOL_HOST}:{POOL_PORT} as {WORKER_NAME}")

        def _runner():
            asyncio.run(_stratum_client.run())

        t = threading.Thread(target=_runner, name="stratum-client", daemon=True)
        t.start()
        _stratum_started = True
    except Exception as e:
        print(f"❌ Failed to start Stratum client: {e}")


@mcp.tool()
async def get_mining_job(device_id: str = "", device_type: str = "unknown") -> dict:
    """
    Holt den aktuellen Mining-Job vom Stratum-Proxy (real mining).
    Aktivierung via ENV: REAL_MINING_ENABLED=1 und XMR_WALLET_ADDRESS gesetzt.
    """
    _ensure_stratum_started()
    if not REAL_MINING_ENABLED:
        return {"success": False, "error": "Real mining not enabled (set REAL_MINING_ENABLED=1)"}
    job = stratum_get_current_job()
    if not job:
        return {"success": False, "error": "No active mining job from pool"}
    # Pass through job fields as provided by stratum_proxy
    return {"success": True, "job": job, "device_id": device_id, "device_type": device_type}


@mcp.tool()
async def submit_mining_result(task_id: str = "", nonce: str = "", result_hash: str = "") -> dict:
    """
    Reicht ein Mining-Result beim Stratum-Proxy ein.
    Hinweis: task_id entspricht hier dem job_id vom Pool.
    """
    _ensure_stratum_started()
    if not REAL_MINING_ENABLED:
        return {"success": False, "error": "Real mining not enabled (set REAL_MINING_ENABLED=1)"}
    if not task_id or not nonce or not result_hash:
        return {"success": False, "error": "task_id, nonce and result_hash are required"}
    try:
        res = await stratum_submit_result(task_id, nonce, result_hash)
        return {"success": True, **res}
    except Exception as e:
        return {"success": False, "error": f"submit failed: {e}"}


@mcp.tool()
async def get_server_status() -> dict:
    """
    Zeigt Status von Server (MCP), Stratum-Proxy (Pool) und Devices.
    """
    try:
        _ensure_stratum_started()
        connected = await get_connected_devices()
        inflight = await get_all_inflight()
        pool = stratum_get_pool_stats() if REAL_MINING_ENABLED else {"enabled": False}
        return {
            "success": True,
            "mcp": {"host": HOST, "port": PORT},
            "devices": {"total": len(connected), "active": sum(1 for d in connected if inflight.get(d, 0) > 0)},
            "pool": pool,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_nanopool_stats(wallet_address: str = "") -> dict:
    """
    Holt Statistiken vom Pool (via Stratum-Proxy/State). Wallet optional, nutzt ENV.
    """
    _ensure_stratum_started()
    if not REAL_MINING_ENABLED:
        return {"success": False, "error": "Real mining not enabled (set REAL_MINING_ENABLED=1)"}
    stats = stratum_get_pool_stats()
    return {"success": True, "wallet": wallet_address or XMR_WALLET, "stats": stats}

# =========================
# Main – RICHTIGE LÖSUNG!
# =========================

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("📋 MCP JOB SERVER - n8n Integration")
    print("=" * 70)
    print("\n🔗 n8n MCP Client Configuration:")
    print(f"   URL: http://{HOST}:{PORT}/mcp")
    print("   Protocol: StreamableHTTP (JSON-RPC 2.0 over HTTP/SSE)")
    print("   Required headers:")
    print("     • Accept: application/json, text/event-stream")
    print("     • mcp-session-id: <any unique id per run>")
    print("\n🔧 Available Tools:")
    print("   • create_mining_job(num_tasks, chunk_size)")
    print("   • get_pool_status()")
    print("   • get_leaderboard()")
    print("   • get_job_details(job_id)")
    print("   • list_devices()")
    print("\n💡 n8n Setup:")
    print("   1. Add 'MCP Client' tool node")
    print(f"   2. Set URL: http://{HOST}:{PORT}/mcp")
    print("   3. Transport/Protocol: HTTP (StreamableHTTP)")
    print("   4. Use tools via function calls")
    print("\n" + "=" * 70 + "\n")
    # Serve HTTP app on /mcp (FastMCP 2.14+ uses HTTP transport)
    try:
        import uvicorn
        http_app = mcp.http_app(path="/mcp")
        uvicorn.run(http_app, host=HOST, port=PORT)
    except Exception as e:
        print(f"❌ Failed to start HTTP server: {e}")
