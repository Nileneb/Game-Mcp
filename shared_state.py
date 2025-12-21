"""
Shared State für beide MCP Server
==================================
Geteilter Zustand zwischen Job-Server und Device-Server
"""

import asyncio
import hashlib
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque

# ============================================================================
# BLOCKCHAIN
# ============================================================================

class Block:
    """Simulierter Block"""
    def __init__(self, index: int, previous_hash: str, difficulty: int):
        self.index = index
        self.timestamp = datetime.utcnow()
        self.previous_hash = previous_hash
        self.difficulty = difficulty
        self.nonce = None
        self.hash = None
        self.miner = None
        self.reward = 50.0 / (2 ** (index // 100))
        self.header = self._generate_header()
    
    def _generate_header(self) -> str:
        import random
        data = f"{self.index}:{self.previous_hash}:{self.timestamp.isoformat()}:{random.randint(0, 999999999)}"
        return hashlib.sha256(data.encode()).hexdigest()

class Blockchain:
    """Simulierte Blockchain"""
    def __init__(self):
        self.chain: List[Block] = []
        self.pending_block: Optional[Block] = None
        self.base_difficulty = 4
        self.target_block_time = 60
        self.last_block_times: List[float] = []
        
        # Genesis Block
        genesis = Block(0, "0" * 64, 1)
        genesis.nonce = 0
        genesis.hash = "0" * 64
        genesis.miner = "genesis"
        self.chain.append(genesis)
    
    def get_next_block(self) -> Block:
        """Erstellt nächsten Block zum Minen"""
        if self.pending_block is None:
            last_block = self.chain[-1]
            difficulty = self._calculate_difficulty()
            self.pending_block = Block(
                index=len(self.chain),
                previous_hash=last_block.hash,
                difficulty=difficulty
            )
        return self.pending_block
    
    def submit_solution(self, nonce: int, hash_result: str, miner: str) -> dict:
        """Prüft und akzeptiert Mining-Lösung"""
        if self.pending_block is None:
            return {"success": False, "error": "No pending block"}
        
        # Verifiziere Hash
        data = f"{self.pending_block.header}:{nonce}".encode()
        computed = hashlib.sha256(data).hexdigest()
        
        required_zeros = "0" * self.pending_block.difficulty
        if not computed.startswith(required_zeros):
            return {"success": False, "error": "Invalid hash"}
        
        # Block akzeptiert!
        self.pending_block.nonce = nonce
        self.pending_block.hash = computed
        self.pending_block.miner = miner
        
        reward = self.pending_block.reward
        block_index = self.pending_block.index
        
        self.chain.append(self.pending_block)
        self.last_block_times.append(time.time())
        self.pending_block = None
        
        return {
            "success": True,
            "block_index": block_index,
            "reward": reward,
            "hash": computed
        }
    
    def _calculate_difficulty(self) -> int:
        """Dynamische Difficulty"""
        if len(self.last_block_times) < 2:
            return self.base_difficulty
        
        recent = self.last_block_times[-10:]
        if len(recent) < 2:
            return self.base_difficulty
        
        avg_time = (recent[-1] - recent[0]) / (len(recent) - 1)
        
        if avg_time < self.target_block_time * 0.5:
            return min(self.base_difficulty + 1, 8)
        elif avg_time > self.target_block_time * 2:
            return max(self.base_difficulty - 1, 1)
        
        return self.base_difficulty

# ============================================================================
# ASSIGNMENTS & TASKS
# ============================================================================

class Assignment:
    """Ein Mining Task für ein Unity Device"""
    def __init__(self, job_id: str, assignment_id: str, task_data: dict):
        self.job_id = job_id
        self.assignment_id = assignment_id
        self.task_data = task_data
        self.status = "queued"  # queued|assigned|done|expired
        self.client_id: Optional[str] = None
        self.created_at = time.time()
        self.updated_at = time.time()
        self.deadline = 0.0

class Job:
    """Ein Mining Job (erstellt von AI Agent)"""
    def __init__(self, job_id: str, block: Block, num_tasks: int, chunk_size: int):
        self.job_id = job_id
        self.block_index = block.index
        self.block_header = block.header
        self.difficulty = block.difficulty
        self.reward = block.reward
        self.num_tasks = num_tasks
        self.chunk_size = chunk_size
        self.created_at = datetime.utcnow().isoformat()
        self.tasks_created = 0
        self.tasks_completed = 0
        self.status = "active"
        self.winner: Optional[str] = None
        self.winning_hash: Optional[str] = None
        self.winning_nonce: Optional[int] = None

# ============================================================================
# GLOBAL STATE
# ============================================================================

class SharedState:
    """Geteilter Zustand zwischen beiden Servern"""
    
    def __init__(self):
        self.blockchain = Blockchain()
        self.jobs: Dict[str, Job] = {}
        self.assignments: Dict[str, Assignment] = {}
        self.pending_queue: deque = deque()  # Assignment IDs
        self.device_queues: Dict[str, asyncio.Queue] = {}  # device_id -> Queue
        self.device_inflight: Dict[str, int] = {}  # device_id -> count
        self.leaderboard: Dict[str, dict] = {}  # device_id -> stats
        
        # Config
        self.assign_ttl = 120  # Sekunden
        self.max_inflight_per_device = 2
    
    def best_device_id(self) -> Optional[str]:
        """Findet Device mit wenigsten Tasks"""
        if not self.device_queues:
            return None
        return min(
            self.device_queues.keys(),
            key=lambda d: self.device_inflight.get(d, 0)
        )
    
    async def assign_to_device_or_pending(self, asg: Assignment):
        """Assignment an Device oder in Pending Queue"""
        device_id = self.best_device_id()
        
        if device_id is None or self.device_inflight.get(device_id, 0) >= self.max_inflight_per_device:
            self.pending_queue.append(asg.assignment_id)
            return
        
        await self.deliver(device_id, asg)
    
    async def deliver(self, device_id: str, asg: Assignment):
        """Assignment an Device pushen"""
        self.device_inflight[device_id] = self.device_inflight.get(device_id, 0) + 1
        asg.client_id = device_id
        asg.status = "assigned"
        asg.updated_at = time.time()
        asg.deadline = time.time() + self.assign_ttl
        
        await self.device_queues[device_id].put({
            "type": "assignment",
            "job_id": asg.job_id,
            "assignment_id": asg.assignment_id,
            **asg.task_data
        })
        
        # Watch für Expiry
        asyncio.create_task(self._watch_expiry(asg))
    
    async def drain_pending(self):
        """Pending Queue an freie Devices verteilen"""
        if not self.pending_queue:
            return
        
        remaining = deque()
        while self.pending_queue:
            asg_id = self.pending_queue.popleft()
            asg = self.assignments.get(asg_id)
            if not asg or asg.status != "queued":
                continue
            
            device_id = self.best_device_id()
            if device_id is None or self.device_inflight.get(device_id, 0) >= self.max_inflight_per_device:
                remaining.append(asg_id)
            else:
                await self.deliver(device_id, asg)
        
        self.pending_queue = remaining
    
    async def _watch_expiry(self, asg: Assignment):
        """Überwacht Assignment Timeout"""
        await asyncio.sleep(max(1, self.assign_ttl))
        
        if asg.status in ("done", "expired"):
            return
        
        asg.status = "expired"
        if asg.client_id:
            self.device_inflight[asg.client_id] = max(0, self.device_inflight.get(asg.client_id, 1) - 1)
        
        # Re-queue
        job = self.jobs.get(asg.job_id)
        if job and job.status == "active":
            new_asg = Assignment(
                job_id=asg.job_id,
                assignment_id=f"asg_{uuid.uuid4().hex[:8]}",
                task_data=asg.task_data
            )
            self.assignments[new_asg.assignment_id] = new_asg
            await self.assign_to_device_or_pending(new_asg)

# Singleton Instance
state = SharedState()
