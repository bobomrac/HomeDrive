import os
import sys
import json
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

def is_first_run():
    """Check if this is the first run"""
    return not os.path.exists(CONFIG_FILE)

def create_storage_dir():
    """Create storage directory if it doesn't exist"""
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)
        print(f"✓ Created storage directory: {BASE_DIR}")

def save_config(password_hash, port=None):
    """Save configuration to file"""
    if port is None:
        port = int(os.environ.get('HOMEDRIVE_PORT', 8080))
    
    config = {
        "password_hash": password_hash,
        "port": port
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)
    os.chmod(CONFIG_FILE, 0o600)  # Restrict permissions

def load_config():
    """Load configuration from file"""
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def hash_password(password):
    """Hash a password"""
    return ph.hash(password)

def verify_password(password, password_hash):
    """Verify a password against its hash"""
    try:
        ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False
