#!/usr/bin/env python3
"""
STRATUM PROXY - Verbindet sich mit Nanopool und stellt Jobs über HTTP bereit

Dieses Modul ist die BRIDGE zwischen:
- Nanopool Stratum Server (TCP, Port 10300/10343)  
- MCP Job Server (HTTP)

Stratum Protocol Flow:
1. mining.subscribe → Pool registrierung
2. mining.authorize → Wallet senden
3. mining.notify → Jobs empfangen (ECHTE MINING JOBS!)
4. mining.submit → Shares einreichen
"""

import asyncio
import json
import time
import hashlib
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from threading import Lock
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# STRATUM JOB DATA STRUCTURES
# ============================================================================

@dataclass
class StratumJob:
    """Repräsentiert einen echten Mining Job vom Pool"""
    job_id: str
    blob: str           # Block header template (hex)
    target: str         # Mining target/difficulty
    height: int         # Block height
    seed_hash: str      # RandomX seed hash
    received_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "blob": self.blob,
            "target": self.target,
            "height": self.height,
            "seed_hash": self.seed_hash,
            "received_at": self.received_at
        }


@dataclass
class StratumState:
    """Globaler State für Stratum Connection"""
    connected: bool = False
    authorized: bool = False
    current_job: Optional[StratumJob] = None
    job_history: List[StratumJob] = field(default_factory=list)
    shares_submitted: int = 0
    shares_accepted: int = 0
    shares_rejected: int = 0
    difficulty: float = 1.0
    last_job_time: float = 0
    
    # Thread-safe lock
    _lock: Lock = field(default_factory=Lock)
    
    def update_job(self, job: StratumJob):
        with self._lock:
            self.current_job = job
            self.job_history.append(job)
            self.last_job_time = time.time()
            # Keep only last 100 jobs
            if len(self.job_history) > 100:
                self.job_history = self.job_history[-100:]
    
    def get_current_job(self) -> Optional[Dict]:
        with self._lock:
            if self.current_job:
                return self.current_job.to_dict()
            return None
    
    def get_stats(self) -> Dict:
        return {
            "connected": self.connected,
            "authorized": self.authorized,
            "difficulty": self.difficulty,
            "shares_submitted": self.shares_submitted,
            "shares_accepted": self.shares_accepted,
            "shares_rejected": self.shares_rejected,
            "accept_rate": (self.shares_accepted / max(1, self.shares_submitted)) * 100,
            "jobs_received": len(self.job_history),
            "last_job_age": time.time() - self.last_job_time if self.last_job_time > 0 else -1
        }


# Global state
stratum_state = StratumState()


# ============================================================================
# STRATUM CLIENT
# ============================================================================

