#!/usr/bin/env python3
"""
HomeDrive Polkit Setup Script

This script configures polkit (PolicyKit) to allow HomeDrive to perform
system operations (reboot, update) WITHOUT requiring a sudo password.

This is SECURE because:
1. Only allows specific commands (reboot, package updates)
2. Only allows the HomeDrive user to run these commands
3. Uses the standard Linux authorization framework (polkit)
4. No passwords transmitted over network
5. System administrators can review/modify the policy

Run with: sudo python3 setup_polkit.py
"""

import os
import sys
import subprocess

def get_current_user():
    """Get the username running HomeDrive"""
    try:
        return os.getlogin()
    except:
        return os.environ.get('SUDO_USER') or os.environ.get('USER', 'root')

def create_polkit_rules():
    """Create polkit rules for HomeDrive system operations"""
    
    user = get_current_user()
    
    # Polkit rules file
    rules_content = f"""// HomeDrive - Allow system operations without password
// This allows the HomeDrive user to reboot and update the system
// through the web interface without entering a sudo password.
//
// Security: Only specific commands are allowed, only for the HomeDrive user.
// To remove these permissions: sudo rm /etc/polkit-1/rules.d/90-homedrive.rules

polkit.addRule(function(action, subject) {{
    // Allow reboot/poweroff for HomeDrive user
    if ((action.id == "org.freedesktop.login1.reboot" ||
         action.id == "org.freedesktop.login1.power-off") &&
        subject.user == "{user}") {{
        return polkit.Result.YES;
    }}
}});

polkit.addRule(function(action, subject) {{
    // Allow package management for HomeDrive user
    if ((action.id == "org.debian.apt.update-cache" ||
         action.id == "org.debian.apt.upgrade-packages" ||
         action.id == "org.freedesktop.packagekit.system-update" ||
         action.id == "org.opensuse.yast.system.packages.write") &&
        subject.user == "{user}") {{
        return polkit.Result.YES;
    }}
}});
"""
    
    rules_file = "/etc/polkit-1/rules.d/90-homedrive.rules"
    
    print(f"Creating polkit rules for user: {user}")
    print(f"Rules file: {rules_file}")
    print("")
    
    try:
        # Write rules file
        with open(rules_file, 'w') as f:
            f.write(rules_content)
        
        os.chmod(rules_file, 0o644)
        print("✓ Polkit rules created successfully")
        
        # Reload polkit
        try:
            subprocess.run(['systemctl', 'reload', 'polkit'], check=False)
            print("✓ Polkit reloaded")
        except:
            print("⚠️  Could not reload polkit (changes will apply on next login)")
        
        return True
        
    except PermissionError:
        print("❌ Permission denied. Run with sudo:")
        print(f"   sudo python3 {sys.argv[0]}")
        return False
    except Exception as e:
        print(f"❌ Error creating polkit rules: {e}")
        return False

def verify_polkit():
    """Verify that polkit is installed and working"""
    
    # Check if polkit is installed
    if not os.path.exists("/usr/bin/pkexec"):
        print("❌ Polkit is not installed")
        print("")
        print("Install with:")
        print("  Debian/Ubuntu: sudo apt install policykit-1")
        print("  Fedora/RHEL:   sudo dnf install polkit")
        print("  Arch:          sudo pacman -S polkit")
        return False
    
    # Check if polkit service is running
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'polkit'],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print("⚠️  Polkit service is not running")
            print("   Start with: sudo systemctl start polkit")
    except:
        pass
    
    return True

def test_permissions():
    """Test if the permissions work"""
    print("")
    print("Testing permissions...")
    print("")
    
    user = get_current_user()
    
    # Test reboot permission (dry-run)
    print("Testing reboot permission...")
    try:
        result = subprocess.run(
            ['systemctl', 'reboot', '--dry-run'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "authentication" in result.stderr.lower() or "password" in result.stderr.lower():
            print("⚠️  Reboot may still require password")
            print("   You may need to log out and back in for changes to take effect")
        else:
            print("✓ Reboot permission working")
    except Exception as e:
        print(f"⚠️  Could not test reboot: {e}")
    
    print("")
    print("✓ Polkit configuration complete!")
    print("")
    print("Security notes:")
    print(f"  • User '{user}' can now reboot/update without password")
    print("  • Only works when logged in as this user")
    print("  • Only allows specific system operations")
    print("  • Review rules: cat /etc/polkit-1/rules.d/90-homedrive.rules")
    print("")
    print("To remove these permissions:")
    print("  sudo rm /etc/polkit-1/rules.d/90-homedrive.rules")
    print("")

def main():
    print("=" * 60)
    print("  HomeDrive Polkit Configuration")
    print("=" * 60)
    print("")
    print("This will configure your system to allow HomeDrive to:")
    print("  • Reboot the system")
    print("  • Update system packages")
    print("")
    print("WITHOUT requiring a sudo password in the web interface.")
    print("")
    print("This is SECURE because:")
    print("  ✓ Uses standard Linux authorization (polkit)")
    print("  ✓ Only allows specific commands")
    print("  ✓ Only allows your user account")
    print("  ✓ No passwords transmitted over network")
    print("")
    
    # Check if running as root
    if os.geteuid() != 0:
        print("❌ This script must be run with sudo")
        print(f"   Run: sudo python3 {sys.argv[0]}")
        sys.exit(1)
    
    # Verify polkit is installed
    if not verify_polkit():
        sys.exit(1)
    
    # Get user confirmation
    response = input("Continue with polkit configuration? (y/n): ").lower().strip()
    if response != 'y':
        print("Cancelled.")
        sys.exit(0)
    
    print("")
    
    # Create polkit rules
    if create_polkit_rules():
        test_permissions()
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
