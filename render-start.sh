#!/usr/bin/env bash
set -euo pipefail

# Start the Baileys WhatsApp bot in background
echo "Starting Baileys WhatsApp bot..."
node services/whatsapp/index.js &
BOT_PID=$!
echo "Baileys bot started (PID: $BOT_PID)"

# Start the FastAPI application
echo "Starting FastAPI..."
exec uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-8000}
