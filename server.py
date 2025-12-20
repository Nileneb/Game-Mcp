import asyncio
import json
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import Dict, List

app = FastAPI(title="Game-Mining MCP HTTP Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory state
connected_clients: List[WebSocket] = []
mining_results: List[Dict] = []
devices: Dict[str, Dict] = {}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/sse-paperstream")
async def sse_paperstream(request: Request):
    async def event_generator():
        last_idx = 0
        while True:
            if await request.is_disconnected():
                break
            if last_idx < len(mining_results):
                for result in mining_results[last_idx:]:
                    yield f"event: result\ndata: {json.dumps(result)}\n\n"
                last_idx = len(mining_results)
            await asyncio.sleep(1)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/paper-result")
async def paper_result(result: Dict):
    mining_results.append(result)
    return {"status": "received", "result": result}

@app.post("/register-device")
async def register_device(device: Dict):
    device_id = device.get("device_id")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
    devices[device_id] = device
    return {"status": "registered", "device_id": device_id}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    logging.getLogger("uvicorn.error").propagate = True

    # Start Uvicorn server on port 8082
    uvicorn.run("server:app", host="0.0.0.0", port=8082, reload=False)
