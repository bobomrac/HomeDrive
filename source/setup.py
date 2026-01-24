import os
import sys
import subprocess
import getpass
import logging
import socket
from config import create_storage_dir, save_config, hash_password, EXECUTABLE_DIR, BASE_DIR, load_config

logger = logging.getLogger(__name__)

def get_network_ip():
    """Try to get local network IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "YOUR_IP"

def check_sudo_available():
    """Check if sudo is available and user can use it"""
    try:
        result = subprocess.run(
            ['sudo', '-n', 'true'],
            capture_output=True,
            timeout=1
        )
        return result.returncode == 0
    except:
        return False

def setup_polkit():
    """Setup polkit rules for passwordless system operations"""
    print("\n" + "=" * 60)
    print("  Setting up System Operations")
    print("=" * 60)
    print("\nThis allows HomeDrive to:")
    print("  • Reboot/shutdown the system")
    print("  • Update system packages")
    print("\nFrom the web interface without passwords.")
    print()
    
    # Check if polkit is installed
    if not os.path.exists("/usr/bin/pkexec"):
        print("⚠️  Polkit not found")
        print("\nWithout Polkit:")
        print("  • System operations will not be available")
        print("  • You won't be able to reboot/update from web interface")
        print("\nYou can install Polkit from your package manager")
        print("and run setup again to enable system operations.")
        print()
        skip = input("Continue without system operations? (y/n): ").lower().strip()
        if skip == 'y':
            return False
        else:
            print("\nPlease install Polkit and run setup again.")
            sys.exit(0)
    
    # Get current user
    try:
        current_user = os.getlogin()
    except:
        current_user = os.environ.get('SUDO_USER') or os.environ.get('USER', 'root')
    
    print("Configuring Polkit for passwordless system operations...")
    print()
    
    # Create polkit rules
    rules_content = f"""// HomeDrive - Allow system operations without password
polkit.addRule(function(action, subject) {{
    if ((action.id == "org.freedesktop.login1.reboot" ||
         action.id == "org.freedesktop.login1.power-off") &&
        subject.user == "{current_user}") {{
        return polkit.Result.YES;
    }}
}});

