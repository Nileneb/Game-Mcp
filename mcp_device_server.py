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
from datetime import datetime
from aiohttp import web
import aiohttp_cors

# Import shared state
from shared_state import state

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp-devices")

HOST = "0.0.0.0"
PORT = 8083

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
    
    # Device Queue erstellen
    q = asyncio.Queue()
    state.device_queues[device_id] = q
    state.device_inflight.setdefault(device_id, 0)
    
    # Leaderboard initialisieren
    if device_id not in state.leaderboard:
        state.leaderboard[device_id] = {
            "coins": 0.0,
            "blocks_found": 0,
            "tasks_completed": 0
        }
    
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
    
    # Pending Tasks verteilen
    await state.drain_pending()
    
    try:
        while True:
            # Warte auf Assignment oder Timeout
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
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
        state.device_queues.pop(device_id, None)
        state.device_inflight.pop(device_id, None)
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
        
        if not assignment_id or assignment_id not in state.assignments:
            return web.json_response({"ok": False, "error": "Invalid assignment"}, status=400)
        
        asg = state.assignments[assignment_id]
        job = state.jobs.get(job_id)
        
        if not job:
            return web.json_response({"ok": False, "error": "Job not found"}, status=400)
        
        # Assignment als done markieren
        asg.status = "done"
        asg.updated_at = time.time()
        
        # Inflight counter reduzieren
        if asg.client_id:
            state.device_inflight[asg.client_id] = max(0, state.device_inflight.get(asg.client_id, 1) - 1)
        
        # Job stats
        job.tasks_completed += 1
        
        # Leaderboard stats
        if device_id in state.leaderboard:
            state.leaderboard[device_id]["tasks_completed"] += 1
        
        # Prüfe ob gültiger Hash gefunden
        required_zeros = "0" * asg.task_data["difficulty"]
        
        if hash_result and hash_result.startswith(required_zeros):
            # WINNER!
            logger.info(f"🎉 POTENTIAL WINNER: {device_id} found hash!")
            
            result = state.blockchain.submit_solution(nonce, hash_result, device_id)
            
            if result["success"]:
                # Reward vergeben
                if device_id in state.leaderboard:
                    state.leaderboard[device_id]["coins"] += result["reward"]
                    state.leaderboard[device_id]["blocks_found"] += 1
                
                # Job als completed markieren
                job.status = "completed"
                job.winner = device_id
                job.winning_hash = hash_result
                job.winning_nonce = nonce
                
                # Alle pending tasks dieses Jobs canceln
                for asg_id, a in state.assignments.items():
                    if a.job_id == job_id and a.status in ("queued", "assigned"):
                        a.status = "cancelled"
                
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
# DEVICE API
# ============================================================================

async def handle_device_status(request):
    """GET /status?device_id=xxx"""
    device_id = request.query.get("device_id", "unknown")
    
    stats = state.leaderboard.get(device_id, {
        "coins": 0,
        "blocks_found": 0,
        "tasks_completed": 0
    })
    
    inflight = state.device_inflight.get(device_id, 0)
    connected = device_id in state.device_queues
    
    return web.json_response({
        "device_id": device_id,
        "connected": connected,
        "inflight_tasks": inflight,
        "stats": stats
    })

async def handle_health(request):
    """GET /health"""
    return web.json_response({
        "status": "healthy",
        "server": "MCP Device Server",
        "connected_devices": len(state.device_queues),
        "pending_tasks": len(state.pending_queue)
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
    
    # Result Submission
    app.router.add_post('/result', handle_submit_result)
    
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
    print("   • type: assignment   - New mining task")
    print()
    print("📤 POST /result Body:")
    print("   {")
    print('     "assignment_id": "asg_xxx",')
    print('     "job_id": "job_xxx",')
    print('     "device_id": "Unity1",')
    print('     "nonce": 12345,')
    print('     "hash": "0000abc...",')
    print('     "conf": 1.0')
    print("   }")
    print()
    print("=" * 70)
    
    await site.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
