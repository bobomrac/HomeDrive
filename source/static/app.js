let currentPath = '';
let currentRenameItem = null;
let currentMoveItem = null;
let duplicatesData = [];
let contextMenuPath = '';
let selectedFile = null;
let csrfToken = '';
let selectedFiles = new Set();  // Track multiple selected files

// Drag selection state
let isDragging = false;
let dragStartX = 0;
let dragStartY = 0;
let selectionBox = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Get CSRF token from meta tag or cookie
    const tokenElement = document.querySelector('meta[name="csrf-token"]');
    if (tokenElement) {
        csrfToken = tokenElement.content;
    }
    
    loadFiles('');
    loadFavorites();
    updateDiskUsage();
    updateTrashBadge();
    setInterval(updateDiskUsage, 30000);
    setInterval(updateTrashBadge, 60000); // Update trash badge every minute

    // Check polkit configuration status
    checkPolkitStatus();
    
    // Close context menu on click outside
    document.addEventListener('click', function(e) {
        document.getElementById('contextMenu').classList.remove('show');

        // Close upload dropdown on click outside
        const dropdown = document.getElementById('upload-dropdown');
        if (dropdown && !e.target.closest('#upload-dropdown') && !e.target.closest('button[onclick*="toggleUploadDropdown"]')) {
            dropdown.style.display = 'none';
        }
    });
    
    // Setup drag selection
    setupDragSelection();

    // Setup drag and drop upload
    setupDragDropUpload();

    // Setup internal drag and drop
    setupInternalDragDrop();
});

// API helper with CSRF token and better error handling
async function apiRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        }
    };
    
    // Add CSRF token to all non-GET requests
    if (options.method && options.method !== 'GET') {
        if (options.body && typeof options.body === 'string') {
            try {
                const bodyData = JSON.parse(options.body);
                bodyData.csrf_token = csrfToken;
                options.body = JSON.stringify(bodyData);
            } catch (e) {
                console.error('Failed to add CSRF token to body:', e);
            }
        } else if (!options.body) {
            options.body = JSON.stringify({ csrf_token: csrfToken });
        }
    }
    
    const mergedOptions = { ...defaultOptions, ...options };
    
    try {
        const response = await fetch(url, mergedOptions);
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API Request failed:', url, error);
        throw error;
    }
}

// Navigate to a path
function navigateTo(path) {
    currentPath = path;
    selectedFiles.clear();  // Clear selection when changing folders
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
        html += ' / <a href="#" onclick="navigateTo(\'' + escapeHtml(currentSegment) + '\'); return false;">' + escapeHtml(part) + '</a>';
    });
    
    breadcrumbPath.innerHTML = html;
}

// Load files for current path
async function loadFiles(path) {
    showLoading();

    try {
        const data = await apiRequest('/api/files?path=' + encodeURIComponent(path));
        displayFiles(data);
        updateFavoriteStars(); // Update star icons based on favorites
    } catch (error) {
        showError('Failed to load files: ' + error.message);
    }
}

// Display files in grid format with icons and thumbnails
function displayFiles(data) {
    const fileGrid = document.getElementById('file-list');
    
    if (data.folders.length === 0 && data.files.length === 0) {
        fileGrid.innerHTML = '<div class="empty-message">Empty folder<br><small style="color: #999; font-size: 11px;">Right-click for options</small></div>';
        return;
    }
    
    let html = '';
    
    // Folders
    data.folders.forEach(folder => {
        const isSelected = selectedFiles.has(folder.path);
        const isTrash = folder.name === '.trash';
        const icon = isTrash ? '🗑️' : '📁';

        html += `
            <div class="file-item ${isSelected ? 'selected' : ''}"
                 data-path="${escapeHtml(folder.path)}"
                 data-is-folder="true"
                 draggable="true"
                 ondblclick="navigateTo('${escapeHtml(folder.path)}')"
                 oncontextmenu="showContextMenu(event, '${escapeHtml(folder.path)}', true); return false;"
                 onclick="handleFileClick(event, '${escapeHtml(folder.path)}', this)">
                <div class="file-icon">${icon}</div>
                <div class="file-name">${escapeHtml(folder.name)}</div>
                ${!isTrash ? '<div class="favorite-star" onclick="toggleFavorite(\'' + escapeHtml(folder.path) + '\', event)">☆</div>' : ''}
                <div class="selection-indicator">✓</div>
            </div>
        `;
    });
    
    // Files
    data.files.forEach(file => {
        const icon = getFileIcon(file.name);
        const ext = file.name.split('.').pop().toLowerCase();
        const isImage = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'].includes(ext);
        const isSelected = selectedFiles.has(file.path);
        
        // Use thumbnail for images
        let iconHtml;
        if (isImage) {
            const thumbUrl = '/api/thumbnail?path=' + encodeURIComponent(file.path) + '&size=100';
            iconHtml = `<div class="file-icon thumbnail"><img src="${thumbUrl}" alt="${escapeHtml(file.name)}" onerror="this.parentElement.innerHTML='${icon}'"></div>`;
        } else {
            iconHtml = `<div class="file-icon">${icon}</div>`;
        }
        
        html += `
            <div class="file-item ${isSelected ? 'selected' : ''}"
                 data-path="${escapeHtml(file.path)}"
                 data-is-folder="false"
                 draggable="true"
                 ondblclick="viewFile('${escapeHtml(file.path)}')"
                 oncontextmenu="showContextMenu(event, '${escapeHtml(file.path)}', false); return false;"
                 onclick="handleFileClick(event, '${escapeHtml(file.path)}', this)">
                ${iconHtml}
                <div class="file-name">${escapeHtml(file.name)}</div>
                <div class="selection-indicator">✓</div>
            </div>
        `;
    });
    
    fileGrid.innerHTML = html;
    
    // Show hint if nothing selected
    if (selectedFiles.size === 0) {
        showContextHint();
    }
}

