from __future__ import annotations
import os
import time
import json
import hmac
import hashlib
import asyncio
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import PlainTextResponse, StreamingResponse, JSONResponse

load_dotenv()

mcp = FastMCP(
    name="paperstream",
    instructions="Paperstream MCP over HTTP. SSE assignments + REST results.",
    version="1.0.0",
)

# =========================
# Config / ENV
# =========================
HOST = os.getenv("FASTMCP_HOST", "0.0.0.0")
PORT = int(os.getenv("FASTMCP_PORT", "8082"))
SSE_PATH = os.getenv("SSE_PATH", "/sse-paperstream")
RESULT_PATH = os.getenv("RESULT_PATH", "/paper-result")
HEALTH_PATH = os.getenv("HEALTH_PATH", "/health")
HMAC_SECRET = os.getenv("PAPERSTREAM_HMAC", "")  # optional
ASSIGN_TTL = int(os.getenv("ASSIGN_TTL", "120"))  # seconds
MAX_INFLIGHT_PER_CLIENT = int(os.getenv("MAX_INFLIGHT_PER_CLIENT", "2"))

# =========================
# State (in-memory)
# =========================
class Assignment(BaseModel):
    job_id: str
    assignment_id: str
    item: Dict[str, Any]
    status: str = "queued"   # queued|assigned|done|expired
    client_id: str | None = None
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())
    deadline: float = 0.0

class Job(BaseModel):
    job_id: str
    items: List[Dict[str, Any]]
    k: int = 2
    assignments: List[Assignment] = Field(default_factory=list)
    closed: bool = False
    created_at: float = Field(default_factory=lambda: time.time())

clients_queues: Dict[str, asyncio.Queue] = {}
clients_inflight: Dict[str, int] = {}
jobs: Dict[str, Job] = {}
pending_assignments: List[Assignment] = []  # wartet auf freie/verbundene Clients

# =========================
# Helpers
# =========================
def _now_ms() -> int:
    return int(time.time() * 1000)

