import os
import hashlib
import shutil
import subprocess
import logging
import threading
from pathlib import Path
from collections import defaultdict
from config import BASE_DIR
from file_ops import is_safe_path, get_full_path

logger = logging.getLogger(__name__)

# Constants
LARGE_FILE_THRESHOLD = 100 * 1024 * 1024  # 100MB
PARTIAL_HASH_SIZE = 1 * 1024 * 1024  # 1MB for partial hashing
HASH_CHUNK_SIZE = 64 * 1024  # 64KB chunks for hashing

# Lock for maintenance operations
maintenance_lock = threading.Lock()

def hash_file(filepath, partial=False):
    """Generate SHA256 hash of a file
    
    Args:
        filepath: Path to file
        partial: If True and file > 100MB, only hash first/last 1MB
    """
    sha256_hash = hashlib.sha256()
    file_size = os.path.getsize(filepath)
    
    # For large files, do partial hash first
    if partial and file_size > LARGE_FILE_THRESHOLD:
        with open(filepath, "rb") as f:
            # Hash first 1MB
            sha256_hash.update(f.read(PARTIAL_HASH_SIZE))
            # Hash last 1MB
            f.seek(-PARTIAL_HASH_SIZE, 2)
            sha256_hash.update(f.read(PARTIAL_HASH_SIZE))
    else:
        # Full hash for smaller files
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(HASH_CHUNK_SIZE), b""):
                sha256_hash.update(byte_block)
    
    return sha256_hash.hexdigest()

def find_duplicates():
    """Find duplicate files using optimized size-first algorithm"""
    with maintenance_lock:
        logger.info("Starting duplicate scan")
        
        # Step 1: Group by size (fast)
        size_groups = defaultdict(list)
        total_files = 0
        
        for root, dirs, files in os.walk(BASE_DIR):
            # Skip _duplicates and .trash folders
            if '_duplicates' in root or '.trash' in root:
                continue
            
            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    file_size = os.path.getsize(filepath)
                    rel_path = os.path.relpath(filepath, BASE_DIR)
                    
                    size_groups[file_size].append({
                        "path": rel_path,
                        "full_path": filepath
                    })
                    total_files += 1
                except (IOError, OSError) as e:
                    logger.warning(f"Cannot access {filepath}: {e}")
                    continue
        
        logger.info(f"Scanned {total_files} files")
        
        # Step 2: Only hash files where size matches another file
        file_hashes = defaultdict(list)
        files_to_hash = []
        
        for size, files in size_groups.items():
            if len(files) > 1:  # Only hash if multiple files have same size
                files_to_hash.extend(files)
        
        logger.info(f"Hashing {len(files_to_hash)} potential duplicates")
        
        # Step 3: Hash potential duplicates
        for file_info in files_to_hash:
            try:
                # Try partial hash first for large files
                file_hash = hash_file(file_info['full_path'], partial=True)
                file_size = os.path.getsize(file_info['full_path'])
                
                file_hashes[file_hash].append({
                    "path": file_info['path'],
                    "size": file_size,
                    "full_path": file_info['full_path']
                })
            except (IOError, OSError) as e:
                logger.warning(f"Cannot hash {file_info['path']}: {e}")
                continue
        
        # Step 4: For large files with matching partial hashes, do full hash
        final_hashes = defaultdict(list)
        
        for partial_hash, files in file_hashes.items():
            if len(files) > 1:
                # Check if these are large files
                if files[0]['size'] > LARGE_FILE_THRESHOLD:
                    # Do full hash to confirm
                    for file_info in files:
                        try:
                            full_hash = hash_file(file_info['full_path'], partial=False)
                            final_hashes[full_hash].append(file_info)
                        except (IOError, OSError) as e:
                            logger.warning(f"Cannot fully hash {file_info['path']}: {e}")
                            continue
                else:
                    # Small files already have full hash
                    final_hashes[partial_hash] = files
        
        # Filter to only actual duplicates
        duplicates = {k: v for k, v in final_hashes.items() if len(v) > 1}
        
        if not duplicates:
            logger.info("No duplicates found")
            return {"count": 0, "duplicates": []}
        
        logger.info(f"Found {len(duplicates)} duplicate groups")
        
        # Create _duplicates folder
        dupes_folder = os.path.join(BASE_DIR, "_duplicates")
        if os.path.exists(dupes_folder):
            shutil.rmtree(dupes_folder)
        os.makedirs(dupes_folder)
        
        # Copy duplicates to folder, organized by hash
        for file_hash, files in duplicates.items():
            # Create subfolder for this duplicate group
            hash_folder = os.path.join(dupes_folder, file_hash[:8])
            os.makedirs(hash_folder, exist_ok=True)
            
            # Copy all duplicate files
            for idx, file_info in enumerate(files):
                src = file_info['full_path']
                # Preserve original path structure in filename
                safe_path = file_info['path'].replace('/', '_').replace('\\', '_')
                dst = os.path.join(hash_folder, f"{idx}_{safe_path}")
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    logger.warning(f"Cannot copy duplicate {src}: {e}")
                    continue
        
        # Format for return
        result = []
        for file_hash, files in duplicates.items():
            result.append({
                "hash": file_hash,
                "count": len(files),
                "size": files[0]["size"],
                "files": files
            })
        
        logger.info(f"Duplicate scan complete: {len(result)} groups found")
        return {"count": len(result), "duplicates": result}

