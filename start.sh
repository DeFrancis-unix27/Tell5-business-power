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

# Wait for either process to exit, then shut down the other
wait -n $BOT_PID $WEB_PID
echo "A process exited. Shutting down..."
kill $BOT_PID 2>/dev/null || true
kill $WEB_PID 2>/dev/null || true
wait 2>/dev/null
exit 0
