#!/usr/bin/env bash
set -e

export BOT_PORT=${BOT_PORT:-3001}
export API_URL="http://localhost:${PORT:-8000}"

cleanup() {
    echo "Shutting down..."
    kill $BOT_PID 2>/dev/null || true
    kill $WEB_PID 2>/dev/null || true
    wait 2>/dev/null
}
trap cleanup EXIT INT TERM

echo "Starting WhatsApp bot on port $BOT_PORT (API_URL=$API_URL)..."
node services/whatsapp/index.js &
BOT_PID=$!

# Wait briefly for the bot to start its HTTP server
sleep 2

echo "Starting web app on port ${PORT:-8000}..."
uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-8000} &
WEB_PID=$!

# Keep the web app running regardless of bot state.
# If the web app itself exits, shut down everything (Render will restart).
while true; do
    if ! kill -0 $WEB_PID 2>/dev/null; then
        echo "Web app exited. Shutting down."
        exit 0
    fi
    if ! kill -0 $BOT_PID 2>/dev/null; then
        echo "Bot exited. Restarting..."
        node services/whatsapp/index.js &
        BOT_PID=$!
    fi
    sleep 5
done
