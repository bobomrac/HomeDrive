import os
import shutil
import logging
import threading
import time
import json
import zipfile
import tempfile
from pathlib import Path
from werkzeug.utils import secure_filename
from config import BASE_DIR

logger = logging.getLogger(__name__)

# Constants
MAX_FILENAME_LENGTH = 255
CHUNK_SIZE = 64 * 1024  # 64KB for file operations
MIN_FREE_SPACE = 100 * 1024 * 1024  # 100MB minimum free space
THUMBNAIL_SIZE = 200
THUMBNAIL_MAX_SOURCE_SIZE = 50 * 1024 * 1024  # Don't thumbnail files >50MB
TRASH_DIR = os.path.join(BASE_DIR, ".trash")
TRASH_MANIFEST = os.path.join(TRASH_DIR, ".trash_manifest.json")
TRASH_MAX_AGE_DAYS = 30

# Lock for file operations to prevent race conditions
file_ops_lock = threading.Lock()

def get_disk_usage():
    """Get disk usage statistics for the partition containing BASE_DIR"""
    stat = shutil.disk_usage(BASE_DIR)
    return {
        'total': stat.total,
        'used': stat.used,
        'free': stat.free,
        'percent': (stat.used / stat.total) * 100
    }

def get_homedrive_usage():
    """Get actual storage used by HomeDrive files"""
    total_size = 0
    file_count = 0
    
    try:
        for root, dirs, files in os.walk(BASE_DIR):
            for file in files:
                try:
                    filepath = os.path.join(root, file)
                    total_size += os.path.getsize(filepath)
                    file_count += 1
                except (OSError, IOError) as e:
                    logger.warning(f"Cannot stat file {file}: {e}")
                    continue
    except Exception as e:
        logger.error(f"Error calculating HomeDrive usage: {e}")
        return {'total': 0, 'file_count': 0}
    
    return {'total': total_size, 'file_count': file_count}

def has_space_for_upload(file_size):
    """Check if there's enough disk space for upload"""
    usage = get_disk_usage()
    required_free = file_size + MIN_FREE_SPACE
    return usage['free'] >= required_free

def is_safe_path(user_path):
    """Validate that path is within BASE_DIR and doesn't contain malicious patterns"""
    try:
        base = Path(BASE_DIR).resolve()
        if user_path:
            target = (base / user_path).resolve()
        else:
            target = base
        
        is_safe = str(target).startswith(str(base))
        
        if not is_safe:
            logger.warning(f"Path traversal attempt detected: {user_path}")
        
        return is_safe
    except (ValueError, OSError) as e:
        logger.warning(f"Invalid path validation for {user_path}: {e}")
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
    
    if not os.path.isdir(full_path):
        raise ValueError("Not a directory")
    
    try:
        items = os.listdir(full_path)
    except PermissionError:
        raise PermissionError("Permission denied")
    except OSError as e:
        raise OSError(f"Cannot read directory: {e}")
    
    folders = []
    files = []
    
    for item in items:
        item_path = os.path.join(full_path, item)
        try:
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
        except (OSError, IOError) as e:
            logger.warning(f"Cannot stat {item}: {e}")
            continue
    
    folders.sort(key=lambda x: x['name'].lower())
    files.sort(key=lambda x: x['name'].lower())
    
    return {"folders": folders, "files": files}

def create_folder(user_path, folder_name):
    """Create a new folder"""
    folder_name = secure_filename(folder_name)
    if not folder_name:
        raise ValueError("Invalid folder name")
    
    if len(folder_name) > MAX_FILENAME_LENGTH:
        raise ValueError(f"Folder name too long (max {MAX_FILENAME_LENGTH} characters)")
    
    new_path = os.path.join(user_path, folder_name) if user_path else folder_name
    full_path = get_full_path(new_path)
    
    with file_ops_lock:
        if os.path.exists(full_path):
            raise ValueError("Folder already exists")
        
        try:
            os.makedirs(full_path)
            logger.info(f"Created folder: {new_path}")
        except OSError as e:
            logger.error(f"Failed to create folder {new_path}: {e}")
            raise ValueError(f"Cannot create folder: {e}")
    
    return new_path

def delete_item(user_path):
    """Delete a file or folder (moves to trash)"""
    # Move to trash instead of permanent deletion
    return move_to_trash(user_path)

