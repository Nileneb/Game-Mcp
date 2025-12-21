#!/bin/bash
# Startet beide MCP Server parallel

echo "🚀 Starting MCP Mining System..."
echo ""

# Farben
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Virtuelle Umgebung (venv) erstellen/aktivieren
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "🛠 Creating virtualenv in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Dependencies installieren (mit venv's pip)
echo "${BLUE}📦 Installing dependencies into venv...${NC}"
python -m pip install --upgrade pip >/dev/null
python -m pip install -q -r requirements.txt

echo ""
echo "${GREEN}🚀 Starting servers...${NC}"
echo ""

# Server 1: Job Server (n8n)
python3 mcp_job_server.py &
JOB_PID=$!

sleep 2

# Server 2: Device Server (Unity)
python3 mcp_device_server.py &
DEVICE_PID=$!

echo ""
echo "${GREEN}✅ Both servers running!${NC}"
echo ""
echo "📋 Job Server (n8n):      PID $JOB_PID  → http://192.168.178.12:8082"
echo "🎮 Device Server (Unity): PID $DEVICE_PID → http://192.168.178.12:8083"
echo ""
echo "Press Ctrl+C to stop all servers..."
echo ""

# Warte auf SIGINT
trap "kill $JOB_PID $DEVICE_PID 2>/dev/null; echo '\n👋 Servers stopped'; exit" SIGINT SIGTERM

wait
