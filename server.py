#!/usr/bin/env python3
"""
Enhanced Game-MCP Server für Mining
Kombiniert IoT-Device Management, Mining-Koordination und Game-State Management
"""

import asyncio
import json
import logging
import hashlib
import time
import random
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import sqlite3
from contextlib import asynccontextmanager

# MCP Protocol imports
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)
from pydantic import BaseModel, Field

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data Models
@dataclass
class IoTDevice:
    device_id: str
    capabilities: Dict[str, Any]  # CPU, RAM, network_speed, etc.
    status: str  # 'idle', 'busy', 'offline'
    last_seen: datetime
    current_task: Optional[str] = None
    performance_score: float = 1.0

@dataclass
class MiningTask:
    task_id: str
    algorithm: str  # 'sha256', 'scrypt', etc.
    difficulty: int
    target_hash: str
    nonce_range_start: int
    nonce_range_end: int
    assigned_device: Optional[str] = None
    status: str = 'pending'  # 'pending', 'assigned', 'completed', 'failed'
    created_at: datetime = None
    game_context: Optional[Dict] = None  # Link to game state
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

@dataclass
class GameState:
    player_id: str
    position: Dict[str, float]  # x, y coordinates
    actions: List[str]  # recent player actions
    score: int
    level: int
    mining_contributions: int = 0
    current_dungeon: Optional[str] = None

