let currentPath = '';
let currentRenameItem = null;
let currentMoveItem = null;
let systemCommandAction = null;
let duplicatesData = [];
let contextMenuPath = '';
let selectedFile = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    loadFiles('');
    updateDiskUsage();
    setInterval(updateDiskUsage, 30000);
    
    // Close context menu on click outside
    document.addEventListener('click', function() {
        document.getElementById('contextMenu').classList.remove('show');
    });
});

// Navigate to a path
function navigateTo(path) {
    currentPath = path;
    loadFiles(path);
    updateBreadcrumb(path);
}

// Update breadcrumb
function updateBreadcrumb(path) {
    const breadcrumbPath = document.getElementById('breadcrumb-path');
    if (!path) {
        breadcrumbPath.innerHTML = '';
        return;
    }
    
    const parts = path.split('/');
    let html = '';
    let currentSegment = '';
    
    parts.forEach((part, index) => {
        currentSegment += (currentSegment ? '/' : '') + part;
        html += ' / <a href="#" onclick="navigateTo(\'' + currentSegment + '\'); return false;">' + part + '</a>';
    });
    
    breadcrumbPath.innerHTML = html;
}

// Load files for current path
function loadFiles(path) {
    showLoading();
    
    fetch('/api/files?path=' + encodeURIComponent(path))
        .then(response => response.json())
        .then(data => {
            displayFiles(data);
        })
        .catch(error => {
            showError('Failed to load files');
        });
}

// Display files in grid format with icons
function displayFiles(data) {
    const fileGrid = document.getElementById('file-list');
    
    if (data.folders.length === 0 && data.files.length === 0) {
        fileGrid.innerHTML = '<div class="empty-message">Empty folder</div>';
        return;
    }
    
    let html = '';
    
    // Folders
    data.folders.forEach(folder => {
        html += `
            <div class="file-item" 
                 ondblclick="navigateTo('${folder.path}')"
                 oncontextmenu="showContextMenu(event, '${folder.path}', true); return false;"
                 onclick="selectFile(this)">
                <div class="file-icon">📁</div>
                <div class="file-name">${escapeHtml(folder.name)}</div>
            </div>
        `;
    });
    
    // Files
    data.files.forEach(file => {
        const icon = getFileIcon(file.name);
        html += `
            <div class="file-item" 
                 ondblclick="viewFile('${file.path}')"
                 oncontextmenu="showContextMenu(event, '${file.path}', false); return false;"
                 onclick="selectFile(this)">
                <div class="file-icon">${icon}</div>
                <div class="file-name">${escapeHtml(file.name)}</div>
            </div>
        `;
    });
    
    fileGrid.innerHTML = html;
}

// Get file icon based on extension
function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    
    const icons = {
        'jpg': '🖼️', 'jpeg': '🖼️', 'png': '🖼️', 'gif': '🖼️', 'bmp': '🖼️', 'svg': '🖼️', 'webp': '🖼️',
        'pdf': '📄', 'doc': '📄', 'docx': '📄', 'txt': '📄', 'md': '📄',
        'xls': '📊', 'xlsx': '📊', 'csv': '📊',
        'py': '📝', 'js': '📝', 'html': '📝', 'css': '📝', 'json': '📝',
        'zip': '📦', 'rar': '📦', '7z': '📦', 'tar': '📦', 'gz': '📦',
        'mp4': '🎬', 'avi': '🎬', 'mkv': '🎬', 'mov': '🎬',
        'mp3': '🎵', 'wav': '🎵', 'flac': '🎵',
    };
    
    return icons[ext] || '📄';
}

// Select file
function selectFile(element) {
    document.querySelectorAll('.file-item').forEach(item => {
        item.classList.remove('selected');
    });
    element.classList.add('selected');
}

// Show context menu
function showContextMenu(event, path, isFolder) {
    event.preventDefault();
    const menu = document.getElementById('contextMenu');
    contextMenuPath = path;
    selectedFile = path;
    
    // Show/hide "Open" option based on item type
    const menuItems = menu.querySelectorAll('.context-menu-item');
    const openItem = menuItems[0]; // First item is always "Open"
    if (isFolder) {
        openItem.style.display = 'none';
    } else {
        openItem.style.display = 'block';
    }
    
    menu.style.left = event.pageX + 'px';
    menu.style.top = event.pageY + 'px';
    menu.classList.add('show');
}

// Context menu actions
function openFile() {
    viewFile(contextMenuPath);
}

function showRenameModalFromContext() {
    const name = contextMenuPath.split('/').pop();
    showRenameModal(contextMenuPath, name);
}

function showMoveModalFromContext() {
    showMoveModal(contextMenuPath);
}

function deleteItemFromContext() {
    deleteItem(contextMenuPath);
}

