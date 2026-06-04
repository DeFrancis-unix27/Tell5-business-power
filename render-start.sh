#!/usr/bin/env bash
# Don't use set -e — bot failure should not crash the app

# Load nvm (installed by render-build.sh)
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

echo "Node version: $(node --version 2>/dev/null || echo 'not found')"

# Start FastAPI FIRST so Render detects the correct port
echo "Starting FastAPI..."
uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-8000} &
UVICORN_PID=$!

# Give uvicorn a moment to bind before starting the bot
sleep 2

# Start the Baileys WhatsApp bot in background
echo "Starting Baileys WhatsApp bot..."
nvm use 20 2>/dev/null || true
node services/whatsapp/index.js &
BOT_PID=$!
echo "Baileys bot started (PID: $BOT_PID)"

# Wait for uvicorn to keep the main process alive
wait $UVICORN_PID