// Show hint about right-click functionality
function showContextHint() {
    const hint = document.createElement('div');
    hint.className = 'context-hint';
    hint.innerHTML = '💡 Tip: Right-click files for options';
    hint.style.cssText = 'position: fixed; bottom: 20px; right: 20px; background: #3a3a3a; color: #fff; padding: 10px 15px; border-radius: 4px; font-size: 12px; z-index: 999; animation: fadeIn 0.3s;';
    document.body.appendChild(hint);
    
    setTimeout(() => {
        hint.style.animation = 'fadeOut 0.3s';
        setTimeout(() => hint.remove(), 300);
    }, 4000);
}

// Handle file click with multi-select support
function handleFileClick(event, path, element) {
    if (event.ctrlKey || event.metaKey) {
        // Toggle selection
        if (selectedFiles.has(path)) {
            selectedFiles.delete(path);
            element.classList.remove('selected');
        } else {
            selectedFiles.add(path);
            element.classList.add('selected');
        }
    } else if (event.shiftKey && selectedFiles.size > 0) {
        // Range select
        const allItems = Array.from(document.querySelectorAll('.file-item'));
        const lastSelected = Array.from(selectedFiles)[selectedFiles.size - 1];
        const lastElement = document.querySelector(`[data-path="${lastSelected}"]`);
        
        if (lastElement) {
            const start = allItems.indexOf(lastElement);
            const end = allItems.indexOf(element);
            const [min, max] = [Math.min(start, end), Math.max(start, end)];
            
            for (let i = min; i <= max; i++) {
                const item = allItems[i];
                const itemPath = item.getAttribute('data-path');
                selectedFiles.add(itemPath);
                item.classList.add('selected');
            }
        }
    } else {
        // Single select
        selectedFiles.clear();
        document.querySelectorAll('.file-item').forEach(item => {
            item.classList.remove('selected');
        });
        selectedFiles.add(path);
        element.classList.add('selected');
    }
    
    updateSelectionInfo();
}

// Update selection info display
function updateSelectionInfo() {
    let info = document.getElementById('selection-info');
    if (!info) {
        info = document.createElement('div');
        info.id = 'selection-info';
        info.style.cssText = 'position: fixed; bottom: 20px; left: 20px; background: #2b2b2b; border: 1px solid #4a4a4a; color: #e0e0e0; padding: 8px 12px; border-radius: 4px; font-size: 12px; z-index: 999;';
        document.body.appendChild(info);
    }
    
    if (selectedFiles.size > 0) {
        info.textContent = `${selectedFiles.size} selected`;
        info.style.display = 'block';
    } else {
        info.style.display = 'none';
    }
}
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

// Show context menu with proper positioning
function showContextMenu(event, path, isFolder) {
    event.preventDefault();
    const menu = document.getElementById('contextMenu');
    contextMenuPath = path;
    
    // If right-clicked item isn't selected, select only it
    if (!selectedFiles.has(path)) {
        selectedFiles.clear();
        selectedFiles.add(path);
        document.querySelectorAll('.file-item').forEach(item => {
            item.classList.remove('selected');
        });
        const clickedItem = document.querySelector(`[data-path="${path}"]`);
        if (clickedItem) clickedItem.classList.add('selected');
    }
    
    // Update menu based on selection
    const menuItems = menu.querySelectorAll('.context-menu-item');
    const openItem = menuItems[0];
    const downloadItem = menuItems[1];
    const renameItem = menuItems[2];
    const moveItem = menuItems[3];
    const deleteItem = menuItems[4];

    const multiSelect = selectedFiles.size > 1;

    // Check if we're in .trash folder
    const inTrash = path.startsWith('.trash/') || currentPath.startsWith('.trash');

    if (inTrash) {
        // In trash - show Restore instead of Delete
        openItem.style.display = 'none';
        downloadItem.style.display = multiSelect ? 'none' : 'block';
        renameItem.style.display = 'none';
        moveItem.style.display = 'none';
        deleteItem.textContent = multiSelect ? `Restore ${selectedFiles.size} items` : 'Restore';
        deleteItem.classList.remove('danger');
        deleteItem.onclick = () => restoreFromTrash();
    } else {
        // Normal context menu
        openItem.style.display = (multiSelect || isFolder) ? 'none' : 'block';
        downloadItem.style.display = multiSelect ? 'none' : 'block';
        renameItem.style.display = multiSelect ? 'none' : 'block';
        moveItem.style.display = 'block';

        if (multiSelect) {
            moveItem.textContent = `Move ${selectedFiles.size} items`;
            deleteItem.textContent = `Delete ${selectedFiles.size} items`;
        } else {
            moveItem.textContent = 'Move';
            deleteItem.textContent = 'Delete';
        }
        deleteItem.classList.add('danger');
        deleteItem.onclick = () => deleteItemFromContext();
    }

    // Add/remove ZIP download option for folders
    let zipSeparator = menu.querySelector('.zip-separator');
    let zipItem = menu.querySelector('.zip-download-item');

    if (isFolder && !multiSelect && !inTrash) {
        // Add ZIP option if not already there
        if (!zipSeparator) {
            zipSeparator = document.createElement('div');
            zipSeparator.className = 'context-menu-separator zip-separator';
            menu.appendChild(zipSeparator);

            zipItem = document.createElement('div');
            zipItem.className = 'context-menu-item zip-download-item';
            zipItem.textContent = 'Download as ZIP';
            menu.appendChild(zipItem);
        }
        zipSeparator.style.display = 'block';
        zipItem.style.display = 'block';
        zipItem.onclick = () => downloadFolderAsZip(contextMenuPath);
    } else {
        // Hide ZIP option
        if (zipSeparator) zipSeparator.style.display = 'none';
        if (zipItem) zipItem.style.display = 'none';
    }

    // Position menu with boundary checking
    menu.classList.add('show');
    const menuRect = menu.getBoundingClientRect();
    let x = event.pageX;
    let y = event.pageY;
    
    if (x + menuRect.width > window.innerWidth + window.scrollX) {
        x = window.innerWidth + window.scrollX - menuRect.width - 5;
    }
    if (y + menuRect.height > window.innerHeight + window.scrollY) {
        y = window.innerHeight + window.scrollY - menuRect.height - 5;
    }
    if (x < window.scrollX) {
        x = window.scrollX + 5;
    }
    if (y < window.scrollY) {
        y = window.scrollY + 5;
    }
    
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    
    updateSelectionInfo();
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
    if (selectedFiles.size > 1) {
        showMoveModal(Array.from(selectedFiles));
    } else {
        showMoveModal(contextMenuPath);
    }
}

