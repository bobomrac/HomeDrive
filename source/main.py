import os
import sys
import logging
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
from werkzeug.exceptions import HTTPException

import config
import auth
import file_ops
import maintenance
from setup import setup_wizard

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('homedrive.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Handle frozen/compiled executable
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask(__name__)

# Get secret key from config
try:
    app.secret_key = config.get_secret_key()
except Exception as e:
    logger.warning(f"Could not load secret key from config: {e}")
    import secrets
    app.secret_key = secrets.token_hex(32)

app.permanent_session_lifetime = timedelta(minutes=30)
# No upload size limit - stream large files
app.config['MAX_CONTENT_LENGTH'] = None
# Enable streaming for large files
app.config['MAX_CONTENT_PATH'] = None

# CSRF Protection
def generate_csrf_token():
    """Generate CSRF token for session"""
    if 'csrf_token' not in session:
        import secrets
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def verify_csrf_token():
    """Verify CSRF token from request"""
    token = session.get('csrf_token')
    if not token:
        return False
    
    # Check JSON body first, then form data
    if request.is_json:
        request_token = request.json.get('csrf_token')
    else:
        request_token = request.form.get('csrf_token')
    
    return token == request_token

@app.before_request
def csrf_protect():
    """Protect all POST, PUT, DELETE requests with CSRF token"""
    if request.method in ['POST', 'PUT', 'DELETE']:
        # Skip CSRF for login endpoint (can't have token before authentication)
        if request.endpoint == 'login':
            return
        
        if not verify_csrf_token():
            logger.warning(f"CSRF token validation failed from {request.remote_addr} for {request.endpoint}")
            return jsonify({'error': 'CSRF token validation failed'}), 403

@app.context_processor
def inject_csrf_token():
    """Make CSRF token available to all templates"""
    return dict(csrf_token=generate_csrf_token)

# Routes
@app.route('/')
def index():
    if auth.is_authenticated():
        return render_template('file_browser.html')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        ip = request.remote_addr
        
        # Check if locked out
        allowed, wait_time = auth.check_login_attempts(ip)
        if not allowed:
            return render_template('login.html', error=f'Too many attempts. Try again in {wait_time} seconds')
        
        password = request.form.get('password', '')
        
        try:
            cfg = config.load_config()
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return render_template('login.html', error='Configuration error')
        
        if cfg and config.verify_password(password, cfg['password_hash']):
            auth.reset_attempts(ip)
            auth.login_user()
            # Generate new CSRF token on login
            generate_csrf_token()
            return redirect(url_for('index'))
        else:
            auth.record_failed_attempt(ip)
            attempts_left = auth.MAX_ATTEMPTS - auth.login_attempts.get(ip, (0, 0))[0]
            if attempts_left > 0:
                return render_template('login.html', error=f'Invalid password ({attempts_left} attempts left)')
            else:
                return render_template('login.html', error='Too many attempts. Try again in 5 minutes')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    auth.logout_user()
    return redirect(url_for('login'))

# API Routes
@app.route('/api/files')
@auth.login_required
def api_list_files():
    path = request.args.get('path', '')
    try:
        result = file_ops.list_directory(path)
        return jsonify(result)
    except ValueError as e:
        logger.warning(f"Invalid path request: {path} from {request.remote_addr}")
        return jsonify({'error': str(e)}), 400
    except PermissionError:
        logger.error(f"Permission denied for path: {path}")
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        logger.exception(f"Unexpected error listing directory: {path}")
        return jsonify({'error': 'Failed to list directory'}), 500

@app.route('/api/folder/create', methods=['POST'])
@auth.login_required
def api_create_folder():
    data = request.json
    path = data.get('path', '')
    name = data.get('name', '')
    
    if not name:
        return jsonify({'success': False, 'error': 'Folder name required'}), 400
    
    try:
        new_path = file_ops.create_folder(path, name)
        return jsonify({'success': True, 'path': new_path})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.exception(f"Failed to create folder: {name}")
        return jsonify({'success': False, 'error': 'Failed to create folder'}), 500

@app.route('/api/upload', methods=['POST'])
@auth.login_required
def api_upload():
    path = request.form.get('path', '')
    files = request.files.getlist('files')
    paths = request.form.getlist('paths')  # Get relative paths for folder uploads

    if not files:
        return jsonify({'success': False, 'error': 'No files provided'}), 400

    try:
        uploaded = []
        for i, file in enumerate(files):
            # Get relative path if provided (for folder uploads)
            relative_path = paths[i] if i < len(paths) else None

            # Stream large files to disk instead of loading into memory
            result = file_ops.save_uploaded_file(file, path, relative_path)
            uploaded.append(result)
        return jsonify({'success': True, 'files': uploaded})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.exception("Upload failed")
        return jsonify({'success': False, 'error': 'Upload failed'}), 500

@app.route('/api/download')
@auth.login_required
def api_download():
    path = request.args.get('path', '')
    
    try:
        full_path = file_ops.get_full_path(path)
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            return jsonify({'error': 'File not found'}), 404
        
        logger.info(f"File downloaded: {path} by {request.remote_addr}")
        return send_file(full_path, as_attachment=True, download_name=os.path.basename(full_path))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.exception(f"Download failed for {path}")
        return jsonify({'error': 'Download failed'}), 500

@app.route('/api/thumbnail')
@auth.login_required
def api_thumbnail():
    """Generate and serve thumbnail for image files"""
    path = request.args.get('path', '')
    size = request.args.get('size', '200')
    
    try:
        size = int(size)
        if size < 50 or size > 500:
            size = 200
    except:
        size = 200
    
    try:
        full_path = file_ops.get_full_path(path)
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            return jsonify({'error': 'File not found'}), 404
        
        # Check if it's an image
        ext = os.path.splitext(full_path)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            return jsonify({'error': 'Not an image file'}), 400
        
        # Generate thumbnail (returns BytesIO or None)
        thumbnail = file_ops.generate_thumbnail(full_path, size)
        if thumbnail:
            return send_file(thumbnail, mimetype='image/jpeg')
        else:
            # Fallback to original if thumbnail generation fails
            return send_file(full_path)
            
    except Exception as e:
        logger.exception(f"Thumbnail generation failed for {path}")
        return jsonify({'error': 'Thumbnail generation failed'}), 500

@app.route('/api/rename', methods=['POST'])
@auth.login_required
def api_rename():
    data = request.json
    path = data.get('path', '')
    new_name = data.get('new_name', '')
    
    if not new_name:
        return jsonify({'success': False, 'error': 'New name required'}), 400
    
    try:
        new_path = file_ops.rename_item(path, new_name)
        return jsonify({'success': True, 'path': new_path})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except PermissionError:
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    except Exception as e:
        logger.exception(f"Rename failed for {path}")
        return jsonify({'success': False, 'error': 'Rename failed'}), 500

@app.route('/api/move', methods=['POST'])
@auth.login_required
def api_move():
    data = request.json
    source = data.get('source', '')
    destination = data.get('destination', '')
    
    try:
        new_path = file_ops.move_item(source, destination)
        return jsonify({'success': True, 'path': new_path})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except PermissionError:
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    except Exception as e:
        logger.exception(f"Move failed for {source}")
        return jsonify({'success': False, 'error': 'Move failed'}), 500

@app.route('/api/delete', methods=['POST'])
@auth.login_required
def api_delete():
    data = request.json
    path = data.get('path', '')
    paths = data.get('paths', [])  # Support multiple files
    
    try:
        if paths:
            # Bulk delete
            deleted = []
            errors = []
            for p in paths:
                try:
                    file_ops.delete_item(p)
                    deleted.append(p)
                except Exception as e:
                    errors.append(f"{p}: {str(e)}")
            
            return jsonify({'success': True, 'deleted': deleted, 'errors': errors})
        else:
            # Single delete
            file_ops.delete_item(path)
            return jsonify({'success': True})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except PermissionError:
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    except Exception as e:
        logger.exception(f"Delete failed for {path}")
        return jsonify({'success': False, 'error': 'Delete failed'}), 500

@app.route('/api/move-multiple', methods=['POST'])
@auth.login_required
def api_move_multiple():
    """Move multiple files at once"""
    data = request.json
    sources = data.get('sources', [])
    destination = data.get('destination', '')
    
    if not sources:
        return jsonify({'success': False, 'error': 'No files selected'}), 400
    
    try:
        moved = []
        errors = []
        
        for source in sources:
            try:
                new_path = file_ops.move_item(source, destination)
                moved.append(new_path)
            except Exception as e:
                errors.append(f"{source}: {str(e)}")
        
        return jsonify({'success': True, 'moved': moved, 'errors': errors})
    except Exception as e:
        logger.exception("Bulk move failed")
        return jsonify({'success': False, 'error': 'Move operation failed'}), 500

@app.route('/api/folders')
@auth.login_required
def api_list_folders():
    """Get all folders for move operation (cached version)"""
    try:
        folders = []
        # Simple optimization: limit depth to avoid full tree scan
        max_depth = 5
        
        for root, dirs, files in os.walk(config.BASE_DIR):
            depth = root[len(config.BASE_DIR):].count(os.sep)
            if depth >= max_depth:
                dirs[:] = []  # Don't recurse deeper
                continue
            
            for dir_name in dirs:
                rel_path = os.path.relpath(os.path.join(root, dir_name), config.BASE_DIR)
                folders.append(rel_path)
        
        folders.sort()
        return jsonify({'folders': folders})
    except Exception as e:
        logger.exception("Failed to list folders")
        return jsonify({'error': 'Failed to list folders'}), 500

@app.route('/api/disk-usage')
@auth.login_required
def api_disk_usage():
    """Get disk usage information"""
    try:
        usage = file_ops.get_disk_usage()
        homedrive_usage = file_ops.get_homedrive_usage()
        
        return jsonify({
            'total': usage['total'],
            'used': usage['used'],
            'free': usage['free'],
            'percent': usage['percent'],
            'homedrive_used': homedrive_usage['total'],
            'homedrive_files': homedrive_usage['file_count']
        })
    except Exception as e:
        logger.exception("Failed to get disk usage")
        return jsonify({'error': 'Failed to get disk usage'}), 500

# Maintenance API Routes
@app.route('/api/maintenance/duplicates')
@auth.login_required
def api_find_duplicates():
    try:
        result = maintenance.find_duplicates()
        return jsonify(result)
    except Exception as e:
        logger.exception("Duplicate scan failed")
        return jsonify({'error': 'Duplicate scan failed'}), 500

@app.route('/api/maintenance/delete-duplicates', methods=['POST'])
@auth.login_required
def api_delete_duplicates():
    data = request.json
    paths = data.get('paths', [])
    
    if not paths:
        return jsonify({'error': 'No paths provided'}), 400
    
    try:
        result = maintenance.delete_duplicate_files(paths)
        return jsonify(result)
    except Exception as e:
        logger.exception("Failed to delete duplicates")
        return jsonify({'error': 'Failed to delete duplicates'}), 500

@app.route('/api/maintenance/auto-sort', methods=['POST'])
@auth.login_required
def api_auto_sort():
    try:
        result = maintenance.auto_sort_files()
        return jsonify(result)
    except Exception as e:
        logger.exception("Auto-sort failed")
        return jsonify({'error': 'Auto-sort failed'}), 500

# System operation endpoints (secure - uses polkit, no password required)
@app.route('/api/maintenance/reboot', methods=['POST'])
@auth.login_required
def api_reboot():
    """Reboot system using polkit (no password required)"""
    try:
        result = maintenance.system_reboot()
        return jsonify(result)
    except Exception as e:
        logger.exception("Reboot failed")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/maintenance/update', methods=['POST'])
@auth.login_required
def api_update():
    """Update system using polkit (no password required)"""
    try:
        result = maintenance.system_update()
        return jsonify(result)
    except Exception as e:
        logger.exception("Update failed")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/maintenance/check-polkit')
@auth.login_required
def api_check_polkit():
    """Check if polkit is configured"""
    try:
        configured = maintenance.check_polkit_configured()
        return jsonify({
            'configured': configured,
            'message': 'Polkit configured' if configured else 'Run: sudo python3 setup_polkit.py'
        })
    except Exception as e:
        logger.exception("Failed to check polkit")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/system-commands')
@auth.login_required
def api_get_system_commands():
    """Get current system commands configuration"""
    try:
        cfg = config.load_config()
        return jsonify({
            'commands': cfg.get('system_commands', {}),
            'success': True
        })
    except Exception as e:
        logger.exception("Failed to get system commands")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/system-commands', methods=['POST'])
@auth.login_required
def api_update_system_commands():
    """Update system commands configuration (core commands only)"""
    data = request.json
    commands = data.get('commands', {})
    
    # Only allow core commands
    allowed_keys = ['reboot', 'update', 'shutdown']
    
    # Filter to only allowed commands
    filtered_commands = {k: v for k, v in commands.items() if k in allowed_keys}
    
    # Validate all core commands exist
    for key in allowed_keys:
        if key not in filtered_commands:
            return jsonify({'success': False, 'error': f'Missing core command: {key}'}), 400
        if not filtered_commands[key].strip():
            return jsonify({'success': False, 'error': f'Empty core command: {key}'}), 400
    
    try:
        cfg = config.load_config()
        config.save_config(
            cfg['password_hash'],
            cfg['port'],
            cfg['secret_key'],
            filtered_commands
        )
        logger.info(f"System commands updated: {len(filtered_commands)} commands configured")
        return jsonify({'success': True, 'message': 'Commands updated'})
    except Exception as e:
        logger.exception("Failed to update system commands")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings/detect-commands')
@auth.login_required
def api_detect_commands():
    """Auto-detect system commands"""
    try:
        detected = config.detect_system_commands()
        return jsonify({'commands': detected, 'success': True})
    except Exception as e:
        logger.exception("Failed to detect commands")
        return jsonify({'error': str(e)}), 500

@app.route('/api/maintenance/shutdown', methods=['POST'])
@auth.login_required
def api_shutdown():
    """Shutdown system using polkit (no password required)"""
    try:
        result = maintenance.system_shutdown()
        return jsonify(result)
    except Exception as e:
        logger.exception("Shutdown failed")
        return jsonify({'success': False, 'message': str(e)}), 500

# Favorites API Routes
@app.route('/api/favorites')
@auth.login_required
def api_get_favorites():
    """Get list of favorited folders with metadata"""
    try:
        favorites = config.load_favorites()

        # Get metadata for each favorite
        result = []
        for path in favorites:
            try:
                full_path = file_ops.get_full_path(path)
                if os.path.exists(full_path):
                    result.append({
                        'path': path,
                        'name': os.path.basename(path) or 'Home'
                    })
            except:
                continue

        return jsonify({'favorites': result})
    except Exception as e:
        logger.exception("Failed to get favorites")
        return jsonify({'error': str(e)}), 500

@app.route('/api/favorites/toggle', methods=['POST'])
@auth.login_required
def api_toggle_favorite():
    """Add or remove a folder from favorites"""
    data = request.json
    path = data.get('path', '')

    try:
        # Validate path
        full_path = file_ops.get_full_path(path)
        if not os.path.exists(full_path) or not os.path.isdir(full_path):
            return jsonify({'error': 'Path must be a valid folder'}), 400

        # Load current favorites
        favorites = config.load_favorites()

        # Toggle
        if path in favorites:
            favorites.remove(path)
            is_favorited = False
        else:
            favorites.append(path)
            is_favorited = True

        # Save
        config.save_favorites(favorites)

        return jsonify({'success': True, 'is_favorited': is_favorited})
    except Exception as e:
        logger.exception("Failed to toggle favorite")
        return jsonify({'error': str(e)}), 500

# Change Password API Route
@app.route('/api/settings/change-password', methods=['POST'])
@auth.login_required
def api_change_password():
    """Change user password"""
    data = request.json
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    try:
        # Load current config
        cfg = config.load_config()

        # Verify current password
        if not config.verify_password(current_password, cfg['password_hash']):
            logger.warning(f"Failed password change attempt from {request.remote_addr}")
            return jsonify({'success': False, 'error': 'Current password is incorrect'}), 401

        # Validate new password
        if len(new_password) < 8:
            return jsonify({'success': False, 'error': 'New password must be at least 8 characters'}), 400

        # Hash new password
        new_hash = config.hash_password(new_password)

        # Save config (preserve all other values)
        config.save_config(
            new_hash,
            cfg['port'],
            cfg['secret_key'],
            cfg.get('system_commands', {}),
            cfg.get('ssl_cert'),
            cfg.get('ssl_key'),
            cfg.get('polkit_configured')
        )

        logger.info(f"Password changed successfully from {request.remote_addr}")
        return jsonify({'success': True, 'message': 'Password changed successfully'})

    except Exception as e:
        logger.exception("Password change failed")
        return jsonify({'success': False, 'error': 'Failed to change password'}), 500

# Trash Bin API Routes
@app.route('/api/trash/info')
@auth.login_required
def api_trash_info():
    """Get trash statistics"""
    try:
        info = file_ops.get_trash_info()
        return jsonify(info)
    except Exception as e:
        logger.exception("Failed to get trash info")
        return jsonify({'error': str(e)}), 500

@app.route('/api/trash/empty', methods=['POST'])
@auth.login_required
def api_empty_trash():
    """Permanently delete all trash items"""
    try:
        result = file_ops.empty_trash()
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.exception("Failed to empty trash")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trash/restore', methods=['POST'])
@auth.login_required
def api_restore_trash():
    """Restore item(s) from trash"""
    data = request.json
    trash_name = data.get('trash_name', '')
    trash_names = data.get('trash_names', [])

    try:
        if trash_names:
            # Bulk restore
            restored = []
            errors = []
            for name in trash_names:
                try:
                    restored_path = file_ops.restore_from_trash(name)
                    restored.append(restored_path)
                except Exception as e:
                    errors.append(f"{name}: {str(e)}")

            return jsonify({'success': True, 'restored': restored, 'errors': errors})
        else:
            # Single restore
            restored_path = file_ops.restore_from_trash(trash_name)
            return jsonify({'success': True, 'restored_path': restored_path})

    except Exception as e:
        logger.exception("Failed to restore from trash")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trash/cleanup', methods=['POST'])
@auth.login_required
def api_cleanup_trash():
    """Auto-delete items older than 30 days"""
    try:
        result = file_ops.cleanup_old_trash()
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.exception("Failed to cleanup trash")
        return jsonify({'success': False, 'error': str(e)}), 500

# Folder ZIP Download
@app.route('/api/download-folder')
@auth.login_required
def api_download_folder():
    """Download folder as ZIP file"""
    path = request.args.get('path', '')

    temp_zip = None
    try:
        # Create ZIP
        temp_zip = file_ops.create_folder_zip(path)

        # Determine download name
        folder_name = os.path.basename(path) if path else 'homedrive'
        download_name = f"{folder_name}.zip"

        # Stream ZIP file
        response = send_file(
            temp_zip,
            mimetype='application/zip',
            as_attachment=True,
            download_name=download_name
        )

        # Cleanup temp file after response
        @response.call_on_close
        def cleanup():
            try:
                if temp_zip and os.path.exists(temp_zip):
                    os.remove(temp_zip)
                    logger.info(f"Cleaned up temp ZIP: {temp_zip}")
            except Exception as e:
                logger.error(f"Failed to cleanup temp ZIP {temp_zip}: {e}")

        logger.info(f"Folder downloaded as ZIP: {path} by {request.remote_addr}")
        return response

    except ValueError as e:
        # Cleanup on error
        if temp_zip and os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except:
                pass
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        # Cleanup on error
        if temp_zip and os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except:
                pass
        logger.exception(f"ZIP download failed for {path}")
        return jsonify({'error': 'Failed to create ZIP'}), 500

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(403)
def forbidden(e):
    return jsonify({'error': 'Forbidden'}), 403

@app.errorhandler(500)
def server_error(e):
    logger.exception("Internal server error")
    return jsonify({'error': 'Internal server error'}), 500

def start_server():
    """Start the Flask server"""
    try:
        cfg = config.load_config()
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        print(f"\nError: Cannot load configuration: {e}")
        print("Please run setup again.\n")
        sys.exit(1)
    
    # Check environment variable first, then config, then default
    port = int(os.environ.get('HOMEDRIVE_PORT', cfg.get('port', 8080) if cfg else 8080))
    
    # Validate port
    if port < 1 or port > 65535:
        logger.error(f"Invalid port number: {port}")
        print(f"\nError: Invalid port number: {port}")
        print("Port must be between 1 and 65535.\n")
        sys.exit(1)
    
    # Check for SSL certificates - config first, then environment variables
    cert_file = None
    key_file = None
    
    # Try config first
    if cfg:
        cert_file = cfg.get('ssl_cert')
        key_file = cfg.get('ssl_key')
    
    # Environment variables override config
    if os.environ.get('HOMEDRIVE_CERT'):
        cert_file = os.environ.get('HOMEDRIVE_CERT')
    if os.environ.get('HOMEDRIVE_KEY'):
        key_file = os.environ.get('HOMEDRIVE_KEY')
    
    ssl_context = None
    protocol = "http"
    
    # Get network IP
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        network_ip = s.getsockname()[0]
        s.close()
    except:
        network_ip = "YOUR_IP"
    
    if cert_file and key_file and os.path.exists(cert_file) and os.path.exists(key_file):
        ssl_context = (cert_file, key_file)
        protocol = "https"
        
        # Check if using Let's Encrypt
        is_letsencrypt = "letsencrypt" in cert_file.lower()
        
        logger.info(f"Starting with HTTPS on port {port}")
        print(f"\n{'='*60}")
        print(f"HomeDrive is running at:")
        print(f"  Local:   {protocol}://localhost:{port}")
        print(f"  Network: {protocol}://{network_ip}:{port}")
        if is_letsencrypt:
            print(f"\n  Using Let's Encrypt certificate (trusted)")
        else:
            print(f"\n  Using self-signed certificate")
            print(f"  (Browser will show security warning)")
        print(f"{'='*60}\n")
    else:
        logger.warning("Starting without HTTPS - traffic is not encrypted")
        print(f"\n{'='*60}")
        print(f"⚠️  WARNING: Running without HTTPS")
        print(f"   Traffic is NOT encrypted!")
        print(f"")
        print(f"  Local:   {protocol}://localhost:{port}")
        print(f"  Network: {protocol}://{network_ip}:{port}")
        print(f"")
        print(f"To enable HTTPS:")
        print(f"  Run setup again and choose option 1 or 2")
        print(f"{'='*60}\n")

    # Start periodic trash cleanup thread
    import threading
    import time
    def periodic_trash_cleanup():
        while True:
            try:
                file_ops.cleanup_old_trash()
            except Exception as e:
                logger.error(f"Periodic trash cleanup failed: {e}")
            time.sleep(24 * 60 * 60)  # Run daily

    cleanup_thread = threading.Thread(target=periodic_trash_cleanup, daemon=True)
    cleanup_thread.start()
    logger.info("Started periodic trash cleanup thread")

    try:
        logger.info(f"Starting Flask server on {protocol}://0.0.0.0:{port}")
        app.run(host='0.0.0.0', port=port, debug=False, ssl_context=ssl_context)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        print("\nShutting down HomeDrive...")
    except Exception as e:
        logger.exception("Server failed to start")
        print(f"\nError starting server: {e}")
        sys.exit(1)

if __name__ == '__main__':
    # Check if this is first run
    if config.is_first_run():
        logger.info("First run detected - starting setup wizard")
        print("First run detected. Starting setup wizard...")
        success = setup_wizard()
        if not success:
            # If service wasn't installed, start server manually
            start_server()
    else:
        # Normal operation
        logger.info("Starting HomeDrive")
        start_server()
