import asyncio
import json
import aiohttp
from typing import Dict, Any

class N8NAgentConnector:
    """Connects MCP Server with n8n Agent workflows"""
    
    def __init__(self, n8n_webhook_url: str, mcp_server_url: str):
        self.n8n_webhook_url = n8n_webhook_url
        self.mcp_server_url = mcp_server_url
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def send_mining_result_to_agent(self, result: Dict[str, Any]):
        """Send mining results to n8n agent workflow"""
        payload = {
            "event_type": "mining_result",
            "data": result,
            "timestamp": result.get("timestamp")
        }
        
        async with self.session.post(
            self.n8n_webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        ) as response:
            return await response.json()
    
    async def request_agent_decision(self, context: Dict[str, Any]):
        """Request decision from agent for task distribution"""
        payload = {
            "event_type": "decision_request",
            "context": context,
            "request_type": "task_distribution"
        }
        
        async with self.session.post(
            f"{self.n8n_webhook_url}/decision",
            json=payload
        ) as response:
            return await response.json()
    
    async def notify_game_event(self, game_event: Dict[str, Any]):
        """Notify agent about game events that might trigger mining"""
        payload = {
            "event_type": "game_event",
            "game_data": game_event,
            "requires_mining": self.should_trigger_mining(game_event)
        }
        
        async with self.session.post(
            f"{self.n8n_webhook_url}/game-event",
            json=payload
        ) as response:
            return await response.json()
    
    def should_trigger_mining(self, game_event: Dict[str, Any]) -> bool:
        """Determine if game event should trigger mining task"""
        trigger_actions = [
            "boss_encounter", "treasure_found", "level_complete",
            "player_death", "special_ability_used"
        ]
        return game_event.get("action") in trigger_actions

# Usage example
async def main():
    async with N8NAgentConnector(
        n8n_webhook_url="http://localhost:5678/webhook/game-mining",
        mcp_server_url="http://localhost:8000"
    ) as connector:
        
        # Example: Send mining result to agent
        mining_result = {
            "task_id": "task_123",
            "status": "completed",
            "hash_found": "00000abc123...",
            "device_id": "iot_device_001",
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        await connector.send_mining_result_to_agent(mining_result)
        
        # Example: Request agent decision
        context = {
            "available_devices": 5,
            "pending_tasks": 3,
            "current_difficulty": 1000,
            "player_activity": "high"
        }
        
        decision = await connector.request_agent_decision(context)
        print(f"Agent decision: {decision}")

if __name__ == "__main__":
    asyncio.run(main())