async function deleteItemFromContext() {
    const count = selectedFiles.size;
    const itemText = count > 1 ? `${count} items` : 'this item';
    
    if (!confirm(`Delete ${itemText}?`)) {
        return;
    }
    
    try {
        if (count > 1) {
            await apiRequest('/api/delete', {
                method: 'POST',
                body: JSON.stringify({paths: Array.from(selectedFiles)})
            });
        } else {
            await apiRequest('/api/delete', {
                method: 'POST',
                body: JSON.stringify({path: contextMenuPath})
            });
        }
        
        selectedFiles.clear();
        loadFiles(currentPath);
    } catch (error) {
        alert('Error: ' + error.message);
    }
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
        content.innerHTML = `<img src="${url}" alt="${escapeHtml(filename)}">`;
    } else if (videoExts.includes(ext)) {
        content.innerHTML = `<video controls><source src="${url}"></video>`;
    } else if (audioExts.includes(ext)) {
        content.innerHTML = `<audio controls><source src="${url}"></audio>`;
    } else if (ext === 'pdf') {
        content.innerHTML = `<iframe src="${url}"></iframe>`;
    } else if (textExts.includes(ext)) {
        fetch(url)
            .then(response => {
                if (!response.ok) throw new Error('Failed to load file');
                return response.text();
            })
            .then(text => {
                content.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
            })
            .catch(error => {
                content.innerHTML = `<p>Error loading file: ${error.message}</p>`;
            });
    } else {
        content.innerHTML = `<p>Cannot preview this file type. <button onclick="downloadFile('${escapeHtml(path)}')" class="btn">Download</button></p>`;
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

async function createFolder() {
    const name = document.getElementById('newFolderName').value.trim();
    if (!name) {
        alert('Please enter a folder name');
        return;
    }
    
    try {
        await apiRequest('/api/folder/create', {
            method: 'POST',
            body: JSON.stringify({path: currentPath, name: name})
        });
        closeModal('newFolderModal');
        loadFiles(currentPath);
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

async function uploadFiles(files) {
    if (files.length === 0) return;
    
    const formData = new FormData();
    formData.append('path', currentPath);
    formData.append('csrf_token', csrfToken);
    
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
            document.getElementById('progressPercent').textContent = percent + '%';
            
            // Calculate speed
            const currentTime = Date.now();
            const timeDiff = (currentTime - lastTime) / 1000;
            
            if (timeDiff > 0.5) { // Update speed every 0.5 seconds
                const bytesDiff = e.loaded - lastLoaded;
                const speed = bytesDiff / timeDiff;
                document.getElementById('progressSpeed').textContent = formatFileSize(speed) + '/s';
                
                lastLoaded = e.loaded;
                lastTime = currentTime;
            }
            
            // Estimate files completed
            const filesCompleted = Math.floor((e.loaded / e.total) * files.length);
            document.getElementById('progressDetails').textContent = 
                `${filesCompleted} / ${files.length} files (${formatFileSize(e.loaded)} / ${formatFileSize(e.total)})`;
        }
    });
    
    xhr.addEventListener('load', function() {
        closeModal('progressModal');
        if (xhr.status === 200) {
            try {
                const response = JSON.parse(xhr.responseText);
                if (response.success) {
                    loadFiles(currentPath);
                } else {
                    alert('Upload failed: ' + (response.error || 'Unknown error'));
                }
            } catch (e) {
                alert('Upload failed: Invalid server response');
            }
        } else {
            alert('Upload failed: ' + xhr.statusText);
        }
    });
    
    xhr.addEventListener('error', function() {
        closeModal('progressModal');
        alert('Upload failed: Network error');
    });
    
    xhr.open('POST', '/api/upload');
    xhr.send(formData);
}

// Upload dropdown functions
function toggleUploadDropdown(event) {
    event.stopPropagation();
    const dropdown = document.getElementById('upload-dropdown');
    const isVisible = dropdown.style.display === 'block';
    dropdown.style.display = isVisible ? 'none' : 'block';
}

function triggerFileUpload() {
    document.getElementById('file-upload').click();
    document.getElementById('upload-dropdown').style.display = 'none';
}

function triggerFolderUpload() {
    document.getElementById('folder-upload').click();
    document.getElementById('upload-dropdown').style.display = 'none';
}

