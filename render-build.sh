#!/usr/bin/env bash
# Fail on error, but not on pipefail (curl pipes can flake)
set -eo pipefail

echo "=== Installing Python dependencies ==="
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "=== Installing Node.js 20 ==="
export NVM_DIR="$HOME/.nvm"
if [ ! -d "$NVM_DIR" ]; then
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash 2>/dev/null || {
        echo "NVM install failed — will use system Node if available"
    }
fi
if [ -s "$NVM_DIR/nvm.sh" ]; then
    \. "$NVM_DIR/nvm.sh"
    nvm install 20 --no-progress 2>/dev/null || true
    nvm use 20 2>/dev/null || true
fi
echo "Node: $(node --version 2>/dev/null || echo 'not found')"

echo "=== Installing WhatsApp bot dependencies ==="
if [ -f services/whatsapp/package.json ]; then
    cd services/whatsapp && npm install --no-fund --no-audit 2>/dev/null && cd ../.. || echo "WhatsApp bot deps skipped"
else
    echo "WhatsApp bot not present, skipping"
fi

echo "=== Build complete ==="
