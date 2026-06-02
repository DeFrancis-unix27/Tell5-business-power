#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Installing Node.js 20 ==="
# Install Node.js without root (works on Render Python runtime, no apt-get needed)
export NVM_DIR="$HOME/.nvm"
if [ ! -d "$NVM_DIR" ]; then
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
fi
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
nvm install 20
nvm use 20
node --version

echo "=== Installing WhatsApp bot dependencies ==="
cd services/whatsapp && npm install && cd ../..

echo "=== Build complete ==="