def _hmac(payload: str) -> str:
    if not HMAC_SECRET:
        return ""
    return hmac.new(HMAC_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()

def _best_client_id() -> str | None:
    if not clients_queues:
        return None
    return min(clients_queues.keys(), key=lambda c: clients_inflight.get(c, 0))

async def _assign_to_client_or_pending(asg: Assignment):
    cid = _best_client_id()
    if cid is None or clients_inflight.get(cid, 0) >= MAX_INFLIGHT_PER_CLIENT:
        pending_assignments.append(asg)
        return
    await _deliver(cid, asg)

async def _deliver(client_id: str, asg: Assignment):
    clients_inflight[client_id] = clients_inflight.get(client_id, 0) + 1
    asg.client_id = client_id
    asg.status = "assigned"
    asg.updated_at = time.time()
    asg.deadline = time.time() + ASSIGN_TTL
    await clients_queues[client_id].put({
        "type": "assignment",
        "job_id": asg.job_id,
        "assignment_id": asg.assignment_id,
        "item": asg.item,
        "ttl_s": ASSIGN_TTL,
        "sig": _hmac(asg.assignment_id),
    })
    asyncio.create_task(_watch_expiry(asg))

async def _drain_pending():
    if not pending_assignments:
        return
    remaining: List[Assignment] = []
    for asg in pending_assignments:
        cid = _best_client_id()
        if cid is None or clients_inflight.get(cid, 0) >= MAX_INFLIGHT_PER_CLIENT:
            remaining.append(asg)
        else:
            await _deliver(cid, asg)
    pending_assignments.clear()
    pending_assignments.extend(remaining)

async def _watch_expiry(asg: Assignment):
    await asyncio.sleep(max(1, ASSIGN_TTL))
    if asg.status in ("done", "expired"):
        return
    asg.status = "expired"
    if asg.client_id:
        clients_inflight[asg.client_id] = max(0, clients_inflight.get(asg.client_id, 1) - 1)
    job = jobs.get(asg.job_id)
    if job and not job.closed:
        new_asg = Assignment(job_id=asg.job_id, assignment_id=f"a_{_now_ms()}", item=asg.item)
        job.assignments.append(new_asg)
        await _assign_to_client_or_pending(new_asg)

# =========================
# MCP Tools (ohne 'parameters' im Decorator; n8n-kompatible Signaturen)
# =========================
@mcp.tool(tags={"public"})
async def paperstream_enqueue(items: list, k: float = 2) -> dict:
    """
    Enqueue papers for distribution to SSE clients.
    items: list of {"paper_url": str, "question": str}
    k: number of replicas per item (will be coerced to int >=1)
    returns: { job_id, k, items, assignments }
    """
    try:
        k_int = int(k or 2)
    except Exception:
        k_int = 2
    if k_int < 1:
        k_int = 1

    job_id = f"j_{_now_ms()}"
    # input sanitisieren
    safe_items: list[dict] = []
    for it in (items or []):
        if isinstance(it, dict) and it.get("paper_url") and it.get("question"):
            safe_items.append({"paper_url": str(it["paper_url"]), "question": str(it["question"])} )

    job = Job(job_id=job_id, items=safe_items, k=k_int)
    jobs[job_id] = job

    for it in safe_items:
        for i in range(job.k):
            aid = f"a_{_now_ms()}_{i}"
            asg = Assignment(job_id=job_id, assignment_id=aid, item=it)
            job.assignments.append(asg)
            await _assign_to_client_or_pending(asg)

    return {
        "job_id": job_id,
        "k": job.k,
        "items": len(safe_items),
        "assignments": len(job.assignments),
    }

@mcp.tool(tags={"public"})
async def paperstream_enqueue_json(items_json: str, k: float = 2) -> dict:
    try:
        payload = json.loads(items_json or "[]")
        assert isinstance(payload, list)
    except Exception:
        return {"error":"items_json must be a JSON array of {paper_url,question}"}
    return await paperstream_enqueue(payload, k)


# =========================
# HTTP Routes (SSE + Result)
# =========================
@mcp.custom_route(HEALTH_PATH, methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")

@mcp.custom_route(SSE_PATH, methods=["GET"])
async def sse(request: Request) -> StreamingResponse:
    """
    Unity/Edge Clients verbinden sich hier per SSE und erhalten Assignments.
    """
    client_id = request.query_params.get("client_id", f"client_{_now_ms()}")
    q: asyncio.Queue = asyncio.Queue()
    clients_queues[client_id] = q
    clients_inflight.setdefault(client_id, 0)

    async def gen():
        yield f"data: {json.dumps({'type':'hello','client_id':client_id})}\n\n"
        await _drain_pending()
        try:
            while True:
                msg = await q.get()
                yield f"data: {json.dumps(msg)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            clients_queues.pop(client_id, None)
            clients_inflight.pop(client_id, None)

    return StreamingResponse(gen(), media_type="text/event-stream")

@mcp.custom_route(RESULT_PATH, methods=["POST"])
async def receive_result(request: Request) -> JSONResponse:
    body = await request.json()
    assignment_id = body.get("assignment_id")
    job_id = body.get("job_id")
    result = body.get("result")
    conf = body.get("conf", 0)
    device = body.get("device_id", "unknown")
    sig = body.get("sig", "")

    try:
        conf = float(conf)
    except Exception:
        conf = 0.0

    if HMAC_SECRET:
        expect = _hmac(assignment_id or "")
        if sig != expect:
            return JSONResponse({"ok": False, "error": "invalid signature"}, status_code=401)
    if not assignment_id or not job_id or job_id not in jobs:
        return JSONResponse({"ok": False, "error": "bad ids"}, status_code=400)

    job = jobs[job_id]
    for a in job.assignments:
        if a.assignment_id == assignment_id:
            a.status = "done"
            a.updated_at = time.time()
            if a.client_id:
                clients_inflight[a.client_id] = max(0, clients_inflight.get(a.client_id, 1) - 1)
            # votes sammeln
            if "votes" not in a.item:
                a.item["votes"] = []
            a.item["votes"].append({"result": result, "conf": conf, "device": device})

    finished = 0
    for it in job.items:
        if len(it.get("votes", [])) >= job.k:
            finished += 1
    if finished == len(job.items):
        job.closed = True

    return JSONResponse({"ok": True, "job_closed": job.closed})

# =========================
# Main – identisch zu deiner server.py
# =========================
if __name__ == "__main__":
    transport = os.getenv("FASTMCP_TRANSPORT", "http").lower()  # 'http' oder 'stdio'
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        host = os.getenv("FASTMCP_HOST", "0.0.0.0")
        port = int(os.getenv("FASTMCP_PORT", str(PORT)))
        mcp.run(transport="http", host=host, port=port)