class GameMiningServer:
    """Enhanced MCP Server for Game-Mining coordination"""
    
    def __init__(self):
        self.devices: Dict[str, IoTDevice] = {}
        self.mining_tasks: Dict[str, MiningTask] = {}
        self.game_states: Dict[str, GameState] = {}
        self.active_connections: Dict[str, Any] = {}
        
        # Initialize MCP Server
        self.server = Server("game-mining-mcp")
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup MCP protocol handlers"""
        
        # Resource handlers
        @self.server.list_resources()
        async def list_resources() -> List[Resource]:
            """List available resources"""
            return [
                Resource(
                    uri="game://devices",
                    name="IoT Devices",
                    description="Connected IoT devices and their status",
                    mimeType="application/json"
                ),
                Resource(
                    uri="game://mining-tasks",
                    name="Mining Tasks",
                    description="Active and completed mining tasks",
                    mimeType="application/json"
                ),
                Resource(
                    uri="game://game-states",
                    name="Game States",
                    description="Current player game states",
                    mimeType="application/json"
                )
            ]
        
        @self.server.read_resource()
        async def read_resource(uri: str) -> str:
            """Read resource content"""
            if uri == "game://devices":
                return json.dumps({"devices": [asdict(device) for device in self.devices.values()]}, default=str)
            elif uri == "game://mining-tasks":
                return json.dumps({"tasks": [asdict(task) for task in self.mining_tasks.values()]}, default=str)
            elif uri == "game://game-states":
                return json.dumps({"states": [asdict(state) for state in self.game_states.values()]}, default=str)
            else:
                raise ValueError(f"Unknown resource: {uri}")
        
        # Tool handlers
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """List available tools"""
            return [
                Tool(
                    name="register_device",
                    description="Register a new IoT device",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "device_id": {"type": "string"},
                            "capabilities": {"type": "object"},
                        },
                        "required": ["device_id", "capabilities"]
                    }
                ),
                Tool(
                    name="create_mining_task",
                    description="Create a new mining task from game context",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "player_id": {"type": "string"},
                            "game_action": {"type": "string"},
                            "difficulty": {"type": "integer"},
                        },
                        "required": ["player_id", "game_action"]
                    }
                ),
                Tool(
                    name="update_game_state",
                    description="Update player game state",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "player_id": {"type": "string"},
                            "position": {"type": "object"},
                            "action": {"type": "string"},
                        },
                        "required": ["player_id", "action"]
                    }
                ),
                Tool(
                    name="assign_mining_task",
                    description="Assign mining task to best available device",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                        },
                        "required": ["task_id"]
                    }
                ),
                Tool(
                    name="translate_game_to_mining",
                    description="Convert game actions to mining parameters",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "player_actions": {"type": "array"},
                            "game_context": {"type": "object"},
                        },
                        "required": ["player_actions"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[TextContent]:
            """Handle tool calls"""
            
            if name == "register_device":
                result = await self.register_device(
                    arguments["device_id"], 
                    arguments["capabilities"]
                )
                return [TextContent(type="text", text=json.dumps(result))]
            
            elif name == "create_mining_task":
                result = await self.create_mining_task_from_game(
                    arguments["player_id"],
                    arguments["game_action"],
                    arguments.get("difficulty", 1)
                )
                return [TextContent(type="text", text=json.dumps(result))]
            
            elif name == "update_game_state":
                result = await self.update_game_state(
                    arguments["player_id"],
                    arguments.get("position", {}),
                    arguments["action"]
                )
                return [TextContent(type="text", text=json.dumps(result))]
            
            elif name == "assign_mining_task":
                result = await self.assign_mining_task(arguments["task_id"])
                return [TextContent(type="text", text=json.dumps(result))]
            
            elif name == "translate_game_to_mining":
                result = await self.translate_game_to_mining(
                    arguments["player_actions"],
                    arguments.get("game_context", {})
                )
                return [TextContent(type="text", text=json.dumps(result))]
            
            else:
                raise ValueError(f"Unknown tool: {name}")
    
    # Core Business Logic
    async def register_device(self, device_id: str, capabilities: Dict) -> Dict:
        """Register new IoT device"""
        device = IoTDevice(
            device_id=device_id,
            capabilities=capabilities,
            status="idle",
            last_seen=datetime.now()
        )
        self.devices[device_id] = device
        
        logger.info(f"Registered device: {device_id} with capabilities: {capabilities}")
        return {"status": "success", "device_id": device_id, "message": "Device registered"}
    
    async def create_mining_task_from_game(self, player_id: str, game_action: str, difficulty: int = 1) -> Dict:
        """Create mining task based on game action"""
        
        # Generate task parameters from game context
        task_id = f"task_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # Map game action to mining parameters
        mining_params = self.game_action_to_mining_params(game_action, difficulty)
        
        task = MiningTask(
            task_id=task_id,
            algorithm=mining_params["algorithm"],
            difficulty=mining_params["difficulty"],
            target_hash=mining_params["target_hash"],
            nonce_range_start=mining_params["nonce_start"],
            nonce_range_end=mining_params["nonce_end"],
            game_context={"player_id": player_id, "action": game_action}
        )
        
        self.mining_tasks[task_id] = task
        
        logger.info(f"Created mining task {task_id} for player {player_id} action: {game_action}")
        return {"status": "success", "task_id": task_id, "mining_params": mining_params}
    
    def game_action_to_mining_params(self, action: str, difficulty: int) -> Dict:
        """Convert game action to mining parameters"""
        
        # Base parameters
        base_difficulty = 1000 * difficulty
        
        # Action-specific modifications
        action_modifiers = {
            "move_up": {"nonce_modifier": 0x1000, "algo": "sha256"},
            "move_down": {"nonce_modifier": 0x2000, "algo": "sha256"},
            "move_left": {"nonce_modifier": 0x3000, "algo": "sha256"},
            "move_right": {"nonce_modifier": 0x4000, "algo": "sha256"},
            "attack": {"nonce_modifier": 0x5000, "algo": "sha256"},
            "collect_item": {"nonce_modifier": 0x6000, "algo": "sha256"},
        }
        
        modifier = action_modifiers.get(action, {"nonce_modifier": 0x1000, "algo": "sha256"})
        
        # Generate target hash (simplified)
        target_data = f"{action}_{difficulty}_{int(time.time())}"
        target_hash = hashlib.sha256(target_data.encode()).hexdigest()
        
        return {
            "algorithm": modifier["algo"],
            "difficulty": base_difficulty,
            "target_hash": target_hash[:16] + "0" * 48,  # Simplified target
            "nonce_start": modifier["nonce_modifier"],
            "nonce_end": modifier["nonce_modifier"] + 100000
        }
    
    async def update_game_state(self, player_id: str, position: Dict, action: str) -> Dict:
        """Update player game state"""
        
        if player_id not in self.game_states:
            self.game_states[player_id] = GameState(
                player_id=player_id,
                position=position,
                actions=[],
                score=0,
                level=1
            )
        
        state = self.game_states[player_id]
        state.position.update(position)
        state.actions.append(action)
        
        # Keep only last 10 actions
        if len(state.actions) > 10:
            state.actions = state.actions[-10:]
        
        logger.info(f"Updated game state for player {player_id}: {action}")
        return {"status": "success", "player_id": player_id, "current_state": asdict(state)}
    
    async def assign_mining_task(self, task_id: str) -> Dict:
        """Assign mining task to best available device"""
        
        if task_id not in self.mining_tasks:
            return {"status": "error", "message": "Task not found"}
        
        task = self.mining_tasks[task_id]
        
        # Find best available device
        available_devices = [
            device for device in self.devices.values() 
            if device.status == "idle"
        ]
        
        if not available_devices:
            return {"status": "error", "message": "No available devices"}
        
        # Select device with highest performance score
        best_device = max(available_devices, key=lambda d: d.performance_score)
        
        # Assign task
        task.assigned_device = best_device.device_id
        task.status = "assigned"
        best_device.status = "busy"
        best_device.current_task = task_id
        
        logger.info(f"Assigned task {task_id} to device {best_device.device_id}")
        return {
            "status": "success", 
            "task_id": task_id, 
            "assigned_device": best_device.device_id
        }
    
    async def translate_game_to_mining(self, player_actions: List[str], game_context: Dict) -> Dict:
        """Translate game actions to mining parameters"""
        
        # Combine multiple actions into mining strategy
        action_sequence = "_".join(player_actions[-5:])  # Last 5 actions
        
        # Generate mining parameters based on action sequence
        sequence_hash = hashlib.md5(action_sequence.encode()).hexdigest()
        
        # Use hash to determine mining parameters
        nonce_base = int(sequence_hash[:8], 16)
        difficulty_modifier = len(set(player_actions)) * 100  # Unique actions increase difficulty
        
        mining_strategy = {
            "recommended_algorithm": "sha256",
            "nonce_range_start": nonce_base,
            "nonce_range_end": nonce_base + 50000,
            "difficulty_modifier": difficulty_modifier,
            "action_sequence": action_sequence,
            "optimization_hint": self.get_optimization_hint(player_actions)
        }
        
        return {"status": "success", "mining_strategy": mining_strategy}
    
    def get_optimization_hint(self, actions: List[str]) -> str:
        """Provide optimization hints based on action patterns"""
        
        if not actions:
            return "random_search"
        
        # Analyze action patterns
        action_counts = {}
        for action in actions:
            action_counts[action] = action_counts.get(action, 0) + 1
        
        most_common = max(action_counts, key=action_counts.get)
        
        hints = {
            "move_up": "linear_increment",
            "move_down": "linear_decrement", 
            "move_left": "bit_shift_left",
            "move_right": "bit_shift_right",
            "attack": "aggressive_search",
            "collect_item": "targeted_search"
        }
        
        return hints.get(most_common, "balanced_search")

# Main execution
async def main():
    """Main entry point"""
    game_mining_server = GameMiningServer()
    
    # Run MCP server
    async with stdio_server() as (read_stream, write_stream):
        await game_mining_server.server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="game-mining-mcp",
                server_version="1.0.0",
                capabilities=game_mining_server.server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities=None,
                )
            )
        )

if __name__ == "__main__":
    import os
    mode = os.environ.get("MCP_MODE", "http").lower()
    if mode == "stdio":
        asyncio.run(main())
    else:
        # HTTP-Modus für Docker/Produktivbetrieb
        game_mining_server = GameMiningServer()
        host = os.environ.get("FASTMCP_HOST", "0.0.0.0")
        port = int(os.environ.get("FASTMCP_PORT", "8082"))
        import uvicorn
        uvicorn.run(game_mining_server.server.app, host=host, port=port)