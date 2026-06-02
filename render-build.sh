#!/usr/bin/env bash
set -euo pipefail

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Node.js and build WhatsApp bot
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
cd services/whatsapp && npm install && cd ../..
