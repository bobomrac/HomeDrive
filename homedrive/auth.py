from functools import wraps
from flask import session, redirect, url_for
import secrets
import time

SECRET_KEY = secrets.token_hex(32)

# Login attempt tracking
login_attempts = {}
MAX_ATTEMPTS = 5
LOCKOUT_TIME = 300  # 5 minutes

def check_login_attempts(ip):
    """Check if IP is locked out"""
    if ip in login_attempts:
        attempts, last_attempt = login_attempts[ip]
        if attempts >= MAX_ATTEMPTS:
            if time.time() - last_attempt < LOCKOUT_TIME:
                return False, int(LOCKOUT_TIME - (time.time() - last_attempt))
            else:
                # Reset after lockout period
                del login_attempts[ip]
    return True, 0

def record_failed_attempt(ip):
    """Record a failed login attempt"""
    if ip in login_attempts:
        attempts, _ = login_attempts[ip]
        login_attempts[ip] = (attempts + 1, time.time())
    else:
        login_attempts[ip] = (1, time.time())

def reset_attempts(ip):
    """Reset attempts on successful login"""
    if ip in login_attempts:
        del login_attempts[ip]

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def login_user():
    """Mark user as authenticated"""
    session['authenticated'] = True
    session.permanent = True

def logout_user():
    """Log out user"""
    session.clear()

def is_authenticated():
    """Check if user is authenticated"""
    return session.get('authenticated', False)
