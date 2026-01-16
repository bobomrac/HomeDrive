#!/bin/bash

echo "======================================"
echo "Building HomeDrive Executable"
echo "======================================"
echo ""

# Check if PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "PyInstaller not found. Installing..."
    pip install pyinstaller --break-system-packages
fi

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt --break-system-packages

# Build with PyInstaller
echo ""
echo "Building executable..."
pyinstaller homedrive.spec

# Check if build was successful
if [ -f "dist/homedrive" ]; then
    echo ""
    echo "======================================"
    echo "Build successful!"
    echo "======================================"
    echo ""
    echo "Executable location: dist/homedrive"
    echo ""
    echo "To install and run:"
    echo "  1. Copy dist/homedrive to your desired location"
    echo "  2. Make it executable: chmod +x homedrive"
    echo "  3. Run it: ./homedrive"
    echo ""
else
    echo ""
    echo "Build failed! Check the output above for errors."
    exit 1
fi
