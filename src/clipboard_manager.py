import os
import sys
import sqlite3
import hashlib
import time
import shutil
import logging
from datetime import datetime, timedelta
from PySide6.QtCore import QObject, Signal, QTimer, QStandardPaths, QDateTime, QBuffer, QByteArray
from PySide6.QtGui import QClipboard, QImage, QPixmap
from PySide6.QtWidgets import QApplication
from src.config import ConfigManager

logger = logging.getLogger("ClipboardManager")

class ClipboardManager(QObject):
    # Signal emitted when a new item is added, passing the new item ID
    item_added = Signal(int)
    # Signal emitted when an item is removed
    item_removed = Signal(int)
    # Signal emitted when data is cleared
    data_cleared = Signal()

    def __init__(self):
        super().__init__()
        
        # Paths
        self.user_data_dir = os.path.join(os.getcwd(), 'user_data')
        self.images_dir = os.path.join(self.user_data_dir, 'clipboard_images')
        self.db_path = os.path.join(self.user_data_dir, 'clipboard.db')
        
        self.config_manager = ConfigManager()
        
        self._init_storage()
        
        # Debounce timer
        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(500) # 500ms debounce
        self.debounce_timer.timeout.connect(self._process_clipboard)
        
        # Clipboard
        self.clipboard = QApplication.clipboard()
        self.clipboard.dataChanged.connect(self._on_clipboard_changed)
        
        # Ignore flag to prevent self-loop when we set clipboard programmatically
        self.ignore_next_change = False
        
        # Clean up old data on startup
        self.cleanup()

    def _init_storage(self):
        """Initialize folders and database"""
        try:
            if not os.path.exists(self.images_dir):
                os.makedirs(self.images_dir)
                
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS clipboard (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT,             -- 'text' or 'image'
                    content TEXT,          -- Full text or image filename
                    preview TEXT,          -- Preview text or thumbnail filename
                    hash TEXT,             -- MD5 hash for deduplication
                    created_at TIMESTAMP,  -- Unix timestamp
                    is_favorite BOOLEAN DEFAULT 0
                )
            ''')
            
            # Index
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON clipboard(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_hash ON clipboard(hash)')
            
            conn.commit()
            conn.close()
            logger.info("Clipboard storage initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize clipboard storage: {e}", exc_info=True)

    def _on_clipboard_changed(self):
        if self.ignore_next_change:
            self.ignore_next_change = False
            return
            
        # Restart timer (debounce)
        self.debounce_timer.start()

    def _process_clipboard(self):
        """Process clipboard data after debounce"""
        try:
            mime_data = self.clipboard.mimeData()
            
            # 1. Direct Image Data (e.g. Screenshot)
            if mime_data.hasImage():
                self._process_image(self.clipboard.image())
                return

            # 2. File URLs (e.g. Copy file from Explorer)
            if mime_data.hasUrls():
                urls = mime_data.urls()
                if urls:
                    # Check the first file if it is an image
                    file_path = urls[0].toLocalFile()
                    if file_path and os.path.exists(file_path):
                        ext = os.path.splitext(file_path)[1].lower()
                        if ext in ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp']:
                            # Load image from file
                            try:
                                image = QImage(file_path)
                                if not image.isNull():
                                    self._process_image(image)
                                    return
                            except Exception as e:
                                logger.warning(f"Failed to load image from file {file_path}: {e}")
            
            # 3. Text Data
            if mime_data.hasText():
                text = mime_data.text().strip()
                if text:
                    self._process_text(text)
        except Exception as e:
            logger.error(f"Error processing clipboard data: {e}", exc_info=True)

    def _process_text(self, text):
        try:
            # Calculate Hash
            md5 = hashlib.md5(text.encode('utf-8')).hexdigest()
            
            # Check if identical to the LATEST item (to avoid consecutive duplicates)
            last_item = self.get_latest_item()
            if last_item and last_item['hash'] == md5:
                return

            preview = text[:100].replace('\n', ' ')
            timestamp = int(time.time())
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO clipboard (type, content, preview, hash, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', ('text', text, preview, md5, timestamp))
            new_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            self.item_added.emit(new_id)
            self._check_limit()
            logger.info(f"Text added to clipboard history. ID: {new_id}")
        except Exception as e:
            logger.error(f"Failed to process text clipboard: {e}", exc_info=True)

    def _process_image(self, qimage):
        if qimage.isNull():
            return
            
        try:
            # Convert QImage to bytes for hashing
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QBuffer.WriteOnly)
            qimage.save(buf, "PNG")
            img_bytes = ba.data()
            
            md5 = hashlib.md5(img_bytes).hexdigest()
            
            # Check duplicate
            last_item = self.get_latest_item()
            if last_item and last_item['hash'] == md5:
                return

            # Save Image
            filename = f"{md5}.png"
            thumb_filename = f"{md5}_thumb.jpg"
            file_path = os.path.join(self.images_dir, filename)
            thumb_path = os.path.join(self.images_dir, thumb_filename)
            
            if not os.path.exists(file_path):
                qimage.save(file_path, "PNG")
                
            # Generate Thumbnail
            if not os.path.exists(thumb_path):
                thumb = qimage.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumb.save(thumb_path, "JPG", quality=80)

            timestamp = int(time.time())
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO clipboard (type, content, preview, hash, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', ('image', filename, thumb_filename, md5, timestamp))
            new_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            self.item_added.emit(new_id)
            self._check_limit()
            logger.info(f"Image added to clipboard history. ID: {new_id}")
        except Exception as e:
            logger.error(f"Failed to process image clipboard: {e}", exc_info=True)

    def get_latest_item(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM clipboard ORDER BY created_at DESC LIMIT 1')
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_history(self, limit=50, offset=0, filter_type=None, only_favorites=False):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM clipboard WHERE 1=1"
        params = []
        
        if filter_type:
            query += " AND type = ?"
            params.append(filter_type)
            
        if only_favorites:
            query += " AND is_favorite = 1"
            
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            item = dict(row)
            # Add full paths for images
            if item['type'] == 'image':
                item['content_path'] = os.path.join(self.images_dir, item['content'])
                item['preview_path'] = os.path.join(self.images_dir, item['preview'])
            results.append(item)
        return results

    def set_favorite(self, item_id, is_favorite):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE clipboard SET is_favorite = ? WHERE id = ?', (1 if is_favorite else 0, item_id))
        conn.commit()
        conn.close()

    def delete_item(self, item_id):
        # Retrieve info first to delete files if needed
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT type, content, preview FROM clipboard WHERE id = ?', (item_id,))
        row = cursor.fetchone()
        
        if row:
            type_, content, preview = row
            # Delete from DB
            cursor.execute('DELETE FROM clipboard WHERE id = ?', (item_id,))
            conn.commit()
            
            # Check if image files are used by other items (deduplication check)
            if type_ == 'image':
                cursor.execute('SELECT COUNT(*) FROM clipboard WHERE content = ?', (content,))
                count = cursor.fetchone()[0]
                if count == 0:
                    # Safe to delete files
                    try:
                        os.remove(os.path.join(self.images_dir, content))
                        os.remove(os.path.join(self.images_dir, preview))
                    except:
                        pass
                        
        conn.close()
        self.item_removed.emit(item_id)

    def clear_all(self):
        """Clear all non-favorite items"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Find images to delete
        cursor.execute('SELECT content, preview FROM clipboard WHERE is_favorite = 0 AND type = "image"')
        images_to_del = cursor.fetchall()
        
        cursor.execute('DELETE FROM clipboard WHERE is_favorite = 0')
        conn.commit()
        conn.close()
        
        # Cleanup files
        # A bit simplistic: we should check if favorites use them, but clear_all usually implies massive cleanup.
        # Safer way: rely on the general cleanup() method or iterate.
        # For now, let's trust cleanup() will handle orphans eventually, or implement strict ref counting.
        # Let's verify against favorites before deleting file.
        
        self.cleanup_orphan_files()
        self.data_cleared.emit()

    def cleanup(self):
        """Keep only last N days AND max N items (non-favorites)"""
        days = self.config_manager.get("clipboard_retention_days", 10)
        max_items = self.config_manager.get("clipboard_max_items", 200)
        
        cutoff_time = int(time.time()) - (days * 24 * 3600)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. Delete old items
        cursor.execute('DELETE FROM clipboard WHERE created_at < ? AND is_favorite = 0', (cutoff_time,))
        
        # 2. Delete if > max_items
        cursor.execute('SELECT COUNT(*) FROM clipboard WHERE is_favorite = 0')
        count = cursor.fetchone()[0]
        if count > max_items:
            limit = count - max_items
            # Delete oldest
            cursor.execute('''
                DELETE FROM clipboard WHERE id IN (
                    SELECT id FROM clipboard WHERE is_favorite = 0 ORDER BY created_at ASC LIMIT ?
                )
            ''', (limit,))
            
        conn.commit()
        conn.close()
        
        self.cleanup_orphan_files()

    def cleanup_orphan_files(self):
        """Delete image files not referenced in DB"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT content, preview FROM clipboard WHERE type = "image"')
        rows = cursor.fetchall()
        conn.close()
        
        used_files = set()
        for r in rows:
            used_files.add(r[0])
            used_files.add(r[1])
            
        if os.path.exists(self.images_dir):
            for f in os.listdir(self.images_dir):
                if f not in used_files:
                    try:
                        os.remove(os.path.join(self.images_dir, f))
                    except:
                        pass
    
    def _check_limit(self):
        # Trigger cleanup occasionally or check count
        # For simplicity, we can run a quick check here
        # But to avoid DB locks, maybe just run cleanup on startup is enough?
        # Let's do a soft check: if ID % 50 == 0, run cleanup
        pass

    def copy_to_clipboard(self, item_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT type, content FROM clipboard WHERE id = ?', (item_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return
            
        type_, content = row
        self.ignore_next_change = True
        
        if type_ == 'text':
            self.clipboard.setText(content)
        elif type_ == 'image':
            path = os.path.join(self.images_dir, content)
            if os.path.exists(path):
                img = QImage(path)
                self.clipboard.setImage(img)

# Global instance
from PySide6.QtCore import Qt