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

# Lade Umgebungsvariablen aus .env
if [ -f ".env" ]; then
    set -a
    source <(grep -v '^#' .env | grep -v '^$')
    set +a
    echo "✅ Environment variables loaded from .env"
else
    echo "⚠️  Warning: .env file not found, using defaults"
fi

# Basic validation
if [ -z "$FASTMCP_HOST" ] || [ -z "$FASTMCP_PORT" ]; then
    echo "ℹ️ FASTMCP_HOST/FASTMCP_PORT not set, using defaults (0.0.0.0:8082)"
    export FASTMCP_HOST="${FASTMCP_HOST:-0.0.0.0}"
    export FASTMCP_PORT="${FASTMCP_PORT:-8082}"
fi

if [ "${REAL_MINING_ENABLED}" = "1" ]; then
    if [ -z "${XMR_WALLET_ADDRESS}" ]; then
        echo "❌ REAL_MINING_ENABLED=1 but XMR_WALLET_ADDRESS not set. Disable or set wallet in .env."
        exit 1
    fi
    echo "💰 Real mining enabled. Wallet: ${XMR_WALLET_ADDRESS:0:30}..."
    echo "🏊 Pool: ${POOL_HOST:-xmr-eu1.nanopool.org}:${POOL_PORT:-10300} as ${WORKER_NAME:-game-mcp}"
fi

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
echo "📋 Job Server (n8n):      PID $JOB_PID  → http://${FASTMCP_HOST}:${FASTMCP_PORT}"
echo "🎮 Device Server (Unity): PID $DEVICE_PID → http://${DEVICE_SERVER_HOST:-0.0.0.0}:${DEVICE_SERVER_PORT:-8083}"
echo ""
echo "Press Ctrl+C to stop all servers..."
echo ""

# Warte auf SIGINT
trap "kill $JOB_PID $DEVICE_PID 2>/dev/null; echo '\n👋 Servers stopped'; exit" SIGINT SIGTERM

wait