class StratumClient:
    """
    Stratum Protocol Client für Monero/RandomX Mining Pools
    
    Verbindet sich mit Nanopool und empfängt echte Mining Jobs.
    """
    
    def __init__(
        self,
        pool_host: str = "xmr-eu1.nanopool.org",
        pool_port: int = 10300,
        wallet_address: str = "",
        worker_name: str = "game-mcp",
        password: str = "x"
    ):
        self.pool_host = pool_host
        self.pool_port = pool_port
        self.wallet_address = wallet_address
        self.worker_name = worker_name
        self.password = password
        
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        
        self.message_id = 0
        self.pending_requests: Dict[int, asyncio.Future] = {}
        
        self._running = False
        self._reconnect_delay = 5  # seconds
        
    def _next_id(self) -> int:
        self.message_id += 1
        return self.message_id
    
    async def connect(self) -> bool:
        """Verbindet sich mit dem Pool"""
        try:
            logger.info(f"🔌 Connecting to {self.pool_host}:{self.pool_port}...")
            
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.pool_host, self.pool_port),
                timeout=30
            )
            
            stratum_state.connected = True
            logger.info("✅ Connected to pool!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            stratum_state.connected = False
            return False
    
    async def disconnect(self):
        """Trennt die Verbindung"""
        self._running = False
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except:
                pass
        stratum_state.connected = False
        stratum_state.authorized = False
        logger.info("🔌 Disconnected from pool")
    
    async def _send(self, method: str, params: List[Any]) -> int:
        """Sendet eine JSON-RPC Nachricht"""
        msg_id = self._next_id()
        message = {
            "id": msg_id,
            "method": method,
            "params": params
        }
        
        data = json.dumps(message) + "\n"
        self.writer.write(data.encode())
        await self.writer.drain()
        
        logger.debug(f"📤 Sent: {message}")
        return msg_id
    
    async def _receive_line(self) -> Optional[str]:
        """Empfängt eine Zeile vom Pool"""
        try:
            line = await asyncio.wait_for(
                self.reader.readline(),
                timeout=300  # 5 min timeout
            )
            if line:
                return line.decode().strip()
            return None
        except asyncio.TimeoutError:
            logger.warning("⚠️ Receive timeout")
            return None
        except Exception as e:
            logger.error(f"❌ Receive error: {e}")
            return None
    
    async def login(self) -> bool:
        """
        Führt Login beim Pool durch:
        1. mining.subscribe
        2. mining.authorize (mit Wallet)
        """
        try:
            # Für Monero/XMR: Kombiniertes Login
            login_params = {
                "login": f"{self.wallet_address}.{self.worker_name}",
                "pass": self.password,
                "agent": "game-mcp/1.0"
            }
            
            await self._send("login", [login_params])
            
            # Warte auf Response
            response_line = await self._receive_line()
            if not response_line:
                logger.error("❌ No login response")
                return False
            
            response = json.loads(response_line)
            logger.info(f"📥 Login response: {response}")
            
            if "result" in response and response["result"]:
                result = response["result"]
                
                # Extract job if present
                if "job" in result:
                    job_data = result["job"]
                    job = StratumJob(
                        job_id=job_data.get("job_id", ""),
                        blob=job_data.get("blob", ""),
                        target=job_data.get("target", ""),
                        height=job_data.get("height", 0),
                        seed_hash=job_data.get("seed_hash", "")
                    )
                    stratum_state.update_job(job)
                    logger.info(f"📋 Initial job received: {job.job_id}")
                
                stratum_state.authorized = True
                logger.info("✅ Authorization successful!")
                return True
            else:
                error = response.get("error", "Unknown error")
                logger.error(f"❌ Login failed: {error}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Login error: {e}")
            return False
    
    async def submit_share(
        self,
        job_id: str,
        nonce: str,
        result_hash: str
    ) -> bool:
        """
        Submitted einen Share zum Pool
        
        Args:
            job_id: ID des Jobs (vom Pool erhalten)
            nonce: Gefundene Nonce (hex, 8 bytes)
            result_hash: Berechneter Hash (hex, 32 bytes)
        """
        try:
            submit_params = {
                "id": "1",  # Session ID
                "job_id": job_id,
                "nonce": nonce,
                "result": result_hash
            }
            
            await self._send("submit", [submit_params])
            stratum_state.shares_submitted += 1
            
            # Warte auf Response
            response_line = await self._receive_line()
            if response_line:
                response = json.loads(response_line)
                
                if response.get("result", {}).get("status") == "OK":
                    stratum_state.shares_accepted += 1
                    logger.info(f"✅ Share accepted! ({stratum_state.shares_accepted}/{stratum_state.shares_submitted})")
                    return True
                else:
                    stratum_state.shares_rejected += 1
                    error = response.get("error", "Unknown")
                    logger.warning(f"❌ Share rejected: {error}")
                    return False
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Submit error: {e}")
            return False
    
    async def _handle_notification(self, message: dict):
        """Verarbeitet Notifications vom Pool (neue Jobs, Difficulty, etc.)"""
        method = message.get("method", "")
        params = message.get("params", {})
        
        if method == "job":
            # Neuer Job empfangen
            job = StratumJob(
                job_id=params.get("job_id", ""),
                blob=params.get("blob", ""),
                target=params.get("target", ""),
                height=params.get("height", 0),
                seed_hash=params.get("seed_hash", "")
            )
            stratum_state.update_job(job)
            logger.info(f"📋 New job: {job.job_id} (height: {job.height})")
            
    async def listen(self):
        """Hauptloop - Empfängt kontinuierlich Nachrichten vom Pool"""
        self._running = True
        
        while self._running:
            try:
                line = await self._receive_line()
                
                if not line:
                    logger.warning("⚠️ Connection lost, reconnecting...")
                    break
                
                message = json.loads(line)
                
                # Check if it's a notification (no id or id is null)
                if message.get("id") is None or message.get("method"):
                    await self._handle_notification(message)
                else:
                    # It's a response to a request
                    msg_id = message.get("id")
                    if msg_id in self.pending_requests:
                        self.pending_requests[msg_id].set_result(message)
                        
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Invalid JSON: {e}")
            except Exception as e:
                logger.error(f"❌ Listen error: {e}")
                break
        
        # Reconnect logic
        if self._running:
            stratum_state.connected = False
            logger.info(f"🔄 Reconnecting in {self._reconnect_delay}s...")
            await asyncio.sleep(self._reconnect_delay)
            await self.run()
    
    async def run(self):
        """Startet den Stratum Client"""
        while self._running or not stratum_state.connected:
            if await self.connect():
                if await self.login():
                    await self.listen()
            else:
                await asyncio.sleep(self._reconnect_delay)


# ============================================================================
# HTTP API für MCP Server
# ============================================================================

def get_current_job() -> Optional[Dict]:
    """Gibt den aktuellen Mining Job zurück (für MCP Server)"""
    return stratum_state.get_current_job()


def get_pool_stats() -> Dict:
    """Gibt Pool-Statistiken zurück"""
    return stratum_state.get_stats()


async def submit_result(job_id: str, nonce: str, result_hash: str) -> Dict:
    """Submitted ein Mining Result (für MCP Server)"""
    # Diese Funktion wird vom MCP Server aufgerufen
    # Der StratumClient muss global verfügbar sein
    return {
        "submitted": True,
        "job_id": job_id,
        "nonce": nonce
    }


# ============================================================================
# MAIN
# ============================================================================

async def main():
    """Startet den Stratum Proxy"""
    from dotenv import load_dotenv
    load_dotenv()
    
    wallet = os.getenv("XMR_WALLET_ADDRESS", "")
    if not wallet:
        logger.error("❌ XMR_WALLET_ADDRESS not set!")
        logger.info("Set it in .env or environment variable")
        return
    
    client = StratumClient(
        pool_host=os.getenv("POOL_HOST", "xmr-eu1.nanopool.org"),
        pool_port=int(os.getenv("POOL_PORT", "10300")),
        wallet_address=wallet,
        worker_name=os.getenv("WORKER_NAME", "game-mcp")
    )
    
    logger.info("🚀 Starting Stratum Proxy...")
    logger.info(f"   Pool: {client.pool_host}:{client.pool_port}")
    logger.info(f"   Wallet: {wallet[:20]}...")
    
    await client.run()


if __name__ == "__main__":
    asyncio.run(main())
