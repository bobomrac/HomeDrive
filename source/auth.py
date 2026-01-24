from functools import wraps
from flask import session, redirect, url_for, request
import time
import threading
import logging

logger = logging.getLogger(__name__)

# Login attempt tracking with thread safety
login_attempts = {}
login_attempts_lock = threading.Lock()
MAX_ATTEMPTS = 5
LOCKOUT_TIME = 300  # 5 minutes

def cleanup_old_attempts():
    """Remove old login attempts to prevent memory leak"""
    current_time = time.time()
    with login_attempts_lock:
        to_delete = [
            ip for ip, (attempts, last_time) in login_attempts.items()
            if current_time - last_time > LOCKOUT_TIME * 2
        ]
        for ip in to_delete:
            del login_attempts[ip]
        if to_delete:
            logger.info(f"Cleaned up {len(to_delete)} old login attempt records")

def check_login_attempts(ip):
    """Check if IP is locked out"""
    cleanup_old_attempts()  # Clean up on every check
    
    with login_attempts_lock:
        if ip in login_attempts:
            attempts, last_attempt = login_attempts[ip]
            if attempts >= MAX_ATTEMPTS:
                if time.time() - last_attempt < LOCKOUT_TIME:
                    remaining = int(LOCKOUT_TIME - (time.time() - last_attempt))
                    logger.warning(f"Login attempt from locked out IP: {ip} ({remaining}s remaining)")
                    return False, remaining
                else:
                    # Reset after lockout period
                    logger.info(f"Lockout expired for IP: {ip}")
                    del login_attempts[ip]
        return True, 0

def record_failed_attempt(ip):
    """Record a failed login attempt"""
    with login_attempts_lock:
        if ip in login_attempts:
            attempts, _ = login_attempts[ip]
            login_attempts[ip] = (attempts + 1, time.time())
            logger.warning(f"Failed login attempt from {ip} (attempt {attempts + 1}/{MAX_ATTEMPTS})")
        else:
            login_attempts[ip] = (1, time.time())
            logger.warning(f"Failed login attempt from {ip} (attempt 1/{MAX_ATTEMPTS})")

def reset_attempts(ip):
    """Reset attempts on successful login"""
    with login_attempts_lock:
        if ip in login_attempts:
            del login_attempts[ip]
            logger.info(f"Login attempts reset for {ip}")

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not check_session_activity():
            logger.warning(f"Session expired or unauthorized access attempt to {request.path} from {request.remote_addr}")
            session.clear()
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def login_user():
    """Mark user as authenticated"""
    session['authenticated'] = True
    session['last_activity'] = time.time()
    session.permanent = True
    # Regenerate session ID to prevent session fixation
    session.modified = True
    logger.info(f"User logged in from {request.remote_addr}")

def check_session_activity():
    """Check if session is still active based on last activity"""
    if not session.get('authenticated'):
        return False
    
    last_activity = session.get('last_activity', 0)
    if time.time() - last_activity > 1800:  # 30 minutes in seconds
        return False
    
    # Update last activity
    session['last_activity'] = time.time()
    session.modified = True
    return True

def logout_user():
    """Log out user"""
    logger.info(f"User logged out from {request.remote_addr}")
    session.clear()

def is_authenticated():
    """Check if user is authenticated"""
    return session.get('authenticated', False)
