import os
import sys
import subprocess
import getpass
from config import create_storage_dir, save_config, hash_password, EXECUTABLE_DIR, BASE_DIR

def get_network_ip():
    """Try to get local network IP"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "YOUR_IP"

def setup_wizard():
    """Run the setup wizard"""
    print("\n" + "=" * 60)
    print("           Welcome to HomeDrive Setup!")
    print("=" * 60)
    print("\nThis will:")
    print("  • Create storage directory")
    print("  • Set your access password")
    print("  • Install systemd service (requires sudo)")
    print("  • Configure automatic startup")
    print("\n")
    
    # Get password
    while True:
        password = getpass.getpass("Set your HomeDrive password: ")
        if len(password) < 4:
            print("❌ Password must be at least 4 characters")
            continue
        
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("❌ Passwords don't match")
            continue
        
        break
    
    # Hash and save password
    password_hash = hash_password(password)
    
    # Ask for port (optional)
    port_input = input("Port number (press Enter for default 8080): ").strip()
    port = 8080
    if port_input:
        try:
            port = int(port_input)
            if port < 1024 or port > 65535:
                print("⚠ Invalid port, using default 8080")
                port = 8080
        except ValueError:
            print("⚠ Invalid port, using default 8080")
    
    save_config(password_hash, port)
    print("✓ Password set")
    
    # Create storage directory
    create_storage_dir()
    
    # Ask about service installation
    print("\n" + "-" * 60)
    install_service = input("Install as system service? (y/n): ").lower().strip()
    
    if install_service == 'y':
        print("\nInstalling systemd service...")
        success = install_systemd_service()
        if success:
            print("✓ Service installed and started")
        else:
            print("❌ Service installation failed")
            print("   You can start HomeDrive manually with: ./homedrive")
            return False
    else:
        print("\n⚠ Skipping service installation")
        print("   Start HomeDrive manually with: ./homedrive")
        return False
    
    # Show completion message
    print("\n" + "=" * 60)
    print("                  Setup Complete!")
    print("=" * 60)
    
    network_ip = get_network_ip()
    print(f"\nHomeDrive is now running!")
    print(f"\n  Local access:  http://localhost:8080")
    print(f"  Network access: http://{network_ip}:8080")
    print(f"\n  Storage location: {BASE_DIR}")
    
    print("\nService management commands:")
    print("  • Stop:    sudo systemctl stop homedrive")
    print("  • Restart: sudo systemctl restart homedrive")
    print("  • Status:  sudo systemctl status homedrive")
    print("  • Disable: sudo systemctl disable homedrive")
    print("\n")
    
    return True

def install_systemd_service():
    """Install systemd service"""
    try:
        # Get current user
        current_user = os.getlogin()
    except:
        current_user = os.environ.get('USER', 'root')
    
    # Get executable path
    if getattr(sys, 'frozen', False):
        executable_path = sys.executable
    else:
        executable_path = os.path.abspath(__file__)
    
    # Check if HTTPS is configured
    cert_env = ""
    if os.environ.get('HOMEDRIVE_CERT') and os.environ.get('HOMEDRIVE_KEY'):
        cert_path = os.environ.get('HOMEDRIVE_CERT')
        key_path = os.environ.get('HOMEDRIVE_KEY')
        port = os.environ.get('HOMEDRIVE_PORT', '8080')
        cert_env = f"""Environment="HOMEDRIVE_CERT={cert_path}"
Environment="HOMEDRIVE_KEY={key_path}"
Environment="HOMEDRIVE_PORT={port}"
"""
    
    # Generate service file content
    service_content = f"""[Unit]
Description=HomeDrive - Personal Network File Storage
After=network.target

[Service]
Type=simple
User={current_user}
WorkingDirectory={EXECUTABLE_DIR}
ExecStart={executable_path}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
{cert_env}
[Install]
WantedBy=multi-user.target
"""
    
    # Write to temp file
    temp_service = "/tmp/homedrive.service"
    with open(temp_service, 'w') as f:
        f.write(service_content)
    
    print("   Installing service (requires sudo password)...")
    
    # Install service with sudo
    commands = [
        f"sudo cp {temp_service} /etc/systemd/system/homedrive.service",
        "sudo systemctl daemon-reload",
        "sudo systemctl enable homedrive",
        "sudo systemctl start homedrive"
    ]
    
    for cmd in commands:
        try:
            result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Command failed: {cmd}")
            print(f"   Error: {e.stderr}")
            return False
    
    # Clean up temp file
    try:
        os.remove(temp_service)
    except:
        pass
    
    return True

if __name__ == "__main__":
    setup_wizard()