def delete_duplicate_files(file_paths):
    """Delete specified duplicate files"""
    deleted = []
    errors = []
    
    with maintenance_lock:
        for rel_path in file_paths:
            try:
                if not is_safe_path(rel_path):
                    errors.append(f"{rel_path}: Invalid path")
                    logger.warning(f"Attempted to delete invalid path: {rel_path}")
                    continue
                
                full_path = get_full_path(rel_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
                    deleted.append(rel_path)
                    logger.info(f"Deleted duplicate file: {rel_path}")
                else:
                    errors.append(f"{rel_path}: File not found")
            except Exception as e:
                errors.append(f"{rel_path}: {str(e)}")
                logger.error(f"Failed to delete {rel_path}: {e}")
    
    return {"deleted": deleted, "errors": errors}

def auto_sort_files():
    """Automatically sort files into folders by type"""
    # Define file type categories
    file_types = {
        "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico"],
        "Documents": [".pdf", ".doc", ".docx", ".txt", ".odt", ".rtf", ".tex"],
        "Spreadsheets": [".xls", ".xlsx", ".csv", ".ods"],
        "Presentations": [".ppt", ".pptx", ".odp"],
        "Videos": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"],
        "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"],
        "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
        "Code": [".py", ".js", ".html", ".css", ".java", ".cpp", ".c", ".h", ".go", ".rs"],
        "Other": []
    }
    
    with maintenance_lock:
        logger.info("Starting auto-sort")
        moved_files = []
        errors = []
        
        # Get all files in BASE_DIR (not in subdirectories)
        try:
            items = os.listdir(BASE_DIR)
        except Exception as e:
            logger.error(f"Cannot read directory: {e}")
            return {"moved": [], "errors": [f"Cannot read directory: {str(e)}"]}
        
        for item in items:
            full_path = os.path.join(BASE_DIR, item)
            
            # Skip directories
            if os.path.isdir(full_path):
                continue
            
            # Determine file category
            _, ext = os.path.splitext(item)
            ext = ext.lower()
            
            category = "Other"
            for cat, extensions in file_types.items():
                if ext in extensions:
                    category = cat
                    break
            
            # Create category folder if it doesn't exist
            category_folder = os.path.join(BASE_DIR, category)
            if not os.path.exists(category_folder):
                try:
                    os.makedirs(category_folder)
                except Exception as e:
                    errors.append(f"Cannot create folder {category}: {str(e)}")
                    logger.error(f"Cannot create category folder {category}: {e}")
                    continue
            
            # Move file to category folder with atomic operation
            dest_path = os.path.join(category_folder, item)
            
            # Handle duplicates
            if os.path.exists(dest_path):
                base_name, ext = os.path.splitext(item)
                counter = 1
                while os.path.exists(dest_path):
                    new_name = f"{base_name}_{counter}{ext}"
                    dest_path = os.path.join(category_folder, new_name)
                    counter += 1
            
            try:
                shutil.move(full_path, dest_path)
                moved_files.append(f"{item} → {category}/")
                logger.info(f"Sorted {item} to {category}/")
            except Exception as e:
                errors.append(f"Cannot move {item}: {str(e)}")
                logger.error(f"Failed to move {item}: {e}")
        
        logger.info(f"Auto-sort complete: {len(moved_files)} files moved")
        return {"moved": moved_files, "errors": errors}

