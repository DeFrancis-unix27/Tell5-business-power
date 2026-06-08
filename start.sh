#!/usr/bin/env bash
set -e

export BOT_PORT=${BOT_PORT:-3001}
export API_URL="http://localhost:${PORT:-8000}"

echo "Starting WhatsApp bot on port $BOT_PORT (API_URL=$API_URL)..."
node services/whatsapp/index.js &
BOT_PID=$!

echo "Starting web app on port ${PORT:-8000}..."
exec uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-8000}
