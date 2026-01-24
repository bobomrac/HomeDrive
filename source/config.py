import os
import sys
import json
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher()

def get_executable_dir():
    """Get directory where executable/script is located"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

EXECUTABLE_DIR = get_executable_dir()
BASE_DIR = os.path.join(EXECUTABLE_DIR, "homedrive_storage")
CONFIG_FILE = os.path.join(EXECUTABLE_DIR, ".homedrive.conf")
FAVORITES_FILE = os.path.join(EXECUTABLE_DIR, ".homedrive.favorites.conf")

def is_first_run():
    """Check if this is the first run"""
    return not os.path.exists(CONFIG_FILE)

def create_storage_dir():
    """Create storage directory if it doesn't exist"""
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)
        print(f"✓ Created storage directory: {BASE_DIR}")

def save_config(password_hash, port=None, secret_key=None, system_commands=None, cert_path=None, key_path=None, polkit_configured=None):
    """Save configuration to file"""
    if port is None:
        port = int(os.environ.get('HOMEDRIVE_PORT', 8080))
    
    if secret_key is None:
        # Check if we already have a secret key
        existing_config = load_config()
        if existing_config and 'secret_key' in existing_config:
            secret_key = existing_config['secret_key']
        else:
            secret_key = secrets.token_hex(32)
    
    if system_commands is None:
        # Check if we already have system commands
        existing_config = load_config()
        if existing_config and 'system_commands' in existing_config:
            system_commands = existing_config['system_commands']
        else:
            system_commands = detect_system_commands()
    
    config = {
        "password_hash": password_hash,
        "port": port,
        "secret_key": secret_key,
        "system_commands": system_commands
    }
    
    # Add SSL cert paths if provided
    if cert_path and key_path:
        config["ssl_cert"] = cert_path
        config["ssl_key"] = key_path
    
    # Add polkit status if provided
    if polkit_configured is not None:
        config["polkit_configured"] = polkit_configured
    elif existing_config and 'polkit_configured' in existing_config:
        config["polkit_configured"] = existing_config['polkit_configured']
    
    # Write atomically by writing to temp file then moving
    temp_file = CONFIG_FILE + '.tmp'
    try:
        with open(temp_file, 'w') as f:
            json.dump(config, f, indent=2)
        os.chmod(temp_file, 0o600)  # Restrict permissions before moving
        
        # Atomic move (overwrites existing)
        if os.name == 'nt':  # Windows
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
        os.rename(temp_file, CONFIG_FILE)
    except Exception as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise e

def detect_system_commands():
    """Auto-detect system commands based on distro"""
    commands = {
        "reboot": "systemctl reboot",
        "shutdown": "systemctl poweroff"
    }
    
    # Detect update command based on package manager
    if os.path.exists("/usr/bin/rpm-ostree"):
        commands["update"] = "rpm-ostree upgrade"
    elif os.path.exists("/usr/bin/transactional-update"):
        commands["update"] = "transactional-update"
    elif os.path.exists("/usr/bin/abroot"):
        commands["update"] = "abroot upgrade"
    elif os.path.exists("/usr/bin/apt"):
        commands["update"] = "pkexec sh -c 'apt update && apt upgrade -y'"
    elif os.path.exists("/usr/bin/dnf"):
        commands["update"] = "pkexec dnf upgrade -y"
    elif os.path.exists("/usr/bin/pacman"):
        commands["update"] = "pkexec pacman -Syu --noconfirm"
    elif os.path.exists("/usr/bin/zypper"):
        commands["update"] = "pkexec zypper update -y"
    else:
        commands["update"] = "echo 'No package manager detected. Configure in settings.'"
    
    return commands

def load_config():
    """Load configuration from file with validation"""
    if not os.path.exists(CONFIG_FILE):
        return None
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        # Validate required fields
        required_fields = ['password_hash', 'port']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate types
        if not isinstance(config['port'], int):
            raise ValueError("Port must be an integer")
        if config['port'] < 1 or config['port'] > 65535:
            raise ValueError("Port must be between 1 and 65535")
        
        # Add secret_key if missing (for backward compatibility)
        if 'secret_key' not in config:
            config['secret_key'] = secrets.token_hex(32)
            save_config(config['password_hash'], config['port'], config['secret_key'])
        
        # Add system_commands if missing (for backward compatibility)
        if 'system_commands' not in config:
            config['system_commands'] = detect_system_commands()
            save_config(config['password_hash'], config['port'], config['secret_key'], config['system_commands'])
        
        return config
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid configuration file: {e}")
    except Exception as e:
        raise ValueError(f"Error loading configuration: {e}")

def get_secret_key():
    """Get or create secret key for Flask sessions"""
    config = load_config()
    if config and 'secret_key' in config:
        return config['secret_key']
    
    # First run or missing secret key
    secret_key = secrets.token_hex(32)
    return secret_key

def hash_password(password):
    """Hash a password using Argon2"""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    return ph.hash(password)

def verify_password(password, password_hash):
    """Verify a password against its hash"""
    try:
        ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False

def load_favorites():
    """Load favorited folder paths with validation"""
    if not os.path.exists(FAVORITES_FILE):
        return []

    try:
        with open(FAVORITES_FILE, 'r') as f:
            data = json.load(f)
            favorites = data.get('favorites', [])

        # Import is_safe_path from file_ops for validation
        try:
            from file_ops import is_safe_path

            # Validate paths still exist
            valid_favorites = []
            for path in favorites:
                if is_safe_path(path):
                    full_path = os.path.join(BASE_DIR, path)
                    if os.path.exists(full_path) and os.path.isdir(full_path):
                        valid_favorites.append(path)

            # Save cleaned list if any were removed
            if len(valid_favorites) != len(favorites):
                save_favorites(valid_favorites)

            return valid_favorites
        except ImportError:
            # If file_ops not available, return favorites without validation
            return favorites
    except:
        return []

def save_favorites(favorites_list):
    """Save favorites atomically (same pattern as main config)"""
    data = {"favorites": favorites_list}
    temp_file = FAVORITES_FILE + '.tmp'

    try:
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=2)
        os.chmod(temp_file, 0o600)
        os.rename(temp_file, FAVORITES_FILE)
    except Exception as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise e
