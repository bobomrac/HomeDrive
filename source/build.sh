#!/bin/bash

set -e  # Exit on error

echo "======================================"
echo "   Building HomeDrive Executable"
echo "======================================"
echo ""

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1-2)
echo "Python version: $python_version"

# Check if running in virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Not in a virtual environment"
    echo "   Creating one for clean build..."
    
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    
    source venv/bin/activate
    echo "✓ Virtual environment activated"
fi

# Install build dependencies
echo ""
echo "Installing build dependencies..."
pip install --upgrade pip setuptools wheel

# Check if PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

# Install runtime dependencies
echo ""
echo "Installing runtime dependencies..."
pip install -r requirements.txt

# Clean previous builds
echo ""
echo "Cleaning previous builds..."
rm -rf build dist homedrive.spec.bak

# Build with PyInstaller
echo ""
echo "Building executable with PyInstaller..."
echo "(This may take a few minutes...)"
echo ""

pyinstaller homedrive.spec

# Check if build was successful
if [ ! -f "dist/homedrive" ]; then
    echo ""
    echo "✗ Build failed!"
    echo "  Check the output above for errors"
    exit 1
fi

# Create distribution package
echo ""
echo "Creating distribution package..."

DIST_DIR="dist/homedrive-package"
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

# Copy executable
cp dist/homedrive "$DIST_DIR/"

# Copy supporting files
cp README.md "$DIST_DIR/"
cp setup_polkit.py "$DIST_DIR/"
cp requirements.txt "$DIST_DIR/"

# Create installer script
cat > "$DIST_DIR/install.sh" << 'EOF'
#!/bin/bash

echo "======================================"
echo "   HomeDrive Installation"
echo "======================================"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "✗ Do not run this script as root"
    echo "  Run as your normal user: ./install.sh"
    exit 1
fi

# Detect installation directory
DEFAULT_INSTALL="/usr/local/bin"
echo "HomeDrive will be installed to: $DEFAULT_INSTALL"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

# Copy executable
echo ""
echo "Installing HomeDrive..."
sudo cp homedrive "$DEFAULT_INSTALL/"
sudo chmod +x "$DEFAULT_INSTALL/homedrive"

echo "✓ HomeDrive installed to $DEFAULT_INSTALL/homedrive"

# Check for dependencies
echo ""
echo "Checking dependencies..."

MISSING_DEPS=()

# Check OpenSSL
if ! command -v openssl &> /dev/null; then
    MISSING_DEPS+=("openssl")
fi

# Check polkit
if [ ! -f "/usr/bin/pkexec" ]; then
    MISSING_DEPS+=("policykit-1 (or polkit)")
fi

if [ ${#MISSING_DEPS[@]} -ne 0 ]; then
    echo ""
    echo "⚠️  Missing dependencies:"
    for dep in "${MISSING_DEPS[@]}"; do
        echo "   • $dep"
    done
    echo ""
    echo "Install with your package manager:"
    echo "  Debian/Ubuntu: sudo apt install openssl policykit-1"
    echo "  Fedora/RHEL:   sudo dnf install openssl polkit"
    echo "  Arch:          sudo pacman -S openssl polkit"
else
    echo "✓ All dependencies found"
fi

echo ""
echo "======================================"
echo "   Installation Complete!"
echo "======================================"
echo ""
echo "To start HomeDrive, run:"
echo "  homedrive"
echo ""
echo "First run will start the setup wizard."
echo ""
echo "For more information, see README.md"
echo ""
EOF

chmod +x "$DIST_DIR/install.sh"

# Create uninstaller
cat > "$DIST_DIR/uninstall.sh" << 'EOF'
#!/bin/bash

echo "======================================"
echo "   HomeDrive Uninstallation"
echo "======================================"
echo ""
echo "This will:"
echo "  • Stop HomeDrive service (if running)"
echo "  • Remove HomeDrive executable"
echo "  • Remove systemd service (if installed)"
echo "  • Remove polkit rules (if configured)"
echo ""
echo "⚠️  Your data will NOT be deleted"
echo "   (~/homedrive_storage and ~/.homedrive.conf)"
echo ""
read -p "Continue? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Uninstalling..."

# Stop service
if systemctl is-active --quiet homedrive 2>/dev/null; then
    echo "Stopping service..."
    sudo systemctl stop homedrive
    sudo systemctl disable homedrive
fi

# Remove service file
if [ -f "/etc/systemd/system/homedrive.service" ]; then
    echo "Removing service file..."
    sudo rm /etc/systemd/system/homedrive.service
    sudo systemctl daemon-reload
fi

# Remove executable
if [ -f "/usr/local/bin/homedrive" ]; then
    echo "Removing executable..."
    sudo rm /usr/local/bin/homedrive
fi

# Remove polkit rules
if [ -f "/etc/polkit-1/rules.d/90-homedrive.rules" ]; then
    echo "Removing polkit rules..."
    sudo rm /etc/polkit-1/rules.d/90-homedrive.rules
    sudo systemctl reload polkit 2>/dev/null || true
fi

echo ""
echo "✓ HomeDrive uninstalled"
echo ""
echo "Your data is still in:"
echo "  • ~/homedrive_storage (your files)"
echo "  • ~/.homedrive.conf (configuration)"
echo ""
echo "To remove data:"
echo "  rm -rf ~/homedrive_storage ~/.homedrive.conf"
echo ""
EOF

chmod +x "$DIST_DIR/uninstall.sh"

# Create tarball
echo ""
echo "Creating tarball..."
cd dist
tar -czf homedrive-linux-x64.tar.gz homedrive-package/
cd ..

# Get file size
SIZE=$(du -sh dist/homedrive-linux-x64.tar.gz | cut -f1)

echo ""
echo "======================================"
echo "   Build Successful!"
echo "======================================"
echo ""
echo "Executable:  dist/homedrive"
echo "Package:     dist/homedrive-linux-x64.tar.gz ($SIZE)"
echo ""
echo "Distribution package includes:"
echo "  ✓ homedrive          (executable)"
echo "  ✓ README.md          (documentation)"
echo "  ✓ install.sh         (installer)"
echo "  ✓ uninstall.sh       (uninstaller)"
echo "  ✓ setup_polkit.py    (polkit setup)"
echo "  ✓ requirements.txt   (for reference)"
echo ""
echo "To test locally:"
echo "  cd dist"
echo "  ./homedrive"
echo ""
echo "To install system-wide:"
echo "  cd dist/homedrive-package"
echo "  ./install.sh"
echo ""
echo "To distribute:"
echo "  Share dist/homedrive-linux-x64.tar.gz"
echo ""