async function uploadFolder(files) {
    if (files.length === 0) return;

    const formData = new FormData();
    formData.append('path', currentPath);
    formData.append('csrf_token', csrfToken);

    let totalSize = 0;
    const paths = [];

    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
        // Extract relative path from webkitRelativePath
        paths.push(files[i].webkitRelativePath || files[i].name);
        totalSize += files[i].size;
    }

    // Append paths array to preserve folder structure
    paths.forEach(path => formData.append('paths', path));

    showProgressModal('Uploading folder...');
    document.getElementById('progressDetails').textContent = `0 / ${files.length} files`;
    document.getElementById('progressSpeed').textContent = '0 KB/s';

    const startTime = Date.now();
    let lastLoaded = 0;
    let lastTime = startTime;

    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', function(e) {
        if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            document.getElementById('progressPercent').textContent = percent + '%';

            // Calculate speed
            const currentTime = Date.now();
            const timeDiff = (currentTime - lastTime) / 1000;

            if (timeDiff > 0.5) {
                const bytesDiff = e.loaded - lastLoaded;
                const speed = bytesDiff / timeDiff;
                document.getElementById('progressSpeed').textContent = formatFileSize(speed) + '/s';

                lastLoaded = e.loaded;
                lastTime = currentTime;
            }

            const filesCompleted = Math.floor((e.loaded / e.total) * files.length);
            document.getElementById('progressDetails').textContent =
                `${filesCompleted} / ${files.length} files (${formatFileSize(e.loaded)} / ${formatFileSize(e.total)})`;
        }
    });

    xhr.addEventListener('load', function() {
        closeModal('progressModal');
        if (xhr.status === 200) {
            try {
                const response = JSON.parse(xhr.responseText);
                if (response.success) {
                    loadFiles(currentPath);
                } else {
                    alert('Upload failed: ' + (response.error || 'Unknown error'));
                }
            } catch (e) {
                alert('Upload failed: Invalid server response');
            }
        } else {
            alert('Upload failed: ' + xhr.statusText);
        }
    });

    xhr.addEventListener('error', function() {
        closeModal('progressModal');
        alert('Upload failed: Network error');
    });

    xhr.open('POST', '/api/upload');
    xhr.send(formData);
}

function downloadFile(path) {
    window.location.href = '/api/download?path=' + encodeURIComponent(path);
}

function showRenameModal(path, currentName) {
    currentRenameItem = path;
    document.getElementById('renameInput').value = currentName;
    showModal('renameModal');
}

