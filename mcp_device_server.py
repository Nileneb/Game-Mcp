#!/usr/bin/env python3
"""
MCP Device Server - Für Unity Devices
======================================

SSE Push für Tasks → Unity Devices
POST für Results ← Unity Devices

Port: 8083
SSE Endpoint: http://192.168.178.12:8083/sse
"""

import asyncio
import json
import hashlib
import uuid
import logging
import time
import os
from datetime import datetime
from aiohttp import web
import aiohttp_cors

# Redis helpers
from redis_state import (
    register_device,
    unregister_device,
    blpop_task,
    get_connected_devices,
    get_inflight,
    get_device_stats,
    inc_tasks_completed,
    add_coins,
    inc_blocks_found,
    decr_inflight,
)

# Import shared state
from shared_state import state
from stratum_proxy import submit_result as stratum_submit_result

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp-devices")

HOST = os.getenv("DEVICE_SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("DEVICE_SERVER_PORT", "8083"))
XMR_WALLET = os.getenv("XMR_WALLET_ADDRESS", "")
POOL_HOST = os.getenv("POOL_HOST", "xmr-eu1.nanopool.org")
POOL_PORT = int(os.getenv("POOL_PORT", "10300"))

# ============================================================================
# SSE STREAM FÜR UNITY DEVICES
# ============================================================================

async def handle_device_sse(request):
    """
    GET /sse?device_id=Unity1
    
    Unity Device verbindet sich hier und bekommt Tasks per SSE gepusht!
    """
    device_id = request.query.get("device_id", f"device_{uuid.uuid4().hex[:8]}")

    logger.info(f"🎮 Device connected: {device_id}")

    # Register device in Redis (presence + idx + init stats)
    await register_device(device_id)
    
    response = web.StreamResponse(
        status=200,
        headers={
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )
    await response.prepare(request)
    
    # Hello Event
    await response.write(
        f"data: {json.dumps({'type': 'hello', 'device_id': device_id})}\n\n".encode()
    )
    
    # Attempt to drain pending assignments via Redis (safe across processes)
    try:
        await state.drain_pending()
    except Exception:
        pass
    
    try:
        while True:
            # Warte auf Assignment oder Timeout
            try:
                msg = await blpop_task(device_id, timeout=30)
                if not msg:
                    # Timeout → send ping below
                    raise asyncio.TimeoutError()
                data = json.dumps(msg)
                await response.write(f"data: {data}\n\n".encode())
                logger.info(f"📤 {device_id}: Assignment sent")
            except asyncio.TimeoutError:
                # Ping senden
                await response.write(b": ping\n\n")
    
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in SSE stream: {e}")
    finally:
        # Cleanup
        await unregister_device(device_id)
        logger.info(f"🎮 Device disconnected: {device_id}")
    
    return response

# ============================================================================
# RESULT SUBMISSION
# ============================================================================

async def handle_submit_result(request):
    """
    POST /result
    
    Unity Device submittet Mining-Ergebnis
    
    Body:
    {
        "assignment_id": "asg_xxx",
        "job_id": "job_xxx",
        "device_id": "Unity1",
        "nonce": 12345,
        "hash": "0000abc...",
        "conf": 1.0
    }
    """
    try:
        body = await request.json()
        
        assignment_id = body.get("assignment_id")
        job_id = body.get("job_id")
        device_id = body.get("device_id")
        nonce = body.get("nonce")
        hash_result = body.get("hash")
        conf = body.get("conf", 1.0)
        
        if not assignment_id:
            return web.json_response({"ok": False, "error": "Invalid assignment"}, status=400)

        asg = state.assignments.get(assignment_id)
        job = state.jobs.get(job_id)
        
        # Assignment als done markieren (best-effort)
        if asg:
            asg.status = "done"
            asg.updated_at = time.time()
        
        # Inflight counter reduzieren
        if device_id:
            await decr_inflight(device_id)
        
        # Job stats (best-effort if present in this process)
        if job:
            job.tasks_completed += 1
        
        # Leaderboard stats
        await inc_tasks_completed(device_id)
        
        # Prüfe ob gültiger Hash gefunden (via Blockchain validator)
        if hash_result:
            logger.info(f"🎉 POTENTIAL WINNER: {device_id} submitted hash!")

            result = state.blockchain.submit_solution(nonce, hash_result, device_id)
            
            if result["success"]:
                # Reward vergeben
                await add_coins(device_id, float(result["reward"]))
                await inc_blocks_found(device_id)
                
                # Job als completed markieren (best-effort)
                if job:
                    job.status = "completed"
                    job.winner = device_id
                    job.winning_hash = hash_result
                    job.winning_nonce = nonce
                
                # Alle pending tasks dieses Jobs canceln
                for asg_id2, a2 in list(state.assignments.items()):
                    if a2.job_id == job_id and a2.status in ("queued", "assigned"):
                        a2.status = "cancelled"
                
                logger.info(f"🏆 WINNER CONFIRMED: {device_id} - Block #{result['block_index']} - Reward: {result['reward']:.4f} coins")
                
                # Pending queue clearen
                await state.drain_pending()
                
                return web.json_response({
                    "ok": True,
                    "winner": True,
                    "reward": result["reward"],
                    "block_index": result["block_index"],
                    "job_closed": True,
                    "message": f"🎉 WINNER! Block #{result['block_index']} mined! Reward: {result['reward']:.4f} coins"
                })
        
        # Kein Winner - nächstes Assignment verteilen
        await state.drain_pending()
        
        return web.json_response({
            "ok": True,
            "winner": False,
            "job_closed": job.status == "completed",
            "message": "Task completed, no valid hash found"
        })
    
    except Exception as e:
        logger.error(f"Error in submit_result: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

# ============================================================================
# UNITY COMPAT: DEVICE REGISTRATION & REAL-MINING SUBMIT
# ============================================================================

async def handle_device_register(request):
    """POST /device/register — Unity device sends metadata, server returns wallet/pool."""
    try:
        body = await request.json()
        device_id = body.get("device_id") or f"device_{uuid.uuid4().hex[:8]}"
        device_type = body.get("device_type", "unknown")
        algorithm = body.get("algorithm", "unknown")
        platform = body.get("platform", "unknown")

        await register_device(device_id)

        # Basic logging for visibility
        logger.info(f"📝 Device registered: {device_id} ({device_type}, alg={algorithm}, platform={platform})")

        return web.json_response({
            "success": True,
            "wallet_address": XMR_WALLET,
            "pool_address": f"{POOL_HOST}:{POOL_PORT}",
            "message": "Device registered"
        })
    except Exception as e:
        logger.error(f"Error in device register: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_mining_submit(request):
    """POST /mining/submit — Unity submits a share for real mining.

    Expected body:
    {
      "job_id": "...",
      "device_id": "Unity_...",
      "nonce": 12345,
      "hash": "...",
      "hashes_computed": 123456,
      "duration_seconds": 1.23,
      "algorithm": "randomx|sha256"
    }
    """
    try:
        body = await request.json()
        job_id = body.get("job_id", "")
        device_id = body.get("device_id", "")
        nonce = str(body.get("nonce", ""))
        result_hash = body.get("hash", "")

        if not job_id or not nonce or not result_hash:
            return web.json_response({
                "share_accepted": False,
                "reason": "invalid_payload"
            }, status=400)

        # Submit to Stratum proxy (async)
        try:
            submit_resp = await stratum_submit_result(job_id, nonce, result_hash)
        except Exception as se:
            logger.error(f"Stratum submit error: {se}")
            submit_resp = {"submitted": False, "error": str(se)}

        # Update simple stats
        if device_id:
            await inc_tasks_completed(device_id)

        # Map response for Unity
        share_accepted = bool(submit_resp.get("accepted", submit_resp.get("submitted", False)))
        block_found = bool(submit_resp.get("block_found", False))
        reward = float(submit_resp.get("reward", 0.0))
        reason = submit_resp.get("error") or submit_resp.get("reason") or ("ok" if share_accepted else "rejected")

        if reward > 0 and device_id:
            await add_coins(device_id, reward)

        return web.json_response({
            "share_accepted": share_accepted,
            "block_found": block_found,
            "reward": reward,
            "reason": reason,
            "current_balance": 0.0
        })
    except Exception as e:
        logger.error(f"Error in mining submit: {e}")
        return web.json_response({"share_accepted": False, "reason": str(e)}, status=500)

# ============================================================================
# DEVICE API
# ============================================================================

async def handle_device_status(request):
    """GET /status?device_id=xxx"""
    device_id = request.query.get("device_id", "unknown")

    connected_list = await get_connected_devices()
    connected = device_id in connected_list
    inflight = await get_inflight(device_id)
    stats = await get_device_stats(device_id)

    return web.json_response({
        "device_id": device_id,
        "connected": connected,
        "inflight_tasks": inflight,
        "stats": stats,
    })

async def handle_health(request):
    """GET /health"""
    try:
        from redis_state import get_redis, get_connected_devices
        r = get_redis()
        connected = await get_connected_devices()
        pending = int(await r.llen("assignments:pending"))
        return web.json_response({
            "status": "healthy",
            "server": "MCP Device Server",
            "connected_devices": len(connected),
            "pending_tasks": pending,
        })
    except Exception:
        # Fallback to legacy in-memory counts
        return web.json_response({
            "status": "healthy",
            "server": "MCP Device Server",
            "connected_devices": len(getattr(state, 'device_queues', {})),
            "pending_tasks": len(getattr(state, 'pending_queue', [])),
        })

# ============================================================================
# MAIN
# ============================================================================

async def main():
    app = web.Application()
    
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*"
        )
    })
    
    # SSE für Devices
    app.router.add_get('/sse', handle_device_sse)
    # Unity client compatibility path
    app.router.add_get('/sse/device', handle_device_sse)
    
    # Result Submission
    app.router.add_post('/result', handle_submit_result)
    # Unity client real-mining submit endpoint
    app.router.add_post('/mining/submit', handle_mining_submit)
    
    # Device Status
    app.router.add_get('/status', handle_device_status)
    
    # Health
    app.router.add_get('/health', handle_health)
    
    for route in list(app.router.routes()):
        cors.add(route)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    
    print()
    print("=" * 70)
    print("🎮 MCP DEVICE SERVER (Unity Devices)")
    print("=" * 70)
    print()
    print("🔗 Unity Device API:")
    print(f"   SSE Stream:  GET  http://192.168.178.12:{PORT}/sse?device_id=Unity1")
    print(f"   Submit:      POST http://192.168.178.12:{PORT}/result")
    print(f"   Status:      GET  http://192.168.178.12:{PORT}/status?device_id=Unity1")
    print()
    print("📡 SSE Events:")
    print("   • type: hello        - Device connected")
    print("   • type: mining_job   - New real-mining task (Unity)")
    print()
    print("📤 POST /result Body (simulation):")
    print("   {")
    print('     "assignment_id": "asg_xxx",')
    print('     "job_id": "job_xxx",')
    print('     "device_id": "Unity1",')
    print('     "nonce": 12345,')
    print('     "hash": "0000abc...",')
    print('     "conf": 1.0')
    print("   }")
    print()
    print("📤 POST /device/register (Unity)")
    print("   returns wallet + pool config")
    print()
    print("📤 POST /mining/submit (Unity)")
    print("   submits shares to pool via Stratum")
    print()
    print("=" * 70)
    
    await site.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped")