def move_item(source_path, dest_folder):
    """Move a file or folder to a different location (works across filesystems)"""
    source_full = get_full_path(source_path)
    dest_full = get_full_path(dest_folder)
    
    if not os.path.exists(source_full):
        raise ValueError("Source does not exist")
    
    if not os.path.exists(dest_full) or not os.path.isdir(dest_full):
        raise ValueError("Destination folder does not exist")
    
    item_name = os.path.basename(source_full)
    new_path = os.path.join(dest_full, item_name)
    
    with file_ops_lock:
        if os.path.exists(new_path):
            raise ValueError("Item already exists in destination")
        
        try:
            # Use shutil.move which handles cross-filesystem moves
            shutil.move(source_full, new_path)
            result_path = os.path.join(dest_folder, item_name) if dest_folder else item_name
            logger.info(f"Moved {source_path} to {result_path}")
            return result_path
        except PermissionError:
            raise PermissionError("Permission denied")
        except OSError as e:
            logger.error(f"Failed to move {source_path} to {dest_folder}: {e}")
            raise ValueError(f"Cannot move item: {e}")

def rename_item(user_path, new_name):
    """Rename a file or folder atomically"""
    new_name = secure_filename(new_name)
    if not new_name:
        raise ValueError("Invalid name")
    
    if len(new_name) > MAX_FILENAME_LENGTH:
        raise ValueError(f"Name too long (max {MAX_FILENAME_LENGTH} characters)")
    
    full_path = get_full_path(user_path)
    if not os.path.exists(full_path):
        raise ValueError("Item does not exist")
    
    parent_dir = os.path.dirname(full_path)
    new_full_path = os.path.join(parent_dir, new_name)
    
    with file_ops_lock:
        if os.path.exists(new_full_path):
            raise ValueError("Item with this name already exists")
        
        try:
            # Use os.replace for atomic rename
            os.replace(full_path, new_full_path)
            parent_user_path = os.path.dirname(user_path)
            result_path = os.path.join(parent_user_path, new_name) if parent_user_path else new_name
            logger.info(f"Renamed {user_path} to {result_path}")
            return result_path
        except PermissionError:
            raise PermissionError("Permission denied")
        except OSError as e:
            logger.error(f"Failed to rename {user_path} to {new_name}: {e}")
            raise ValueError(f"Cannot rename item: {e}")

def save_uploaded_file(file, user_path="", relative_path=None):
    """Save an uploaded file with streaming for large files (atomic)"""
    if not file or not file.filename:
        raise ValueError("No file provided")

    # If relative_path is provided (folder upload), use it to preserve structure
    if relative_path:
        # Extract directory structure from relative path
        file_dir = os.path.dirname(relative_path)
        filename = os.path.basename(relative_path)

        # Secure the filename
        filename = secure_filename(filename)
        if not filename:
            raise ValueError("Invalid filename")

        # Build the upload path preserving folder structure
        if file_dir:
            upload_path = os.path.join(user_path, file_dir) if user_path else file_dir
        else:
            upload_path = user_path
    else:
        # Normal single file upload
        filename = secure_filename(file.filename)
        if not filename:
            raise ValueError("Invalid filename")
        upload_path = user_path

    if len(filename) > MAX_FILENAME_LENGTH:
        raise ValueError(f"Filename too long (max {MAX_FILENAME_LENGTH} characters)")

    dest_path = os.path.join(upload_path, filename) if upload_path else filename
    full_path = get_full_path(dest_path)

    # Create parent directories if they don't exist (for folder uploads)
    parent_dir = os.path.dirname(full_path)
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create parent directories for {dest_path}: {e}")
            raise ValueError(f"Cannot create directory structure: {e}")

    # Handle duplicate filenames with lock protection
    with file_ops_lock:
        base_name, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(full_path):
            filename = f"{base_name}_{counter}{ext}"
            dest_path = os.path.join(user_path, filename) if user_path else filename
            full_path = get_full_path(dest_path)
            counter += 1
        
        # Write to temporary file first, then rename atomically
        temp_path = full_path + '.tmp'
        try:
            # Stream file to disk in chunks (efficient for large files)
            with open(temp_path, 'wb') as f:
                while True:
                    chunk = file.stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
            
            # Atomic rename
            os.replace(temp_path, full_path)
            logger.info(f"Uploaded file: {dest_path}")
            return dest_path
            
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            logger.error(f"Failed to upload file {filename}: {e}")
            raise ValueError(f"Cannot save file: {e}")