# ============================================================================
# SECURE SYSTEM OPERATIONS - No Password Required
# ============================================================================

def check_polkit_configured():
    """Check if polkit rules are properly configured"""
    polkit_file = "/etc/polkit-1/rules.d/90-homedrive.rules"
    
    # Try to check the actual file
    try:
        if os.path.exists(polkit_file):
            return True
    except (OSError, PermissionError):
        # Can't access /etc, check config file marker instead
        pass
    
    # Fallback: check if config has polkit marker
    try:
        from config import load_config
        cfg = load_config()
        return cfg.get('polkit_configured', False) if cfg else False
    except:
        return False

def system_reboot():
    """Reboot the system using configured command"""
    logger.info("Reboot requested")
    
    if not check_polkit_configured():
        logger.warning("Polkit not configured - reboot unavailable")
        return {
            "success": False, 
            "message": "System operations not available. Polkit is not configured."
        }
    
    try:
        from config import load_config
        cfg = load_config()
        reboot_cmd = cfg.get('system_commands', {}).get('reboot', 'systemctl reboot')
        
        cmd_parts = reboot_cmd.split()
        
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            logger.info("Reboot initiated successfully")
            return {"success": True, "message": "System rebooting..."}
        else:
            logger.error(f"Reboot failed: {result.stderr}")
            return {"success": False, "message": f"Reboot failed: {result.stderr}"}
            
    except subprocess.TimeoutExpired:
        logger.info("Reboot command timed out (system may be rebooting)")
        return {"success": True, "message": "System rebooting..."}
    except Exception as e:
        logger.exception("Reboot failed with exception")
        return {"success": False, "message": f"Error: {str(e)}"}

def system_update():
    """Update the system using configured command"""
    logger.info("System update requested")
    
    if not check_polkit_configured():
        logger.warning("Polkit not configured - update unavailable")
        return {
            "success": False,
            "message": "System operations not available. Polkit is not configured."
        }
    
    try:
        from config import load_config
        cfg = load_config()
        update_cmd = cfg.get('system_commands', {}).get('update', '')
        
        if not update_cmd or 'No package manager detected' in update_cmd:
            return {
                "success": False,
                "message": "Update command not configured."
            }
        
        cmd_parts = update_cmd.split()
        
        logger.info(f"Running update command: {update_cmd}")
        
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result.returncode == 0:
            logger.info("System update completed successfully")
            return {
                "success": True, 
                "message": "System update completed", 
                "output": result.stdout[:1000]
            }
        else:
            logger.error(f"Update failed: {result.stderr}")
            return {"success": False, "message": f"Update failed: {result.stderr[:500]}"}
            
    except subprocess.TimeoutExpired:
        logger.error("Update timed out after 10 minutes")
        return {"success": False, "message": "Update timed out after 10 minutes"}
    except Exception as e:
        logger.exception("Update failed with exception")
        return {"success": False, "message": f"Error: {str(e)}"}

def system_shutdown():
    """Shutdown the system using configured command"""
    logger.info("Shutdown requested")
    
    if not check_polkit_configured():
        logger.warning("Polkit not configured - shutdown unavailable")
        return {
            "success": False, 
            "message": "System operations not available. Polkit is not configured."
        }
    
    try:
        from config import load_config
        cfg = load_config()
        shutdown_cmd = cfg.get('system_commands', {}).get('shutdown', 'systemctl poweroff')
        
        cmd_parts = shutdown_cmd.split()
        
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            logger.info("Shutdown initiated successfully")
            return {"success": True, "message": "System shutting down..."}
        else:
            logger.error(f"Shutdown failed: {result.stderr}")
            return {"success": False, "message": f"Shutdown failed: {result.stderr}"}
            
    except subprocess.TimeoutExpired:
        logger.info("Shutdown command timed out (system may be shutting down)")
        return {"success": True, "message": "System shutting down..."}
    except Exception as e:
        logger.exception("Shutdown failed with exception")
        return {"success": False, "message": f"Error: {str(e)}"}
