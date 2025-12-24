"""
Redis-backed shared state helpers
=================================

Provides a single async Redis client and utility functions to coordinate
devices, task queues, inflight counters, and leaderboard across the
job server and device server processes.

Env vars:
- REDIS_HOST (default: localhost)
- REDIS_PORT (default: 6379)

ID sequencing:
- Uses Redis counters to generate numeric identifiers per entity type
  (job, asg, device). Provides mapping from external device_id to a
  stable numeric idx the first time a device connects.
"""

from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Optional, Tuple

from redis import asyncio as redis_async


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))


_redis: Optional[redis_async.Redis] = None


def get_redis() -> redis_async.Redis:
    global _redis
    if _redis is None:
        _redis = redis_async.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    return _redis


# =========================
# ID SEQUENCING / IDX
# =========================

async def next_seq(name: str) -> int:
    r = get_redis()
    return int(await r.incr(f"seq:{name}"))


async def ensure_device_idx(device_id: str) -> int:
    r = get_redis()
    idx = await r.hget("device:idx", device_id)
    if idx is not None:
        return int(idx)
    new_idx = await next_seq("device")
    await r.hset("device:idx", device_id, new_idx)
    await r.hset("device:id_by_idx", new_idx, device_id)
    return int(new_idx)


# =========================
# DEVICE PRESENCE / STATE
# =========================

async def register_device(device_id: str) -> int:
    r = get_redis()
    idx = await ensure_device_idx(device_id)
    await r.sadd("devices:connected", device_id)
    # Initialize inflight to 0 if missing
    await r.hsetnx("devices:inflight", device_id, 0)
    # Initialize basic stats hash if missing
    key = f"leaderboard:stats:{device_id}"
    pipe = r.pipeline()
    pipe.hsetnx(key, "coins", 0.0)
    pipe.hsetnx(key, "blocks_found", 0)
    pipe.hsetnx(key, "tasks_completed", 0)
    await pipe.execute()
    return idx


async def unregister_device(device_id: str) -> None:
    r = get_redis()
    await r.srem("devices:connected", device_id)
    await r.hdel("devices:inflight", device_id)


async def get_connected_devices() -> List[str]:
    r = get_redis()
    members = await r.smembers("devices:connected")
    return sorted(list(members))


async def get_inflight(device_id: str) -> int:
    r = get_redis()
    val = await r.hget("devices:inflight", device_id)
    return int(val) if val is not None else 0


async def get_all_inflight() -> Dict[str, int]:
    r = get_redis()
    data = await r.hgetall("devices:inflight")
    return {k: int(v) for k, v in data.items()}


async def incr_inflight(device_id: str) -> int:
    r = get_redis()
    return int(await r.hincrby("devices:inflight", device_id, 1))


async def decr_inflight(device_id: str) -> int:
    r = get_redis()
    # Ensure non-negative
    pipe = r.pipeline()
    pipe.hincrby("devices:inflight", device_id, -1)
    pipe.hget("devices:inflight", device_id)
    res = await pipe.execute()
    val = int(res[1]) if res[1] is not None else 0
    if val < 0:
        await r.hset("devices:inflight", device_id, 0)
        return 0
    return val


# =========================
# TASK QUEUES (PER DEVICE)
# =========================

def _task_queue_key(device_id: str) -> str:
    return f"tasks:{device_id}"


async def push_task(device_id: str, payload: Dict[str, Any]) -> None:
    r = get_redis()
    await r.rpush(_task_queue_key(device_id), json.dumps(payload))


async def blpop_task(device_id: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
    r = get_redis()
    res = await r.blpop(_task_queue_key(device_id), timeout=timeout)
    if not res:
        return None
    _, data = res
    try:
        return json.loads(data)
    except Exception:
        return None


# =========================
# LEADERBOARD
# =========================

LEADERBOARD_ZSET = "leaderboard:coins"


async def add_coins(device_id: str, coins: float) -> None:
    r = get_redis()
    pipe = r.pipeline()
    pipe.zincrby(LEADERBOARD_ZSET, coins, device_id)
    pipe.hincrbyfloat(f"leaderboard:stats:{device_id}", "coins", coins)
    await pipe.execute()


async def inc_blocks_found(device_id: str) -> None:
    r = get_redis()
    await r.hincrby(f"leaderboard:stats:{device_id}", "blocks_found", 1)


async def inc_tasks_completed(device_id: str) -> None:
    r = get_redis()
    await r.hincrby(f"leaderboard:stats:{device_id}", "tasks_completed", 1)


async def get_leaderboard(top_n: int = 10) -> List[Dict[str, Any]]:
    r = get_redis()
    # Highest scores first
    members = await r.zrevrange(LEADERBOARD_ZSET, 0, top_n - 1, withscores=True)
    results: List[Dict[str, Any]] = []
    rank = 1
    for device_id, score in members:
        stats = await r.hgetall(f"leaderboard:stats:{device_id}")
        results.append({
            "rank": rank,
            "device_id": device_id,
            "coins": float(stats.get("coins", score)),
            "blocks_found": int(stats.get("blocks_found", 0) or 0),
            "tasks_completed": int(stats.get("tasks_completed", 0) or 0),
        })
        rank += 1
    return results


async def get_device_stats(device_id: str) -> Dict[str, Any]:
    r = get_redis()
    stats = await r.hgetall(f"leaderboard:stats:{device_id}")
    return {
        "coins": float(stats.get("coins", 0) or 0),
        "blocks_found": int(stats.get("blocks_found", 0) or 0),
        "tasks_completed": int(stats.get("tasks_completed", 0) or 0),
    }

