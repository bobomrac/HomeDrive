import os
import hashlib
import shutil
import subprocess
from pathlib import Path
from collections import defaultdict
from config import BASE_DIR
from file_ops import is_safe_path, get_full_path

def hash_file(filepath):
    """Generate SHA256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def find_duplicates():
    """Find duplicate files and copy them to _duplicates folder"""
    file_hashes = defaultdict(list)
    
    # Walk through all files
    for root, dirs, files in os.walk(BASE_DIR):
        # Skip _duplicates folder itself
        if '_duplicates' in root:
            continue
        for filename in files:
            filepath = os.path.join(root, filename)
            try:
                file_size = os.path.getsize(filepath)
                file_hash = hash_file(filepath)
                
                rel_path = os.path.relpath(filepath, BASE_DIR)
                
                file_hashes[file_hash].append({
                    "path": rel_path,
                    "size": file_size,
                    "full_path": filepath
                })
            except (IOError, OSError):
                continue
    
    # Filter to only duplicates
    duplicates = {k: v for k, v in file_hashes.items() if len(v) > 1}
    
    if not duplicates:
        return {"count": 0, "duplicates": []}
    
    # Create _duplicates folder
    dupes_folder = os.path.join(BASE_DIR, "_duplicates")
    if os.path.exists(dupes_folder):
        shutil.rmtree(dupes_folder)
    os.makedirs(dupes_folder)
    
    # Copy duplicates to folder, organized by hash
    for file_hash, files in duplicates.items():
        # Create subfolder for this duplicate group
        hash_folder = os.path.join(dupes_folder, file_hash[:8])
        os.makedirs(hash_folder)
        
        # Copy all duplicate files
        for idx, file_info in enumerate(files):
            src = file_info['full_path']
            # Preserve original path structure in filename
            safe_path = file_info['path'].replace('/', '_').replace('\\', '_')
            dst = os.path.join(hash_folder, f"{idx}_{safe_path}")
            try:
                shutil.copy2(src, dst)
            except Exception as e:
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
    
    return {"count": len(result), "duplicates": result}

def delete_duplicate_files(file_paths):
    """Delete specified duplicate files"""
    deleted = []
    errors = []
    
    for rel_path in file_paths:
        try:
            if not is_safe_path(rel_path):
                errors.append(f"{rel_path}: Invalid path")
                continue
            
            full_path = get_full_path(rel_path)
            if os.path.exists(full_path):
                os.remove(full_path)
                deleted.append(rel_path)
            else:
                errors.append(f"{rel_path}: File not found")
        except Exception as e:
            errors.append(f"{rel_path}: {str(e)}")
    
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
    
    moved_files = []
    errors = []
    
    # Get all files in BASE_DIR (not in subdirectories)
    try:
        items = os.listdir(BASE_DIR)
    except Exception as e:
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
                continue
        
        # Move file to category folder
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
        except Exception as e:
            errors.append(f"Cannot move {item}: {str(e)}")
    
    return {"moved": moved_files, "errors": errors}

def system_reboot(sudo_password):
    """Reboot the system"""
    try:
        # Use subprocess with stdin to avoid exposing password in process list
        process = subprocess.Popen(
            ['sudo', '-S', 'reboot'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=sudo_password + '\n', timeout=5)
        
        if process.returncode == 0:
            return {"success": True, "message": "Reboot initiated"}
        else:
            # Check if it's a password error
            if "password" in stderr.lower() or "sorry" in stderr.lower():
                return {"success": False, "message": "Invalid sudo password"}
            return {"success": False, "message": f"Failed to reboot: {stderr}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Command timed out"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

def system_update(sudo_password):
    """Update the system"""
    try:
        # Detect the distro and use appropriate command
        update_cmd = None
        
        if os.path.exists("/usr/bin/rpm-ostree"):
            update_cmd = ['sudo', '-S', 'rpm-ostree', 'upgrade']
        elif os.path.exists("/usr/bin/transactional-update"):
            update_cmd = ['sudo', '-S', 'transactional-update']
        elif os.path.exists("/usr/bin/abroot"):
            update_cmd = ['sudo', '-S', 'abroot', 'upgrade']
        elif os.path.exists("/usr/bin/apt"):
            update_cmd = ['sudo', '-S', 'sh', '-c', 'apt update && apt upgrade -y']
        elif os.path.exists("/usr/bin/dnf"):
            update_cmd = ['sudo', '-S', 'dnf', 'upgrade', '-y']
        elif os.path.exists("/usr/bin/pacman"):
            update_cmd = ['sudo', '-S', 'pacman', '-Syu', '--noconfirm']
        else:
            return {"success": False, "message": "Could not detect system package manager"}
        
        process = subprocess.Popen(
            update_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(input=sudo_password + '\n', timeout=300)
        
        if process.returncode == 0:
            return {"success": True, "message": "System update completed", "output": stdout}
        else:
            if "password" in stderr.lower() or "sorry" in stderr.lower():
                return {"success": False, "message": "Invalid sudo password"}
            return {"success": False, "message": f"Update failed: {stderr}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Update timed out after 5 minutes"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}
