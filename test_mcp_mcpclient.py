#!/usr/bin/env python3
"""
Testskript für MCP-Server: Tools und Ressourcen via MCP-Protokoll (HTTP)
"""
import asyncio
import json

# Use fastmcp for HTTP-based MCP client
from fastmcp.client.client import Client
from fastmcp.client.transports import StreamableHttpTransport

MCP_URL = "http://localhost:8082"  # oder Container-Host


async def main():
    transport = StreamableHttpTransport(MCP_URL)
    client = Client(transport)

    print("== Ressourcen auflisten ==")
    resources = await client.list_resources()
    print(json.dumps(resources, indent=2))

    print("== Tools auflisten ==")
    tools = await client.list_tools()
    print(json.dumps(tools, indent=2))

    print("== Device registrieren ==")
    reg_result = await client.call_tool("register_device", {
        "device_id": "iot_test_001",
        "capabilities": {"cpu": 1, "ram": 512}
    })
    print(json.dumps(reg_result, indent=2))

    print("== Mining-Task anlegen ==")
    task_result = await client.call_tool("create_mining_task", {
        "player_id": "player1",
        "game_action": "boss_encounter",
        "difficulty": 1000
    })
    print(json.dumps(task_result, indent=2))

    print("== Game-State updaten ==")
    state_result = await client.call_tool("update_game_state", {
        "player_id": "player1",
        "position": {"x": 1, "y": 2},
        "action": "move"
    })
    print(json.dumps(state_result, indent=2))

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
