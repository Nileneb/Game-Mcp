#!/usr/bin/env python3
"""
MCP Job Server - FastMCP Version (wie Paperstream Beispiel)
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
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse

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
SSE_PATH = "/sse"
HEALTH_PATH = "/health"

# =========================
# MCP Tools (wie Paperstream Beispiel - ohne 'parameters' im Decorator)
# =========================

@mcp.tool(tags={"public"})
async def create_mining_job(num_tasks: float = 10, chunk_size: float = 1000000) -> dict:
    """
    Erstellt einen neuen Mining Job. Der Server generiert automatisch den nächsten Block.
    num_tasks: Anzahl der Tasks (default: 10)
    chunk_size: Nonce-Range pro Task (default: 1000000)
    returns: { success, job_id, block_index, difficulty, potential_reward, tasks_created, message }
    """
    try:
        num_tasks_int = int(num_tasks or 10)
        chunk_size_int = int(chunk_size or 1000000)
    except Exception:
        num_tasks_int = 10
        chunk_size_int = 1000000
    
    block = state.blockchain.get_next_block()
    
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    job = Job(job_id, block, num_tasks_int, chunk_size_int)
    state.jobs[job_id] = job
    
    # Assignments erstellen
    for i in range(num_tasks_int):
        asg_id = f"asg_{job_id}_{i}"
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
    
    return {
        "success": True,
        "job_id": job_id,
        "block_index": block.index,
        "difficulty": block.difficulty,
        "potential_reward": block.reward,
        "tasks_created": num_tasks_int,
        "message": f"Mining job created for Block #{block.index}"
    }

@mcp.tool(tags={"public"})
async def get_pool_status() -> dict:
    """
    Aktueller Pool-Status: Blockchain, aktive Jobs, Devices
    returns: { blockchain, pool, recent_blocks }
    """
    active_jobs = [j for j in state.jobs.values() if j.status == "active"]
    
    return {
        "blockchain": {
            "height": len(state.blockchain.chain),
            "current_difficulty": state.blockchain.base_difficulty,
            "pending_block": state.blockchain.pending_block is not None
        },
        "pool": {
            "active_jobs": len(active_jobs),
            "pending_tasks": len(state.pending_queue),
            "total_devices": len(state.device_queues),
            "active_devices": sum(1 for d in state.device_queues if state.device_inflight.get(d, 0) > 0)
        },
        "recent_blocks": [
            {
                "index": b.index,
                "miner": b.miner,
                "reward": b.reward,
                "difficulty": b.difficulty
            }
            for b in state.blockchain.chain[-5:]
        ]
    }

@mcp.tool(tags={"public"})
async def get_leaderboard() -> dict:
    """
    Top-Miner Leaderboard
    returns: { leaderboard: [{ rank, device_id, coins, blocks_found, tasks_completed }] }
    """
    sorted_leaders = sorted(
        state.leaderboard.items(),
        key=lambda x: x[1]["coins"],
        reverse=True
    )[:10]
    
    return {
        "leaderboard": [
            {
                "rank": i + 1,
                "device_id": device_id,
                "coins": stats["coins"],
                "blocks_found": stats["blocks_found"],
                "tasks_completed": stats["tasks_completed"]
            }
            for i, (device_id, stats) in enumerate(sorted_leaders)
        ]
    }

@mcp.tool(tags={"public"})
async def get_job_details(job_id: str) -> dict:
    """
    Details zu einem Job
    job_id: Job ID
    returns: { success, job: { job_id, block_index, difficulty, reward, status, ... } }
    """
    if job_id not in state.jobs:
        return {"success": False, "error": f"Job {job_id} not found"}
    
    job = state.jobs[job_id]
    return {
        "success": True,
        "job": {
            "job_id": job.job_id,
            "block_index": job.block_index,
            "difficulty": job.difficulty,
            "reward": job.reward,
            "status": job.status,
            "tasks_created": job.tasks_created,
            "tasks_completed": job.tasks_completed,
            "winner": job.winner,
            "created_at": job.created_at
        }
    }

@mcp.tool(tags={"public"})
async def list_devices() -> dict:
    """
    Alle verbundenen Devices
    returns: { devices: [{ device_id, inflight_tasks, stats }], count }
    """
    devices = []
    for device_id in state.device_queues:
        devices.append({
            "device_id": device_id,
            "inflight_tasks": state.device_inflight.get(device_id, 0),
            "stats": state.leaderboard.get(device_id, {
                "coins": 0,
                "blocks_found": 0,
                "tasks_completed": 0
            })
        })
    
    return {"devices": devices, "count": len(devices)}

# =========================
# HTTP Routes
# =========================

@mcp.custom_route(HEALTH_PATH, methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    status = await get_pool_status()
    return PlainTextResponse(f"OK - Height: {status['blockchain']['height']}, Jobs: {status['pool']['active_jobs']}")

# =========================
# Main – wie dein Paperstream Beispiel
# =========================

if __name__ == "__main__":
    print()
    print("=" * 70)
    print("📋 MCP JOB SERVER (FastMCP)")
    print("=" * 70)
    print()
    print(f"🔗 n8n MCP Client Tool:")
    print(f"   Server Transport: HTTP Streamable")
    print(f"   Endpoint: http://192.168.178.12:{PORT}{SSE_PATH}")
    print()
    print("🔧 Tools:")
    print("   • create_mining_job")
    print("   • get_pool_status")
    print("   • get_leaderboard")
    print("   • get_job_details")
    print("   • list_devices")
    print()
    print("=" * 70)
    print()
    
    transport = os.getenv("FASTMCP_TRANSPORT", "http").lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        host = os.getenv("FASTMCP_HOST", HOST)
        port = int(os.getenv("FASTMCP_PORT", str(PORT)))
        mcp.run(transport="http", host=host, port=port)