def get_file_size_readable(size_bytes):
    """Convert bytes to readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"

def generate_thumbnail(file_path, size=THUMBNAIL_SIZE):
    """Generate thumbnail for image file"""
    try:
        # Don't generate thumbnails for huge files
        file_size = os.path.getsize(file_path)
        if file_size > THUMBNAIL_MAX_SOURCE_SIZE:
            logger.warning(f"File {file_path} too large for thumbnail ({file_size} bytes)")
            return None

        from PIL import Image
        import io

        # Open and resize image
        with Image.open(file_path) as img:
            # Convert to RGB if necessary (for PNG with transparency, etc)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background

            # Resize maintaining aspect ratio
            img.thumbnail((size, size), Image.Resampling.LANCZOS)

            # Return as BytesIO instead of temp file (avoids disk clutter)
            output = io.BytesIO()
            img.save(output, 'JPEG', quality=85, optimize=True)
            output.seek(0)

            return output

    except ImportError:
        logger.warning("PIL/Pillow not installed - thumbnails disabled")
        return None
    except Exception as e:
        logger.warning(f"Failed to generate thumbnail for {file_path}: {e}")
        return None

# Trash Bin Functions
def load_trash_manifest():
    """Load trash manifest with error handling"""
    if not os.path.exists(TRASH_MANIFEST):
        return {"items": []}

    try:
        with open(TRASH_MANIFEST, 'r') as f:
            return json.load(f)
    except:
        logger.error("Failed to load trash manifest, creating new one")
        return {"items": []}

def save_trash_manifest(manifest):
    """Save trash manifest atomically"""
    # Ensure .trash directory exists
    if not os.path.exists(TRASH_DIR):
        os.makedirs(TRASH_DIR)

    temp_file = TRASH_MANIFEST + '.tmp'
    try:
        with open(temp_file, 'w') as f:
            json.dump(manifest, f, indent=2)
        os.chmod(temp_file, 0o600)
        os.rename(temp_file, TRASH_MANIFEST)
    except Exception as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise e

def get_dir_size(path):
    """Calculate total size of directory"""
    total = 0
    try:
        for root, dirs, files in os.walk(path):
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    total += os.path.getsize(filepath)
                except:
                    continue
    except:
        pass
    return total

def move_to_trash(user_path):
    """Move item to trash instead of deleting"""
    full_path = get_full_path(user_path)

    if not os.path.exists(full_path):
        raise ValueError("Item does not exist")

    with file_ops_lock:
        # Ensure trash directory exists
        if not os.path.exists(TRASH_DIR):
            os.makedirs(TRASH_DIR)

        # Generate unique trash name
        timestamp = int(time.time())
        original_name = os.path.basename(full_path)
        trash_name = f"item_{timestamp}_{original_name}"
        trash_path = os.path.join(TRASH_DIR, trash_name)

        # Handle collisions (very unlikely but possible)
        counter = 1
        while os.path.exists(trash_path):
            trash_name = f"item_{timestamp}_{counter}_{original_name}"
            trash_path = os.path.join(TRASH_DIR, trash_name)
            counter += 1

        try:
            # Move to trash
            shutil.move(full_path, trash_path)

            # Update manifest
            manifest = load_trash_manifest()
            manifest["items"].append({
                "trash_name": trash_name,
                "original_path": user_path,
                "original_name": original_name,
                "deletion_time": timestamp,
                "is_folder": os.path.isdir(trash_path),
                "size": get_dir_size(trash_path) if os.path.isdir(trash_path) else os.path.getsize(trash_path)
            })
            save_trash_manifest(manifest)

            logger.info(f"Moved to trash: {user_path}")
            return trash_name

        except Exception as e:
            logger.error(f"Failed to move {user_path} to trash: {e}")
            # Try to restore if move failed
            if os.path.exists(trash_path) and not os.path.exists(full_path):
                try:
                    shutil.move(trash_path, full_path)
                except:
                    pass
            raise ValueError(f"Cannot move to trash: {e}")

def restore_from_trash(trash_name):
    """Restore item from trash to original location"""
    with file_ops_lock:
        manifest = load_trash_manifest()

        # Find item in manifest
        item = None
        for i, trash_item in enumerate(manifest["items"]):
            if trash_item["trash_name"] == trash_name:
                item = trash_item
                item_index = i
                break

        if not item:
            raise ValueError("Item not found in trash")

        trash_path = os.path.join(TRASH_DIR, trash_name)
        if not os.path.exists(trash_path):
            # Remove from manifest if file doesn't exist
            manifest["items"].pop(item_index)
            save_trash_manifest(manifest)
            raise ValueError("Trash item file not found")

        # Get original path
        original_path = item["original_path"]
        restore_path = get_full_path(original_path)

        # Handle collision - add " (restored)" suffix
        if os.path.exists(restore_path):
            base, ext = os.path.splitext(restore_path)
            counter = 1
            while os.path.exists(restore_path):
                restore_path = f"{base} (restored {counter}){ext}"
                counter += 1

        # Ensure parent directory exists
        parent_dir = os.path.dirname(restore_path)
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir)

        try:
            # Restore item
            shutil.move(trash_path, restore_path)

            # Remove from manifest
            manifest["items"].pop(item_index)
            save_trash_manifest(manifest)

            # Return final path (may differ from original if renamed)
            final_path = os.path.relpath(restore_path, BASE_DIR)
            logger.info(f"Restored from trash: {trash_name} -> {final_path}")
            return final_path

        except Exception as e:
            logger.error(f"Failed to restore {trash_name}: {e}")
            raise ValueError(f"Cannot restore item: {e}")

def empty_trash():
    """Permanently delete all items in trash"""
    with file_ops_lock:
        if not os.path.exists(TRASH_DIR):
            return {"deleted": 0, "errors": []}

        manifest = load_trash_manifest()
        deleted_count = 0
        errors = []

        for item in manifest["items"]:
            trash_path = os.path.join(TRASH_DIR, item["trash_name"])
            try:
                if os.path.exists(trash_path):
                    if os.path.isdir(trash_path):
                        shutil.rmtree(trash_path)
                    else:
                        os.remove(trash_path)
                    deleted_count += 1
            except Exception as e:
                errors.append(f"{item['trash_name']}: {str(e)}")
                logger.error(f"Failed to delete trash item {item['trash_name']}: {e}")

        # Clear manifest
        save_trash_manifest({"items": []})

        logger.info(f"Emptied trash: {deleted_count} items deleted")
        return {"deleted": deleted_count, "errors": errors}

def cleanup_old_trash():
    """Auto-delete items older than TRASH_MAX_AGE_DAYS"""
    with file_ops_lock:
        if not os.path.exists(TRASH_DIR):
            return {"deleted": 0, "errors": []}

        manifest = load_trash_manifest()
        current_time = int(time.time())
        max_age_seconds = TRASH_MAX_AGE_DAYS * 24 * 60 * 60

        items_to_keep = []
        deleted_count = 0
        errors = []

        for item in manifest["items"]:
            age = current_time - item["deletion_time"]

            if age > max_age_seconds:
                # Delete old item
                trash_path = os.path.join(TRASH_DIR, item["trash_name"])
                try:
                    if os.path.exists(trash_path):
                        if os.path.isdir(trash_path):
                            shutil.rmtree(trash_path)
                        else:
                            os.remove(trash_path)
                    deleted_count += 1
                    logger.info(f"Auto-deleted old trash item: {item['trash_name']}")
                except Exception as e:
                    errors.append(f"{item['trash_name']}: {str(e)}")
                    logger.error(f"Failed to auto-delete {item['trash_name']}: {e}")
                    items_to_keep.append(item)  # Keep in manifest if delete failed
            else:
                items_to_keep.append(item)

        # Update manifest
        manifest["items"] = items_to_keep
        save_trash_manifest(manifest)

        if deleted_count > 0:
            logger.info(f"Auto-cleanup: {deleted_count} old items deleted")

        return {"deleted": deleted_count, "errors": errors}

def get_trash_info():
    """Get trash statistics"""
    if not os.path.exists(TRASH_DIR):
        return {"count": 0, "total_size": 0}

    manifest = load_trash_manifest()

    total_size = 0
    for item in manifest["items"]:
        total_size += item.get("size", 0)

    return {
        "count": len(manifest["items"]),
        "total_size": total_size
    }

def formatFileSize(bytes):
    """Format bytes as human-readable size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024.0:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.1f} TB"

