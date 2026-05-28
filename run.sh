#!/bin/bash
# Setup and run Tell5 locally

set -e

echo "=================================="
echo "Tell5 Setup & Run Script"
echo "=================================="

# Check Python
if ! command -v python &> /dev/null; then
    echo "Error: Python is not installed"
    exit 1
fi

echo "✓ Python found: $(python --version)"

# Check pip
if ! command -v pip &> /dev/null; then
    echo "Error: pip is not installed"
    exit 1
fi

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python -m venv venv
    echo "✓ Virtual environment created"
fi

# Activate venv
echo ""
echo "Activating virtual environment..."
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null
echo "✓ Virtual environment activated"

# Install/upgrade requirements
echo ""
echo "Installing dependencies..."
pip install -q -r requirements.txt
echo "✓ Dependencies installed"

# Check .env exists
echo ""
if [ ! -f ".env" ]; then
    echo "Creating .env from template..."
    cp .env.example .env
    echo "⚠ WARNING: Edit .env with your Twilio credentials!"
    echo ""
    echo "Steps:"
    echo "1. Go to https://console.twilio.com"
    echo "2. Find your Account SID and Auth Token"
    echo "3. Copy them to .env"
    echo "4. Run this script again"
    exit 0
else
    echo "✓ .env file exists"
fi

# Check database
echo ""
echo "Database Configuration:"
echo "  Current: $(grep DATABASE_URL .env | cut -d'=' -f2)"
echo "  Make sure PostgreSQL is running or change DATABASE_URL"

# Run app
echo ""
echo "=================================="
echo "Starting Tell5..."
echo "=================================="
echo ""
echo "Dashboard: http://localhost:8000/dashboard"
echo "API Docs: http://localhost:8000/docs"
echo "Press Ctrl+C to stop"
echo ""

uvicorn main:app --reload --host 0.0.0.0 --port 8000