async function performRename() {
    const newName = document.getElementById('renameInput').value.trim();
    if (!newName) {
        alert('Please enter a name');
        return;
    }
    
    try {
        await apiRequest('/api/rename', {
            method: 'POST',
            body: JSON.stringify({path: currentRenameItem, new_name: newName})
        });
        closeModal('renameModal');
        loadFiles(currentPath);
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

function showMoveModal(pathOrPaths) {
    if (Array.isArray(pathOrPaths)) {
        currentMoveItem = pathOrPaths;
    } else {
        currentMoveItem = pathOrPaths;
    }
    loadFolderTree();
    showModal('moveModal');
}

async function loadFolderTree() {
    try {
        const data = await apiRequest('/api/folders');
        displayFolderTree(data.folders);
    } catch (error) {
        alert('Failed to load folders: ' + error.message);
    }
}

function displayFolderTree(folders) {
    const tree = document.getElementById('folderTree');
    let html = '<div class="folder-item selected" onclick="selectFolder(\'\', this)">Home</div>';
    
    folders.forEach(folder => {
        html += `<div class="folder-item" onclick="selectFolder('${escapeHtml(folder)}', this)">${escapeHtml(folder)}</div>`;
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

async function performMove() {
    try {
        if (Array.isArray(currentMoveItem)) {
            // Bulk move
            await apiRequest('/api/move-multiple', {
                method: 'POST',
                body: JSON.stringify({sources: currentMoveItem, destination: selectedFolder})
            });
        } else {
            // Single move
            await apiRequest('/api/move', {
                method: 'POST',
                body: JSON.stringify({source: currentMoveItem, destination: selectedFolder})
            });
        }
        
        selectedFiles.clear();
        closeModal('moveModal');
        loadFiles(currentPath);
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

async function deleteItem(path) {
    if (!confirm('Delete this item?')) {
        return;
    }
    
    try {
        await apiRequest('/api/delete', {
            method: 'POST',
            body: JSON.stringify({path: path})
        });
        loadFiles(currentPath);
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// Maintenance functions
async function showDuplicates() {
    showProgressModal('Scanning for duplicates...');
    
    try {
        const data = await apiRequest('/api/maintenance/duplicates');
        closeModal('progressModal');
        
        if (data.duplicates.length === 0) {
            alert('No duplicates found');
        } else {
            alert(`Found ${data.duplicates.length} duplicate groups. Check the "_duplicates" folder in your storage.`);
            loadFiles(currentPath);
        }
    } catch (error) {
        closeModal('progressModal');
        alert('Failed to scan for duplicates: ' + error.message);
    }
}

async function autoSort() {
    if (!confirm('Sort all files in root directory by type?')) {
        return;
    }
    
    showProgressModal('Sorting files...');
    
    try {
        const data = await apiRequest('/api/maintenance/auto-sort', {method: 'POST'});
        closeModal('progressModal');
        alert(`Sorted ${data.moved.length} files`);
        loadFiles(currentPath);
    } catch (error) {
        closeModal('progressModal');
        alert('Failed to sort files: ' + error.message);
    }
}

async function showRebootConfirm() {
    if (!confirm('Reboot the system now?')) {
        return;
    }
    
    showProgressModal('Rebooting system...');
    
    try {
        const data = await apiRequest('/api/maintenance/reboot', {method: 'POST'});
        closeModal('progressModal');
        
        if (data.success) {
            alert('System is rebooting...');
        } else {
            alert('Reboot failed: ' + data.message);
        }
    } catch (error) {
        closeModal('progressModal');
        alert('Reboot failed: ' + error.message);
    }
}

async function showUpdateConfirm() {
    if (!confirm('Update system packages now? This may take several minutes.')) {
        return;
    }
    
    showProgressModal('Updating system packages...');
    
    try {
        const data = await apiRequest('/api/maintenance/update', {method: 'POST'});
        closeModal('progressModal');
        
        if (data.success) {
            const output = data.output ? '\n\nOutput:\n' + data.output : '';
            alert('System update completed!' + output);
        } else {
            alert('Update failed: ' + data.message);
        }
    } catch (error) {
        closeModal('progressModal');
        alert('Update failed: ' + error.message);
    }
}

async function checkPolkitStatus() {
    try {
        const data = await apiRequest('/api/maintenance/check-polkit');
        
        if (!data.configured) {
            console.warn('Polkit not configured:', data.message);
        }
    } catch (error) {
        console.error('Failed to check polkit status:', error);
    }
}

// Commands management
let currentCommands = {};

async function showCommands() {
    try {
        const data = await apiRequest('/api/settings/system-commands');
        currentCommands = data.commands || {};
        
        renderCommandsList();
        showModal('commandsModal');
    } catch (error) {
        alert('Failed to load commands: ' + error.message);
    }
}

function renderCommandsList() {
    const container = document.getElementById('commandsList');
    let html = '';
    
    // Only show core commands
    const coreCommands = ['reboot', 'update', 'shutdown'];
    
    for (const name of coreCommands) {
        const cmd = currentCommands[name] || '';
        
        html += `
            <div style="margin-bottom: 15px;">
                <label style="display: block; margin-bottom: 5px; color: #ccc; text-transform: capitalize;">
                    ${escapeHtml(name)}:
                </label>
                <input type="text" 
                       class="input command-input" 
                       data-command-name="${escapeHtml(name)}"
                       value="${escapeHtml(cmd)}" 
                       style="width: 100%;"
                       placeholder="Enter command">
            </div>
        `;
    }
    
    container.innerHTML = html;
}

function addCustomCommand() {
    const name = document.getElementById('newCommandName').value.trim();
    const value = document.getElementById('newCommandValue').value.trim();
    
    if (!name || !value) {
        alert('Both name and command are required');
        return;
    }
    
    // Validate name (alphanumeric, dashes, underscores only)
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
        alert('Command name can only contain letters, numbers, dashes, and underscores');
        return;
    }
    
    if (currentCommands[name]) {
        if (!confirm(`Command "${name}" already exists. Overwrite?`)) {
            return;
        }
    }
    
    currentCommands[name] = value;
    
    // Clear inputs
    document.getElementById('newCommandName').value = '';
    document.getElementById('newCommandValue').value = '';
    
    renderCommandsList();
}

async function saveCommands() {
    // Collect all command values from inputs
    document.querySelectorAll('.command-input').forEach(input => {
        const name = input.getAttribute('data-command-name');
        const value = input.value.trim();
        if (value) {
            currentCommands[name] = value;
        }
    });
    
    // Validate core commands
    const coreCommands = ['reboot', 'update', 'shutdown'];
    for (const cmd of coreCommands) {
        if (!currentCommands[cmd] || !currentCommands[cmd].trim()) {
            alert(`Core command "${cmd}" cannot be empty`);
            return;
        }
    }
    
    try {
        await apiRequest('/api/settings/system-commands', {
            method: 'POST',
            body: JSON.stringify({commands: currentCommands})
        });
        
        closeModal('commandsModal');
        alert('Commands saved successfully');
    } catch (error) {
        alert('Failed to save commands: ' + error.message);
    }
}

async function detectCommands() {
    try {
        const data = await apiRequest('/api/settings/detect-commands');
        
        // Merge detected commands with custom ones
        const coreCommands = ['reboot', 'update', 'shutdown'];
        for (const [name, value] of Object.entries(data.commands)) {
            if (coreCommands.includes(name)) {
                currentCommands[name] = value;
            }
        }
        
        renderCommandsList();
        alert('Core commands detected! Custom commands preserved.');
    } catch (error) {
        alert('Failed to detect commands: ' + error.message);
    }
}

async function showShutdownConfirm() {
    if (!confirm('Shutdown the system now?')) {
        return;
    }
    
    showProgressModal('Shutting down system...');
    
    try {
        const data = await apiRequest('/api/maintenance/shutdown', {method: 'POST'});
        closeModal('progressModal');
        
        if (data.success) {
            alert('System is shutting down...');
        } else {
            alert('Shutdown failed: ' + data.message);
        }
    } catch (error) {
        closeModal('progressModal');
        alert('Shutdown failed: ' + error.message);
    }
}

// Drag selection functionality
function setupDragSelection() {
    const fileGrid = document.getElementById('file-list');
    
    fileGrid.addEventListener('mousedown', function(e) {
        // Only start drag if clicking on the grid background, not on items
        if (e.target.id === 'file-list' || e.target.classList.contains('empty-message')) {
            isDragging = true;
            dragStartX = e.pageX;
            dragStartY = e.pageY;
            
            // Clear selection unless Ctrl is held
            if (!e.ctrlKey && !e.metaKey) {
                selectedFiles.clear();
                document.querySelectorAll('.file-item').forEach(item => {
                    item.classList.remove('selected');
                });
            }
            
            // Create selection box
            selectionBox = document.createElement('div');
            selectionBox.className = 'selection-box';
            selectionBox.style.left = dragStartX + 'px';
            selectionBox.style.top = dragStartY + 'px';
            document.body.appendChild(selectionBox);
            
            e.preventDefault();
        }
    });
    
    document.addEventListener('mousemove', function(e) {
        if (!isDragging || !selectionBox) return;
        
        const currentX = e.pageX;
        const currentY = e.pageY;
        
        // Update selection box dimensions
        const left = Math.min(dragStartX, currentX);
        const top = Math.min(dragStartY, currentY);
        const width = Math.abs(currentX - dragStartX);
        const height = Math.abs(currentY - dragStartY);
        
        selectionBox.style.left = left + 'px';
        selectionBox.style.top = top + 'px';
        selectionBox.style.width = width + 'px';
        selectionBox.style.height = height + 'px';
        
        // Check which items intersect with selection box
        const boxRect = selectionBox.getBoundingClientRect();
        document.querySelectorAll('.file-item').forEach(item => {
            const itemRect = item.getBoundingClientRect();
            
            // Check if rectangles intersect
            const intersects = !(
                boxRect.right < itemRect.left ||
                boxRect.left > itemRect.right ||
                boxRect.bottom < itemRect.top ||
                boxRect.top > itemRect.bottom
            );
            
            const path = item.getAttribute('data-path');
            if (intersects) {
                selectedFiles.add(path);
                item.classList.add('selected');
            } else if (!e.ctrlKey && !e.metaKey) {
                // Only deselect if Ctrl not held
                selectedFiles.delete(path);
                item.classList.remove('selected');
            }
        });
        
        updateSelectionInfo();
    });
    
    document.addEventListener('mouseup', function(e) {
        if (isDragging) {
            isDragging = false;
            
            // Remove selection box
            if (selectionBox) {
                selectionBox.remove();
                selectionBox = null;
            }
            
            updateSelectionInfo();
        }
    });
}

// Drag and drop upload functionality
function setupDragDropUpload() {
    const fileGrid = document.getElementById('file-list');
    let dragCounter = 0;

    // Prevent default drag behaviors on document
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // Highlight drop zone when dragging files over it
    fileGrid.addEventListener('dragenter', function(e) {
        if (e.dataTransfer.types.includes('Files')) {
            dragCounter++;
            fileGrid.classList.add('drag-over');
        }
    });

    fileGrid.addEventListener('dragover', function(e) {
        if (e.dataTransfer.types.includes('Files')) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        }
    });

    fileGrid.addEventListener('dragleave', function(e) {
        if (e.dataTransfer.types.includes('Files')) {
            dragCounter--;
            if (dragCounter === 0) {
                fileGrid.classList.remove('drag-over');
            }
        }
    });

    fileGrid.addEventListener('drop', async function(e) {
        if (e.dataTransfer.types.includes('Files')) {
            e.preventDefault();
            dragCounter = 0;
            fileGrid.classList.remove('drag-over');

            // Use DataTransferItem API to handle folders
            const items = e.dataTransfer.items;
            if (items && items.length > 0) {
                const allFiles = [];
                const promises = [];

                for (let i = 0; i < items.length; i++) {
                    const item = items[i];
                    if (item.kind === 'file') {
                        const entry = item.webkitGetAsEntry();
                        if (entry) {
                            promises.push(traverseFileTree(entry, ''));
                        }
                    }
                }

                // Wait for all file tree traversals to complete
                const results = await Promise.all(promises);
                results.forEach(files => allFiles.push(...files));

                if (allFiles.length > 0) {
                    uploadFilesWithPaths(allFiles);
                }
            } else {
                // Fallback for browsers without DataTransferItem support
                const files = e.dataTransfer.files;
                if (files.length > 0) {
                    uploadFiles(files);
                }
            }
        }
    });
}

// Recursively traverse file tree and collect files with paths
async function traverseFileTree(entry, path) {
    return new Promise((resolve, reject) => {
        if (entry.isFile) {
            entry.file(file => {
                // Attach full path to file object
                file.fullPath = path + file.name;
                resolve([file]);
            }, reject);
        } else if (entry.isDirectory) {
            const dirReader = entry.createReader();
            const allFiles = [];

            const readEntries = () => {
                dirReader.readEntries(async entries => {
                    if (entries.length === 0) {
                        resolve(allFiles);
                        return;
                    }

                    const promises = [];
                    for (let i = 0; i < entries.length; i++) {
                        const newPath = path + entry.name + '/';
                        promises.push(traverseFileTree(entries[i], newPath));
                    }

                    const results = await Promise.all(promises);
                    results.forEach(files => allFiles.push(...files));

                    // Read next batch (some browsers return entries in batches)
                    readEntries();
                }, reject);
            };

            readEntries();
        }
    });
}

// Upload files with relative paths (for folder drag & drop)
async function uploadFilesWithPaths(files) {
    if (files.length === 0) return;

    const formData = new FormData();
    formData.append('path', currentPath);
    formData.append('csrf_token', csrfToken);

    let totalSize = 0;

    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
        formData.append('paths', files[i].fullPath || files[i].name);
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
            document.getElementById('progressPercent').textContent = percent + '%';

            const currentTime = Date.now();
            const timeDiff = (currentTime - lastTime) / 1000;

            if (timeDiff > 0.5) {
                const bytesDiff = e.loaded - lastLoaded;
                const speed = bytesDiff / timeDiff;
                document.getElementById('progressSpeed').textContent = formatFileSize(speed) + '/s';

                lastLoaded = e.loaded;
                lastTime = currentTime;
            }

            const filesCompleted = Math.floor((e.loaded / e.total) * files.length);
            document.getElementById('progressDetails').textContent =
                `${filesCompleted} / ${files.length} files (${formatFileSize(e.loaded)} / ${formatFileSize(e.total)})`;
        }
    });

    xhr.addEventListener('load', function() {
        closeModal('progressModal');
        if (xhr.status === 200) {
            try {
                const response = JSON.parse(xhr.responseText);
                if (response.success) {
                    loadFiles(currentPath);
                } else {
                    alert('Upload failed: ' + (response.error || 'Unknown error'));
                }
            } catch (e) {
                alert('Upload failed: Invalid server response');
            }
        } else {
            alert('Upload failed: ' + xhr.statusText);
        }
    });

    xhr.addEventListener('error', function() {
        closeModal('progressModal');
        alert('Upload failed: Network error');
    });

    xhr.open('POST', '/api/upload');
    xhr.send(formData);
}

// Internal drag & drop for organizing files
let draggedItems = [];

function setupInternalDragDrop() {
    const fileGrid = document.getElementById('file-list');

    // Delegated drag event handlers
    fileGrid.addEventListener('dragstart', function(e) {
        const fileItem = e.target.closest('.file-item');
        if (!fileItem) return;

        const path = fileItem.getAttribute('data-path');

        // If dragged item is not selected, select only it
        if (!selectedFiles.has(path)) {
            selectedFiles.clear();
            selectedFiles.add(path);
            document.querySelectorAll('.file-item').forEach(item => {
                item.classList.remove('selected');
            });
            fileItem.classList.add('selected');
        }

        // Store dragged items
        draggedItems = Array.from(selectedFiles);

        // Set custom data type to identify internal drag
        e.dataTransfer.setData('application/x-homedrive-item', JSON.stringify(draggedItems));
        e.dataTransfer.effectAllowed = 'move';

        // Visual feedback
        fileItem.classList.add('dragging');
        setTimeout(() => fileItem.classList.add('dragging'), 0);
    });

    fileGrid.addEventListener('dragend', function(e) {
        const fileItem = e.target.closest('.file-item');
        if (!fileItem) return;

        // Clean up visual feedback
        fileItem.classList.remove('dragging');
        document.querySelectorAll('.file-item').forEach(item => {
            item.classList.remove('drag-over-target', 'drag-invalid');
        });
    });

    fileGrid.addEventListener('dragover', function(e) {
        // Check if this is an internal drag (not external files)
        if (e.dataTransfer.types.includes('application/x-homedrive-item')) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        }
    });

    fileGrid.addEventListener('dragenter', function(e) {
        if (!e.dataTransfer.types.includes('application/x-homedrive-item')) return;

        const fileItem = e.target.closest('.file-item');
        if (!fileItem) return;

        const targetPath = fileItem.getAttribute('data-path');
        const isFolder = fileItem.getAttribute('data-is-folder') === 'true';

        // Only folders are valid drop targets
        if (isFolder) {
            // Check if trying to drag folder into itself or its children
            const isDraggingIntoSelf = draggedItems.some(dragPath => {
                return targetPath === dragPath || targetPath.startsWith(dragPath + '/');
            });

            if (isDraggingIntoSelf) {
                fileItem.classList.add('drag-invalid');
            } else {
                fileItem.classList.add('drag-over-target');
            }
        } else {
            fileItem.classList.add('drag-invalid');
        }
    });

    fileGrid.addEventListener('dragleave', function(e) {
        const fileItem = e.target.closest('.file-item');
        if (!fileItem) return;

        // Only remove highlight if leaving the item entirely
        const rect = fileItem.getBoundingClientRect();
        const x = e.clientX;
        const y = e.clientY;

        if (x < rect.left || x >= rect.right || y < rect.top || y >= rect.bottom) {
            fileItem.classList.remove('drag-over-target', 'drag-invalid');
        }
    });

    fileGrid.addEventListener('drop', async function(e) {
        if (!e.dataTransfer.types.includes('application/x-homedrive-item')) return;

        e.preventDefault();
        e.stopPropagation();

        const fileItem = e.target.closest('.file-item');
        if (!fileItem) return;

        const targetPath = fileItem.getAttribute('data-path');
        const isFolder = fileItem.getAttribute('data-is-folder') === 'true';

        // Clean up visual feedback
        fileItem.classList.remove('drag-over-target', 'drag-invalid');

        // Only drop on folders
        if (!isFolder) {
            return;
        }

        // Check for circular move
        const isDraggingIntoSelf = draggedItems.some(dragPath => {
            return targetPath === dragPath || targetPath.startsWith(dragPath + '/');
        });

        if (isDraggingIntoSelf) {
            alert('Cannot move a folder into itself or its subfolder');
            return;
        }

        // Perform move operation
        try {
            if (draggedItems.length > 1) {
                await apiRequest('/api/move-multiple', {
                    method: 'POST',
                    body: JSON.stringify({ sources: draggedItems, destination: targetPath })
                });
            } else {
                await apiRequest('/api/move', {
                    method: 'POST',
                    body: JSON.stringify({ source: draggedItems[0], destination: targetPath })
                });
            }

            selectedFiles.clear();
            loadFiles(currentPath);
        } catch (error) {
            alert('Move failed: ' + error.message);
        }
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
    document.getElementById('file-list').innerHTML = `<div class="empty-message">${escapeHtml(message)}</div>`;
}

// Update disk usage display
async function updateDiskUsage() {
    try {
        const data = await apiRequest('/api/disk-usage');
        const used = formatFileSize(data.used);
        const total = formatFileSize(data.total);
        const percent = data.percent.toFixed(1);
        
        document.getElementById('storage-text').textContent = `${used} / ${total} (${percent}%)`;
        document.getElementById('storage-fill').style.width = percent + '%';
    } catch (error) {
        console.error('Failed to fetch disk usage:', error);
    }
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
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Favorites
async function loadFavorites() {
    try {
        const data = await apiRequest('/api/favorites');
        displayFavorites(data.favorites);
    } catch (error) {
        console.error('Failed to load favorites:', error);
    }
}

function displayFavorites(favorites) {
    const section = document.getElementById('favorites-section');
    const list = document.getElementById('favorites-list');

    if (!favorites || favorites.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';

    let html = '';
    favorites.forEach(fav => {
        html += `
            <div class="favorite-item" onclick="navigateTo('${escapeHtml(fav.path)}')">
                <div class="file-icon">📁</div>
                <div class="file-name">${escapeHtml(fav.name)}</div>
            </div>
        `;
    });

    list.innerHTML = html;
}

async function toggleFavorite(path, event) {
    event.stopPropagation(); // Prevent folder navigation

    try {
        const data = await apiRequest('/api/favorites/toggle', {
            method: 'POST',
            body: JSON.stringify({path: path})
        });

        // Update star icon
        const item = document.querySelector(`[data-path="${path}"]`);
        if (item) {
            const star = item.querySelector('.favorite-star');
            if (star) {
                star.textContent = data.is_favorited ? '★' : '☆';
            }
        }

        // Reload favorites section
        loadFavorites();
    } catch (error) {
        alert('Failed to update favorite: ' + error.message);
    }
}

async function updateFavoriteStars() {
    try {
        const data = await apiRequest('/api/favorites');
        const favoritePaths = new Set(data.favorites.map(f => f.path));

        document.querySelectorAll('.favorite-star').forEach(star => {
            const item = star.closest('.file-item');
            const path = item?.getAttribute('data-path');
            if (path && favoritePaths.has(path)) {
                star.textContent = '★';
            }
        });
    } catch (error) {
        console.error('Failed to update stars:', error);
    }
}

// Password Change
function showChangePasswordModal() {
    document.getElementById('currentPassword').value = '';
    document.getElementById('newPassword').value = '';
    document.getElementById('confirmPassword').value = '';
    showModal('changePasswordModal');
}

async function changePassword() {
    const current = document.getElementById('currentPassword').value;
    const newPass = document.getElementById('newPassword').value;
    const confirm = document.getElementById('confirmPassword').value;

    // Validation
    if (!current || !newPass || !confirm) {
        alert('All fields are required');
        return;
    }

    if (newPass.length < 8) {
        alert('New password must be at least 8 characters');
        return;
    }

    if (newPass !== confirm) {
        alert('New passwords do not match');
        return;
    }

    try {
        const data = await apiRequest('/api/settings/change-password', {
            method: 'POST',
            body: JSON.stringify({
                current_password: current,
                new_password: newPass
            })
        });

        closeModal('changePasswordModal');
        alert('Password changed successfully!');
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// Trash operations
async function emptyTrash() {
    if (!confirm('Permanently delete all items in trash? This cannot be undone.')) {
        return;
    }

    showProgressModal('Emptying trash...');

    try {
        const data = await apiRequest('/api/trash/empty', {method: 'POST'});
        closeModal('progressModal');

        if (data.errors && data.errors.length > 0) {
            alert(`Deleted ${data.deleted} items with ${data.errors.length} errors:\n${data.errors.join('\n')}`);
        } else {
            alert(`Trash emptied: ${data.deleted} items deleted`);
        }

        // Reload if viewing trash
        if (currentPath.startsWith('.trash')) {
            loadFiles(currentPath);
        }

        updateTrashBadge();
    } catch (error) {
        closeModal('progressModal');
        alert('Failed to empty trash: ' + error.message);
    }
}

async function restoreFromTrash() {
    const count = selectedFiles.size;
    const itemText = count > 1 ? `${count} items` : 'this item';

    if (!confirm(`Restore ${itemText}?`)) {
        return;
    }

    try {
        // Extract trash names from selected paths
        const trashNames = Array.from(selectedFiles).map(path => {
            // Path format: ".trash/item_timestamp_filename"
            return path.replace('.trash/', '');
        });

        if (count > 1) {
            await apiRequest('/api/trash/restore', {
                method: 'POST',
                body: JSON.stringify({trash_names: trashNames})
            });
        } else {
            await apiRequest('/api/trash/restore', {
                method: 'POST',
                body: JSON.stringify({trash_name: trashNames[0]})
            });
        }

        selectedFiles.clear();
        loadFiles(currentPath);
        updateTrashBadge();
        alert(`Restored ${count} item(s)`);
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

async function updateTrashBadge() {
    try {
        const data = await apiRequest('/api/trash/info');

        let badge = document.getElementById('trash-badge');
        if (!badge) {
            // Create badge element
            const emptyBtn = document.querySelector('button[onclick="emptyTrash()"]');
            if (emptyBtn) {
                badge = document.createElement('span');
                badge.id = 'trash-badge';
                badge.className = 'trash-badge';
                emptyBtn.appendChild(badge);
            }
        }

        if (badge) {
            if (data.count > 0) {
                badge.textContent = data.count;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Failed to update trash badge:', error);
    }
}

// Folder ZIP Download
function downloadFolderAsZip(path) {
    // Show progress modal
    showProgressModal('Preparing download...');

    // Trigger download
    const url = '/api/download-folder?path=' + encodeURIComponent(path);
    window.location.href = url;

    // Close modal after a delay (download should start)
    setTimeout(() => {
        closeModal('progressModal');
    }, 2000);
}

// Close modals when clicking outside
window.onclick = function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.classList.remove('show');
    }
}
