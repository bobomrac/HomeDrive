import os
import sys
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
from werkzeug.exceptions import HTTPException

import config
import auth
import file_ops
import maintenance
from setup import setup_wizard

# Handle frozen/compiled executable
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask(__name__)

app.secret_key = auth.SECRET_KEY
app.permanent_session_lifetime = timedelta(hours=24)
# No upload size limit - stream large files
app.config['MAX_CONTENT_LENGTH'] = None
# Enable streaming for large files
app.config['MAX_CONTENT_PATH'] = None

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
        cfg = config.load_config()
        
        if cfg and config.verify_password(password, cfg['password_hash']):
            auth.reset_attempts(ip)
            auth.login_user()
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
        return jsonify({'error': 'Invalid path'}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to list directory'}), 400

@app.route('/api/folder/create', methods=['POST'])
@auth.login_required
def api_create_folder():
    data = request.json
    path = data.get('path', '')
    name = data.get('name', '')
    
    try:
        new_path = file_ops.create_folder(path, name)
        return jsonify({'success': True, 'path': new_path})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/upload', methods=['POST'])
@auth.login_required
def api_upload():
    path = request.form.get('path', '')
    files = request.files.getlist('files')
    
    if not files:
        return jsonify({'success': False, 'error': 'No files provided'}), 400
    
    try:
        uploaded = []
        for file in files:
            # Stream large files to disk instead of loading into memory
            result = file_ops.save_uploaded_file(file, path)
            uploaded.append(result)
        return jsonify({'success': True, 'files': uploaded})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/download')
@auth.login_required
def api_download():
    path = request.args.get('path', '')
    
    try:
        full_path = file_ops.get_full_path(path)
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(full_path, as_attachment=True, download_name=os.path.basename(full_path))
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/rename', methods=['POST'])
@auth.login_required
def api_rename():
    data = request.json
    path = data.get('path', '')
    new_name = data.get('new_name', '')
    
    try:
        new_path = file_ops.rename_item(path, new_name)
        return jsonify({'success': True, 'path': new_path})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/move', methods=['POST'])
@auth.login_required
def api_move():
    data = request.json
    source = data.get('source', '')
    destination = data.get('destination', '')
    
    try:
        new_path = file_ops.move_item(source, destination)
        return jsonify({'success': True, 'path': new_path})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/delete', methods=['POST'])
@auth.login_required
def api_delete():
    data = request.json
    path = data.get('path', '')
    
    try:
        file_ops.delete_item(path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/folders')
@auth.login_required
def api_list_folders():
    """Get all folders for move operation"""
    try:
        folders = []
        for root, dirs, files in os.walk(config.BASE_DIR):
            for dir_name in dirs:
                rel_path = os.path.relpath(os.path.join(root, dir_name), config.BASE_DIR)
                folders.append(rel_path)
        folders.sort()
        return jsonify({'folders': folders})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/disk-usage')
@auth.login_required
def api_disk_usage():
    """Get disk usage information"""
    try:
        usage = file_ops.get_disk_usage()
        return jsonify(usage)
    except Exception as e:
        return jsonify({'error': 'Failed to get disk usage'}), 500

# Maintenance API Routes
@app.route('/api/maintenance/duplicates')
@auth.login_required
def api_find_duplicates():
    try:
        result = maintenance.find_duplicates()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/maintenance/delete-duplicates', methods=['POST'])
@auth.login_required
def api_delete_duplicates():
    data = request.json
    paths = data.get('paths', [])
    
    try:
        result = maintenance.delete_duplicate_files(paths)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/maintenance/auto-sort', methods=['POST'])
@auth.login_required
def api_auto_sort():
    try:
        result = maintenance.auto_sort_files()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/maintenance/reboot', methods=['POST'])
@auth.login_required
def api_reboot():
    data = request.json
    sudo_password = data.get('sudo_password', '')
    
    if not sudo_password:
        return jsonify({'success': False, 'message': 'Password required'}), 400
    
    try:
        result = maintenance.system_reboot(sudo_password)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/maintenance/update', methods=['POST'])
@auth.login_required
def api_update():
    data = request.json
    sudo_password = data.get('sudo_password', '')
    
    if not sudo_password:
        return jsonify({'success': False, 'message': 'Password required'}), 400
    
    try:
        result = maintenance.system_update(sudo_password)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

def start_server():
    """Start the Flask server"""
    cfg = config.load_config()
    
    # Check environment variable first, then config, then default
    port = int(os.environ.get('HOMEDRIVE_PORT', cfg.get('port', 8080) if cfg else 8080))
    
    # Check for SSL certificates
    cert_file = os.environ.get('HOMEDRIVE_CERT')
    key_file = os.environ.get('HOMEDRIVE_KEY')
    
    ssl_context = None
    protocol = "http"
    
    if cert_file and key_file and os.path.exists(cert_file) and os.path.exists(key_file):
        ssl_context = (cert_file, key_file)
        protocol = "https"
        
        # Check if using Let's Encrypt
        is_letsencrypt = "letsencrypt" in cert_file.lower()
        
        print(f"\n{'='*60}")
        print(f"HomeDrive is running at:")
        print(f"  {protocol}://localhost:{port}")
        if is_letsencrypt:
            print(f"  Using Let's Encrypt certificate (trusted)")
        else:
            print(f"  Using self-signed certificate")
            print(f"  (Browser will show security warning)")
        print(f"{'='*60}\n")
    else:
        print(f"\n{'='*60}")
        print(f"⚠️  WARNING: Running without HTTPS")
        print(f"   Traffic is NOT encrypted!")
        print(f"")
        print(f"  {protocol}://localhost:{port}")
        print(f"")
        print(f"To enable HTTPS:")
        print(f"  Option 1 (Recommended): ./setup-letsencrypt.sh")
        print(f"  Option 2 (LAN only):     ./generate-cert.sh")
        print(f"{'='*60}\n")
    
    try:
        app.run(host='0.0.0.0', port=port, debug=False, ssl_context=ssl_context)
    except KeyboardInterrupt:
        print("\nShutting down HomeDrive...")
    except Exception as e:
        print(f"\nError starting server: {e}")
        sys.exit(1)

if __name__ == '__main__':
    # Check if this is first run
    if config.is_first_run():
        print("First run detected. Starting setup wizard...")
        success = setup_wizard()
        if not success:
            # If service wasn't installed, start server manually
            start_server()
    else:
        # Normal operation
        start_server()