// View file in viewer
function viewFile(path) {
    const filename = path.split('/').pop();
    const ext = filename.split('.').pop().toLowerCase();
    
    document.getElementById('viewerTitle').textContent = filename;
    const content = document.getElementById('viewerContent');
    
    const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp'];
    const videoExts = ['mp4', 'webm', 'ogg', 'avi', 'mkv', 'mov'];
    const audioExts = ['mp3', 'wav', 'ogg', 'flac'];
    const textExts = ['txt', 'md', 'json', 'js', 'py', 'html', 'css', 'xml', 'log', 'csv'];
    
    const url = '/api/download?path=' + encodeURIComponent(path);
    
    if (imageExts.includes(ext)) {
        content.innerHTML = `<img src="${url}" alt="${filename}">`;
    } else if (videoExts.includes(ext)) {
        content.innerHTML = `<video controls><source src="${url}"></video>`;
    } else if (audioExts.includes(ext)) {
        content.innerHTML = `<audio controls><source src="${url}"></audio>`;
    } else if (ext === 'pdf') {
        content.innerHTML = `<iframe src="${url}"></iframe>`;
    } else if (textExts.includes(ext)) {
        fetch(url)
            .then(response => response.text())
            .then(text => {
                content.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
            })
            .catch(error => {
                content.innerHTML = `<p>Error loading file</p>`;
            });
    } else {
        content.innerHTML = `<p>Cannot preview this file type. <button onclick="downloadFile('${path}')" class="btn">Download</button></p>`;
    }
    
    document.getElementById('fileViewer').classList.add('show');
}

function closeViewer() {
    document.getElementById('fileViewer').classList.remove('show');
    document.getElementById('viewerContent').innerHTML = '';
}

// File operations
function showNewFolderModal() {
    document.getElementById('newFolderName').value = '';
    showModal('newFolderModal');
}

function createFolder() {
    const name = document.getElementById('newFolderName').value.trim();
    if (!name) {
        alert('Please enter a folder name');
        return;
    }
    
    fetch('/api/folder/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: currentPath, name: name})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            closeModal('newFolderModal');
            loadFiles(currentPath);
        } else {
            alert('Error: ' + data.error);
        }
    })
    .catch(error => {
        alert('Failed to create folder');
    });
}

function uploadFiles(files) {
    if (files.length === 0) return;
    
    const formData = new FormData();
    formData.append('path', currentPath);
    
    let totalSize = 0;
    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
        totalSize += files[i].size;
    }
    
    showProgressModal('Uploading files...');
    document.getElementById('progressDetails').textContent = `0 / ${files.length} files`;
    document.getElementById('progressSpeed').textContent = '0 KB/s';
    
    const startTime = Date.now();
    let lastLoaded = 0;
    let lastTime = startTime;
    
    const xhr = new XMLHttpRequest();
    
    xhr.upload.addEventListener('progress', function(e) {
        if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            const currentTime = Date.now();
            const timeDiff = (currentTime - lastTime) / 1000;
            const loadedDiff = e.loaded - lastLoaded;
            
            if (timeDiff > 0.5) {
                const speed = loadedDiff / timeDiff;
                lastLoaded = e.loaded;
                lastTime = currentTime;
                
                document.getElementById('progressPercent').textContent = percent + '%';
                document.getElementById('progressSpeed').textContent = formatSpeed(speed);
            }
            
            const filesUploaded = Math.floor((e.loaded / e.total) * files.length);
            document.getElementById('progressDetails').textContent = 
                `${filesUploaded} / ${files.length} files (${formatFileSize(e.loaded)} / ${formatFileSize(e.total)})`;
        }
    });
    
    xhr.addEventListener('load', function() {
        if (xhr.status === 200) {
            const response = JSON.parse(xhr.responseText);
            closeModal('progressModal');
            if (response.success) {
                loadFiles(currentPath);
                updateDiskUsage();
            } else {
                alert('Upload failed: ' + response.error);
            }
        } else {
            closeModal('progressModal');
            alert('Upload failed');
        }
    });
    
    xhr.addEventListener('error', function() {
        closeModal('progressModal');
        alert('Upload failed');
    });
    
    xhr.open('POST', '/api/upload');
    xhr.send(formData);
}

function formatSpeed(bytesPerSecond) {
    if (bytesPerSecond < 1024) return bytesPerSecond.toFixed(0) + ' B/s';
    if (bytesPerSecond < 1024 * 1024) return (bytesPerSecond / 1024).toFixed(1) + ' KB/s';
    if (bytesPerSecond < 1024 * 1024 * 1024) return (bytesPerSecond / (1024 * 1024)).toFixed(1) + ' MB/s';
    return (bytesPerSecond / (1024 * 1024 * 1024)).toFixed(1) + ' GB/s';
}

function downloadFile(path) {
    window.location.href = '/api/download?path=' + encodeURIComponent(path);
}

function showRenameModal(path, currentName) {
    currentRenameItem = path;
    document.getElementById('renameInput').value = currentName;
    showModal('renameModal');
}

function performRename() {
    const newName = document.getElementById('renameInput').value.trim();
    if (!newName) {
        alert('Please enter a name');
        return;
    }
    
    fetch('/api/rename', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: currentRenameItem, new_name: newName})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            closeModal('renameModal');
            loadFiles(currentPath);
        } else {
            alert('Error: ' + data.error);
        }
    })
    .catch(error => {
        alert('Failed to rename');
    });
}

function showMoveModal(path) {
    currentMoveItem = path;
    loadFolderTree();
    showModal('moveModal');
}