polkit.addRule(function(action, subject) {{
    if ((action.id == "org.debian.apt.update-cache" ||
         action.id == "org.debian.apt.upgrade-packages" ||
         action.id == "org.freedesktop.packagekit.system-update") &&
        subject.user == "{current_user}") {{
        return polkit.Result.YES;
    }}
}});
"""
    
    rules_file = "/etc/polkit-1/rules.d/90-homedrive.rules"
    temp_file = "/tmp/90-homedrive.rules"
    
    try:
        with open(temp_file, 'w') as f:
            f.write(rules_content)
        
        print("Installing polkit rules (will ask for sudo password)...")
        subprocess.run(
            f"sudo cp {temp_file} {rules_file} && sudo chmod 644 {rules_file}",
            shell=True,
            check=True
        )
        
        subprocess.run(['sudo', 'systemctl', 'reload', 'polkit'], check=False)
        os.remove(temp_file)
        
        print("✓ Polkit configured")
        print("  System operations will work without passwords")
        return True
        
    except subprocess.CalledProcessError:
        print("✗ Failed to configure polkit")
        print("\nWithout Polkit configuration:")
        print("  • System operations will not be available")
        print()
        skip = input("Continue without system operations? (y/n): ").lower().strip()
        if skip == 'y':
            return False
        else:
            print("\nPlease check permissions and run setup again.")
            sys.exit(0)
    except Exception as e:
        print(f"✗ Error: {e}")
        skip = input("Continue without system operations? (y/n): ").lower().strip()
        return skip == 'y'

def generate_ssl_certificate():
    """Generate self-signed SSL certificate"""
    print("\n" + "=" * 60)
    print("  Setting up HTTPS (SSL Certificate)")
    print("=" * 60)
    print("\nThis encrypts all traffic between your device and HomeDrive.")
    print()
    print("Options:")
    print("  1. Generate self-signed certificate (LAN only)")
    print("     • Works immediately")
    print("     • Browser will show 'not secure' warning (safe to ignore)")
    print("     • Free")
    print()
    print("  2. Use Let's Encrypt (Internet access required)")
    print("     • Requires domain name")
    print("     • No browser warnings")
    print("     • Free")
    print()
    print("  3. Skip HTTPS (NOT recommended)")
    print("     • Traffic is unencrypted")
    print("     • Passwords visible on network")
    print()
    
    choice = input("Choose option (1/2/3): ").strip()
    
    if choice == '1':
        return generate_self_signed_cert()
    elif choice == '2':
        return setup_letsencrypt()
    elif choice == '3':
        print("\n⚠️  WARNING: Running without HTTPS is insecure!")
        print("   Anyone on your network can see your password and files.")
        confirm = input("\nAre you sure? (type 'yes' to confirm): ").lower().strip()
        if confirm == 'yes':
            return None, None, 8080
        else:
            print("\nReturning to HTTPS setup...")
            return generate_ssl_certificate()
    else:
        print("Invalid choice, generating self-signed certificate...")
        return generate_self_signed_cert()

def generate_self_signed_cert():
    """Generate self-signed SSL certificate"""
    cert_dir = os.path.join(EXECUTABLE_DIR, "certs")
    os.makedirs(cert_dir, exist_ok=True)
    
    cert_path = os.path.join(cert_dir, "cert.pem")
    key_path = os.path.join(cert_dir, "key.pem")
    
    print("\nGenerating self-signed SSL certificate...")
    
    # Check if openssl is available
    try:
        subprocess.run(['openssl', 'version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("\n⚠️  OpenSSL not found")
        print("\nWithout OpenSSL:")
        print("  • HTTPS will not be available")
        print("  • Traffic will be unencrypted")
        print("  • Passwords will be visible on your network")
        print("\nYou can install OpenSSL from your package manager")
        print("and run setup again to enable HTTPS.")
        print()
        skip = input("Continue without HTTPS? (y/n): ").lower().strip()
        if skip == 'y':
            return None, None, 8080
        else:
            print("\nPlease install OpenSSL and run setup again.")
            sys.exit(0)
    
    try:
        # Get hostname
        hostname = socket.gethostname()
        
        # Generate certificate
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', key_path,
            '-out', cert_path,
            '-days', '365',
            '-subj', f'/CN={hostname}'
        ], check=True, capture_output=True)
        
        print("✓ SSL certificate generated")
        print(f"  Certificate: {cert_path}")
        print(f"  Private Key: {key_path}")
        
        return cert_path, key_path, 443
        
    except Exception as e:
        print(f"✗ Failed to generate certificate: {e}")
        print("  Continuing without HTTPS...")
        return None, None, 8080

def setup_letsencrypt():
    """Setup Let's Encrypt certificate"""
    print("\nLet's Encrypt Setup")
    print("=" * 60)
    print("\nRequirements:")
    print("  • Domain name pointing to this server")
    print("  • Port 80 must be open to the internet")
    print()
    
    domain = input("Domain name (e.g., homedrive.example.com): ").strip()
    email = input("Email for renewal notifications: ").strip()
    
    if not domain or not email:
        print("✗ Domain and email are required")
        print("  Falling back to self-signed certificate...")
        return generate_self_signed_cert()
    
    # Check if certbot is installed
    try:
        subprocess.run(['certbot', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("\n✗ Certbot is not installed")
        print("\nTo install certbot:")
        print("  Debian/Ubuntu: sudo apt install certbot")
        print("  Fedora/RHEL:   sudo dnf install certbot")
        print("  Arch:          sudo pacman -S certbot")
        print("\n  Falling back to self-signed certificate...")
        return generate_self_signed_cert()
    
    print("\nObtaining certificate from Let's Encrypt...")
    print("(This will ask for your sudo password)")
    
    try:
        subprocess.run([
            'sudo', 'certbot', 'certonly', '--standalone',
            '-d', domain,
            '--email', email,
            '--agree-tos',
            '--non-interactive'
        ], check=True)
        
        cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        key_path = f"/etc/letsencrypt/live/{domain}/privkey.pem"
        
        print("✓ Let's Encrypt certificate obtained!")
        print(f"  Certificate: {cert_path}")
        print(f"  Private Key: {key_path}")
        print("\n  Auto-renewal is configured via certbot timer")
        
        return cert_path, key_path, 443
        
    except subprocess.CalledProcessError as e:
        print(f"\n✗ Failed to obtain certificate")
        print("  Please check:")
        print("    • Domain DNS is pointing to this server")
        print("    • Port 80 is open and accessible")
        print("    • No other service is using port 80")
        print("\n  Falling back to self-signed certificate...")
        return generate_self_signed_cert()

def install_systemd_service(cert_path=None, key_path=None, port=8080):
    """Install systemd service"""
    print("\n" + "=" * 60)
    print("  Installing System Service")
    print("=" * 60)
    print("\nThis will:")
    print("  • Start HomeDrive automatically on boot")
    print("  • Run HomeDrive in the background")
    print("  • Restart automatically if it crashes")
    print()
    
    # Get current user
    try:
        current_user = os.getlogin()
    except:
        current_user = os.environ.get('USER', 'root')
    
    # Get executable path
    if getattr(sys, 'frozen', False):
        executable_path = sys.executable
    else:
        executable_path = os.path.join(EXECUTABLE_DIR, 'main.py')
        # Make sure we're using python3
        executable_path = f"python3 {executable_path}"
    
    # Environment variables for SSL
    cert_env = ""
    if cert_path and key_path:
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
Restart=on-failure
RestartSec=10
TimeoutStartSec=30
TimeoutStopSec=10
StandardOutput=journal
StandardError=journal

# Security hardening
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={BASE_DIR}
ReadWritePaths={EXECUTABLE_DIR}
NoNewPrivileges=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictSUIDSGID=true
{cert_env}
[Install]
WantedBy=multi-user.target
"""
    
    # Write to temp file
    temp_service = "/tmp/homedrive.service"
    try:
        with open(temp_service, 'w') as f:
            f.write(service_content)
    except Exception as e:
        print(f"✗ Failed to create service file: {e}")
        return False
    
    print("Installing service (requires sudo password)...")
    
    # Install service with sudo
    commands = [
        f"sudo cp {temp_service} /etc/systemd/system/homedrive.service",
        "sudo systemctl daemon-reload",
        "sudo systemctl enable homedrive",
        "sudo systemctl start homedrive"
    ]
    
    for cmd in commands:
        try:
            subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"\n✗ Command failed: {cmd}")
            print(f"   Error: {e.stderr}")
            os.remove(temp_service)
            return False
    
    # Clean up
    try:
        os.remove(temp_service)
    except:
        pass
    
    print("✓ Service installed and started")
    return True

def setup_wizard():
    """Run the complete setup wizard"""
    print("\n" + "=" * 60)
    print("        🏠 Welcome to HomeDrive Setup!")
    print("=" * 60)
    print("\nHomeDrive is your personal network storage solution.")
    print("This wizard will set up everything you need.")
    print()
    
    # Step 1: Password
    print("Step 1: Set Your Password")
    print("-" * 60)
    while True:
        password = getpass.getpass("Choose a password (min 8 characters): ")
        if len(password) < 8:
            print("✗ Password must be at least 8 characters")
            print("  Tip: Use a passphrase like 'correct-horse-battery-staple'")
            continue
        
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("✗ Passwords don't match")
            continue
        
        break
    
    try:
        password_hash = hash_password(password)
    except ValueError as e:
        print(f"✗ {e}")
        return False
    
    print("✓ Password set")
    
    # Step 2: SSL Certificate
    cert_path, key_path, default_port = generate_ssl_certificate()
    
    # Step 3: Port selection
    print("\n" + "-" * 60)
    print("Step 2: Choose Port")
    print("-" * 60)
    
    if cert_path:
        # SSL was configured, suggest HTTPS port
        default_port = 8443
        print(f"SSL configured - recommended port is 8443 for HTTPS")
        print(f"(Port 443 requires sudo, 8443 does not)")
    else:
        default_port = 8080
        print(f"No SSL - recommended port is 8080 for HTTP")
    
    port_input = input(f"Port number (press Enter for {default_port}): ").strip()
    port = default_port
    if port_input:
        try:
            port = int(port_input)
            if port < 1 or port > 65535:
                print("⚠️  Invalid port, using default")
                port = default_port
            elif port < 1024:
                print(f"⚠️  Warning: Port {port} requires sudo to run")
                print("    Run with: sudo ./homedrive")
            elif cert_path and port == 8080:
                print(f"⚠️  Warning: Using HTTP port 8080 with SSL configured")
                print("    HTTPS won't work on standard ports")
        except ValueError:
            print("⚠️  Invalid port, using default")
    
    print(f"✓ Using port {port}")
    
    # Save configuration
    try:
        save_config(password_hash, port, cert_path=cert_path, key_path=key_path)
        create_storage_dir()
        print("✓ Configuration saved")
    except Exception as e:
        print(f"✗ Failed to save configuration: {e}")
        return False
    
    # Step 4: Polkit (optional)
    print("\n" + "-" * 60)
    print("Step 3: System Permissions (Optional)")
    print("-" * 60)
    print("Would you like to enable system operations?")
    print("  • Reboot/shutdown from web interface")
    print("  • Update system packages")
    print()
    setup_polkit_choice = input("Enable system operations? (y/n): ").lower().strip()
    
    polkit_configured = False
    if setup_polkit_choice == 'y':
        polkit_configured = setup_polkit()
    else:
        print("⚠️  Skipping system operations setup")
        print("   You can enable this later by running: sudo python3 setup_polkit.py")
    
    # Update config with polkit status
    try:
        cfg = load_config()
        save_config(
            cfg['password_hash'],
            cfg['port'],
            cfg['secret_key'],
            cfg['system_commands'],
            cfg.get('ssl_cert'),
            cfg.get('ssl_key'),
            polkit_configured
        )
    except Exception as e:
        logger.warning(f"Could not update polkit status in config: {e}")
    
    # Step 5: System service
    print("\n" + "-" * 60)
    print("Step 4: Install as System Service")
    print("-" * 60)
    install_service = input("Install as system service? (y/n): ").lower().strip()
    
    service_installed = False
    if install_service == 'y':
        service_installed = install_systemd_service(cert_path, key_path, port)
        if not service_installed:
            print("✗ Service installation failed")
            print("  You can start HomeDrive manually")
    else:
        print("⚠️  Skipping service installation")
        print("   Start HomeDrive manually with: ./homedrive")
    
    # Final summary
    print("\n" + "=" * 60)
    print("        ✓ Setup Complete!")
    print("=" * 60)
    
    network_ip = get_network_ip()
    protocol = "https" if cert_path else "http"
    
    if service_installed:
        print(f"\nHomeDrive is now running!")
    else:
        print(f"\nTo start HomeDrive, run: ./homedrive")
    
    print(f"\n  Local access:   {protocol}://localhost:{port}")
    print(f"  Network access: {protocol}://{network_ip}:{port}")
    
    if cert_path and "letsencrypt" not in cert_path:
        print(f"\n  ⚠️  Using self-signed certificate")
        print(f"     Your browser will show a security warning")
        print(f"     This is safe to ignore on your local network")
    
    if port < 1024:
        print(f"\n  ⚠️  Port {port} requires sudo")
        print(f"     Run with: sudo ./homedrive")
    
    print(f"\n  Storage location: {BASE_DIR}")
    print(f"  Config: {os.path.join(EXECUTABLE_DIR, '.homedrive.conf')}")
    
    if service_installed:
        print("\nService management:")
        print("  • Stop:    sudo systemctl stop homedrive")
        print("  • Restart: sudo systemctl restart homedrive")
        print("  • Status:  sudo systemctl status homedrive")
        print("  • Logs:    sudo journalctl -u homedrive -f")
    
    if polkit_configured:
        print("\n✓ System operations enabled")
    else:
        print("\n  System operations: Not configured")
        print("  Run later: sudo python3 setup_polkit.py")
    
    print("\nSecurity tips:")
    print("  • Keep your password secure")
    print("  • Only access from trusted networks")
    print("  • Monitor logs for suspicious activity")
    print()
    
    return service_installed

if __name__ == "__main__":
    success = setup_wizard()
    sys.exit(0 if success else 1)