def create_folder_zip(user_path):
    """Create ZIP file of folder contents, return temp file path"""
    full_path = get_full_path(user_path)

    if not os.path.exists(full_path) or not os.path.isdir(full_path):
        raise ValueError("Path must be a valid folder")

    # Calculate total size first
    total_size = get_dir_size(full_path)
    max_size = 2 * 1024 * 1024 * 1024  # 2GB limit

    if total_size > max_size:
        raise ValueError(f"Folder too large to ZIP ({formatFileSize(total_size)}). Maximum: 2GB")

    # Create temporary ZIP file
    temp_fd, temp_path = tempfile.mkstemp(suffix='.zip', prefix='homedrive_')
    os.close(temp_fd)

    try:
        with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
            # Walk directory and add files
            for root, dirs, files in os.walk(full_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Create archive name relative to the folder being zipped
                    arcname = os.path.relpath(file_path, full_path)

                    try:
                        zipf.write(file_path, arcname)
                    except Exception as e:
                        logger.warning(f"Failed to add {file_path} to ZIP: {e}")
                        continue

        logger.info(f"Created ZIP for folder: {user_path} ({formatFileSize(os.path.getsize(temp_path))})")
        return temp_path

    except Exception as e:
        # Cleanup temp file on error
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        raise ValueError(f"Failed to create ZIP: {e}")