function loadFolderTree() {
    fetch('/api/folders')
        .then(response => response.json())
        .then(data => {
            displayFolderTree(data.folders);
        })
        .catch(error => {
            alert('Failed to load folders');
        });
}

function displayFolderTree(folders) {
    const tree = document.getElementById('folderTree');
    let html = '<div class="folder-item selected" onclick="selectFolder(\'\', this)">Home</div>';
    
    folders.forEach(folder => {
        html += `<div class="folder-item" onclick="selectFolder('${folder}', this)">${escapeHtml(folder)}</div>`;
    });
    
    tree.innerHTML = html;
}

let selectedFolder = '';

function selectFolder(path, element) {
    document.querySelectorAll('.folder-item').forEach(item => {
        item.classList.remove('selected');
    });
    element.classList.add('selected');
    selectedFolder = path;
}

function performMove() {
    fetch('/api/move', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: currentMoveItem, destination: selectedFolder})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            closeModal('moveModal');
            loadFiles(currentPath);
        } else {
            alert('Error: ' + data.error);
        }
    })
    .catch(error => {
        alert('Failed to move');
    });
}

function deleteItem(path) {
    if (!confirm('Delete this item?')) {
        return;
    }
    
    fetch('/api/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: path})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            loadFiles(currentPath);
        } else {
            alert('Error: ' + data.error);
        }
    })
    .catch(error => {
        alert('Failed to delete');
    });
}

// Maintenance functions
function showDuplicates() {
    showProgressModal('Scanning for duplicates...');
    
    fetch('/api/maintenance/duplicates')
        .then(response => response.json())
        .then(data => {
            closeModal('progressModal');
            if (data.duplicates.length === 0) {
                alert('No duplicates found');
            } else {
                alert(`Found ${data.duplicates.length} duplicate groups. Check the "_duplicates" folder in your storage.`);
                loadFiles(currentPath);
            }
        })
        .catch(error => {
            closeModal('progressModal');
            alert('Failed to scan for duplicates');
        });
}

function autoSort() {
    if (!confirm('Sort all files in root directory by type?')) {
        return;
    }
    
    showProgressModal('Sorting files...');
    
    fetch('/api/maintenance/auto-sort', {method: 'POST'})
        .then(response => response.json())
        .then(data => {
            closeModal('progressModal');
            alert(`Sorted ${data.moved.length} files`);
            loadFiles(currentPath);
        })
        .catch(error => {
            closeModal('progressModal');
            alert('Failed to sort files');
        });
}

function showRebootModal() {
    systemCommandAction = 'reboot';
    document.getElementById('systemCommandTitle').textContent = 'Reboot System';
    document.getElementById('systemCommandMessage').textContent = 'Enter sudo password:';
    document.getElementById('systemCommandBtn').textContent = 'Reboot';
    document.getElementById('sudoPassword').value = '';
    showModal('systemCommandModal');
}

function showUpdateModal() {
    systemCommandAction = 'update';
    document.getElementById('systemCommandTitle').textContent = 'Update System';
    document.getElementById('systemCommandMessage').textContent = 'Enter sudo password:';
    document.getElementById('systemCommandBtn').textContent = 'Update';
    document.getElementById('sudoPassword').value = '';
    showModal('systemCommandModal');
}

function executeSystemCommand() {
    const password = document.getElementById('sudoPassword').value;
    if (!password) {
        alert('Please enter sudo password');
        return;
    }
    
    closeModal('systemCommandModal');
    showProgressModal(`Executing ${systemCommandAction}...`);
    
    fetch('/api/maintenance/' + systemCommandAction, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sudo_password: password})
    })
    .then(response => response.json())
    .then(data => {
        closeModal('progressModal');
        alert(data.message);
    })
    .catch(error => {
        closeModal('progressModal');
        alert('Failed to execute command');
    });
}

// Modal functions
function showModal(modalId) {
    document.getElementById(modalId).classList.add('show');
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('show');
}

function showProgressModal(message) {
    document.getElementById('progressTitle').textContent = message;
    document.getElementById('progressPercent').textContent = '0%';
    document.getElementById('progressDetails').textContent = '';
    document.getElementById('progressSpeed').textContent = '';
    showModal('progressModal');
}

function showLoading() {
    document.getElementById('file-list').innerHTML = '<div class="loading"><div class="loading-spinner"></div>Loading...</div>';
}

function showError(message) {
    document.getElementById('file-list').innerHTML = `<div class="empty-message">${message}</div>`;
}

// Update disk usage display
function updateDiskUsage() {
    fetch('/api/disk-usage')
        .then(response => response.json())
        .then(data => {
            const used = formatFileSize(data.used);
            const total = formatFileSize(data.total);
            const percent = data.percent.toFixed(1);
            
            document.getElementById('storage-text').textContent = `${used} / ${total} (${percent}%)`;
            document.getElementById('storage-fill').style.width = percent + '%';
        })
        .catch(error => {
            console.error('Failed to fetch disk usage');
        });
}

// Utility functions
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Close modals when clicking outside
window.onclick = function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.classList.remove('show');
    }
}
