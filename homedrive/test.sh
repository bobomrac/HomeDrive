#!/bin/bash

echo "======================================"
echo "Running HomeDrive in Development Mode"
echo "======================================"
echo ""

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt -q

echo ""
echo "Starting HomeDrive..."
echo "Press Ctrl+C to stop"
echo ""

python3 main.py
