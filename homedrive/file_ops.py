import os
import shutil
from pathlib import Path
from werkzeug.utils import secure_filename
from config import BASE_DIR

def get_disk_usage():
    """Get disk usage statistics"""
    stat = shutil.disk_usage(BASE_DIR)
    return {
        'total': stat.total,
        'used': stat.used,
        'free': stat.free,
        'percent': (stat.used / stat.total) * 100
    }

def has_space_for_upload(file_size):
    """Check if there's enough disk space for upload"""
    usage = get_disk_usage()
    # Require at least 100MB free after upload
    required_free = file_size + (100 * 1024 * 1024)
    return usage['free'] >= required_free

def is_safe_path(user_path):
    """Validate that path is within BASE_DIR"""
    try:
        base = Path(BASE_DIR).resolve()
        if user_path:
            target = (base / user_path).resolve()
        else:
            target = base
        return str(target).startswith(str(base))
    except:
        return False

def get_full_path(user_path=""):
    """Get full filesystem path from user path"""
    if not is_safe_path(user_path):
        raise ValueError("Invalid path")
    return os.path.join(BASE_DIR, user_path) if user_path else BASE_DIR

def list_directory(user_path=""):
    """List files and folders in directory"""
    full_path = get_full_path(user_path)
    
    if not os.path.exists(full_path):
        return {"folders": [], "files": []}
    
    items = os.listdir(full_path)
    folders = []
    files = []
    
    for item in items:
        item_path = os.path.join(full_path, item)
        if os.path.isdir(item_path):
            folders.append({
                "name": item,
                "path": os.path.join(user_path, item) if user_path else item
            })
        else:
            stat = os.stat(item_path)
            files.append({
                "name": item,
                "path": os.path.join(user_path, item) if user_path else item,
                "size": stat.st_size,
                "modified": stat.st_mtime
            })
    
    folders.sort(key=lambda x: x['name'].lower())
    files.sort(key=lambda x: x['name'].lower())
    
    return {"folders": folders, "files": files}

def create_folder(user_path, folder_name):
    """Create a new folder"""
    folder_name = secure_filename(folder_name)
    if not folder_name:
        raise ValueError("Invalid folder name")
    
    new_path = os.path.join(user_path, folder_name) if user_path else folder_name
    full_path = get_full_path(new_path)
    
    if os.path.exists(full_path):
        raise ValueError("Folder already exists")
    
    os.makedirs(full_path)
    return new_path

def delete_item(user_path):
    """Delete a file or folder"""
    full_path = get_full_path(user_path)
    
    if not os.path.exists(full_path):
        raise ValueError("Item does not exist")
    
    if os.path.isdir(full_path):
        shutil.rmtree(full_path)
    else:
        os.remove(full_path)

def move_item(source_path, dest_folder):
    """Move a file or folder to a different location"""
    source_full = get_full_path(source_path)
    dest_full = get_full_path(dest_folder)
    
    if not os.path.exists(source_full):
        raise ValueError("Source does not exist")
    
    if not os.path.exists(dest_full) or not os.path.isdir(dest_full):
        raise ValueError("Destination folder does not exist")
    
    item_name = os.path.basename(source_full)
    new_path = os.path.join(dest_full, item_name)
    
    if os.path.exists(new_path):
        raise ValueError("Item already exists in destination")
    
    shutil.move(source_full, new_path)
    return os.path.join(dest_folder, item_name) if dest_folder else item_name

def rename_item(user_path, new_name):
    """Rename a file or folder"""
    new_name = secure_filename(new_name)
    if not new_name:
        raise ValueError("Invalid name")
    
    full_path = get_full_path(user_path)
    if not os.path.exists(full_path):
        raise ValueError("Item does not exist")
    
    parent_dir = os.path.dirname(full_path)
    new_full_path = os.path.join(parent_dir, new_name)
    
    if os.path.exists(new_full_path):
        raise ValueError("Item with this name already exists")
    
    os.rename(full_path, new_full_path)
    
    parent_user_path = os.path.dirname(user_path)
    return os.path.join(parent_user_path, new_name) if parent_user_path else new_name

def save_uploaded_file(file, user_path=""):
    """Save an uploaded file with streaming for large files"""
    if not file or not file.filename:
        raise ValueError("No file provided")
    
    filename = secure_filename(file.filename)
    if not filename:
        raise ValueError("Invalid filename")
    
    dest_path = os.path.join(user_path, filename) if user_path else filename
    full_path = get_full_path(dest_path)
    
    # Handle duplicate filenames
    base_name, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(full_path):
        filename = f"{base_name}_{counter}{ext}"
        dest_path = os.path.join(user_path, filename) if user_path else filename
        full_path = get_full_path(dest_path)
        counter += 1
    
    # Stream file to disk in chunks (efficient for large files)
    chunk_size = 4096 * 16  # 64KB chunks
    with open(full_path, 'wb') as f:
        while True:
            chunk = file.stream.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
    
    return dest_path

def get_file_size_readable(size_bytes):
    """Convert bytes to readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"
