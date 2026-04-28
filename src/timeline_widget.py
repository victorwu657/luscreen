from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath
import copy
import wave
import numpy as np
import os

class TimelineWidget(QWidget):
    seekRequested = Signal(int) # position in ms

    def __init__(self, duration=0):
        super().__init__()
        self.setFixedHeight(100)
        self.duration = duration # Total duration in ms
        self.position = 0
        
        # Segments: list of dict {'start': ms, 'end': ms, 'source_start': ms, 'source_end': ms, 'selected': bool}
        self.segments = [] 
        if duration > 0:
            self.segments.append({
                'start': 0, 'end': duration, 
                'source_start': 0, 'source_end': duration, 
                'selected': False
            })
            
        self.setMouseTracking(True)
        
        # Dragging state
        self.is_dragging_segment = False
        self.drag_start_x = 0
        self.drag_segment_index = -1
        self.drag_original_start = 0
        self.drag_original_end = 0
        
        # Undo/Redo stacks
        self.undo_stack = []
        self.redo_stack = []
        
        # Audio Waveform Data
        self.waveform_mic = None # (data, ms_per_point)
        self.waveform_sys = None

    def load_audio_data(self, path):
        if not path or not os.path.exists(path):
            return None
        try:
            if not str(path).lower().endswith(".wav"):
                return None
        except Exception:
            return None
        try:
            try:
                with open(path, "rb") as f:
                    if f.read(4) != b"RIFF":
                        return None
            except Exception:
                return None
            with wave.open(path, 'rb') as wf:
                framerate = wf.getframerate()
                n_frames = wf.getnframes()
                channels = wf.getnchannels()
                width = wf.getsampwidth()
                
                # Duration in seconds
                duration_sec = n_frames / framerate
                
                # We want roughly 1 point per 20ms for reasonable detail without killing performance
                ms_per_point = 20 
                total_points = int((duration_sec * 1000) / ms_per_point)
                
                if total_points == 0: return None
                
                # Read raw data
                raw_data = wf.readframes(n_frames)
                
                if width == 2:
                    y = np.frombuffer(raw_data, dtype=np.int16)
                elif width == 1:
                    y = np.frombuffer(raw_data, dtype=np.int8)
                else:
                    return None
                
                y = y.astype(np.float32)
                if channels > 1:
                    y = y.reshape(-1, channels).mean(axis=1)
                
                # Downsample logic
                # Reshape to (total_points, chunk_size) and take max abs (envelope)
                chunk_size = int(len(y) / total_points)
                if chunk_size < 1: chunk_size = 1
                
                # Pad or truncate to match reshape size
                target_len = total_points * chunk_size
                if len(y) < target_len:
                    y = np.pad(y, (0, target_len - len(y)))
                else:
                    y = y[:target_len]
                    
                y_reshaped = y.reshape(total_points, chunk_size)
                y_envelope = np.max(np.abs(y_reshaped), axis=1)
                
                # Normalize 0.0 - 1.0
                m = np.max(y_envelope)
                if m > 0:
                    y_envelope /= m
                    
                return y_envelope, ms_per_point
        except Exception as e:
            print(f"Error loading audio waveform: {e}")
            return None

    def set_audio_paths(self, mic_path, sys_path):
        print(f"Timeline: Loading waveforms... Mic: {mic_path}, Sys: {sys_path}")
        if mic_path:
            self.waveform_mic = self.load_audio_data(mic_path)
        if sys_path:
            self.waveform_sys = self.load_audio_data(sys_path)
        self.update()

    def _save_state(self):
        """Save current state to undo stack."""
        self.undo_stack.append(copy.deepcopy(self.segments))
        self.redo_stack.clear() # New action clears redo stack

    def undo(self):
        if not self.undo_stack: return False
        
        # Save current state to redo stack
        self.redo_stack.append(copy.deepcopy(self.segments))
        
        # Restore state
        self.segments = self.undo_stack.pop()
        self.update()
        return True

    def redo(self):
        if not self.redo_stack: return False
        
        # Save current state to undo stack
        self.undo_stack.append(copy.deepcopy(self.segments))
        
        # Restore state
        self.segments = self.redo_stack.pop()
        self.update()
        return True

    def set_duration(self, duration):
        # Always reset if duration changes or segments are empty
        if self.duration == duration and self.segments:
            return
            
        self.duration = duration
        self.segments = [{
            'start': 0, 'end': duration, 
            'source_start': 0, 'source_end': duration, 
            'selected': False
        }]
        self.update()

    def set_position(self, pos):
        self.position = pos
        self.update()

    def split_at_current(self):
        """Split the segment under the current playhead position."""
        if self.duration <= 0: return False
        
        new_segments = []
        split_done = False
        
        for seg in self.segments:
            s, e = seg['start'], seg['end']
            if s < self.position < e and not split_done:
                # Save state before modification
                self._save_state()
                
                # Calculate split point relative to source
                offset = self.position - s
                split_source = seg['source_start'] + offset
                
                # Left part
                new_segments.append({
                    'start': s, 'end': self.position, 
                    'source_start': seg['source_start'], 'source_end': split_source,
                    'selected': False
                })
                # Right part
                new_segments.append({
                    'start': self.position, 'end': e, 
                    'source_start': split_source, 'source_end': seg['source_end'],
                    'selected': True
                }) 
                split_done = True
            else:
                new_segments.append(seg)
        
        if split_done:
            self.segments = new_segments
            self.update()
            return True
        return False

    def delete_selected(self):
        """Remove selected segments and shift subsequent segments left (Ripple Delete)."""
        if not self.segments: return
        
        # Check if anything is selected
        selected_indices = [i for i, s in enumerate(self.segments) if s['selected']]
        if not selected_indices: return

        self._save_state()
        
        # Process deletions from right to left to avoid index shifting issues
        selected_indices.sort(reverse=True)
        
        for idx in selected_indices:
            deleted_seg = self.segments.pop(idx)
            duration = deleted_seg['end'] - deleted_seg['start']
            
            # Shift all subsequent segments to the left
            for i in range(idx, len(self.segments)):
                self.segments[i]['start'] -= duration
                self.segments[i]['end'] -= duration
                
            # Update total duration
            self.duration -= duration
            
        # Ensure position is within bounds
        if self.position > self.duration:
            self.position = self.duration
            
        self.update()

    def get_segments(self):
        return self.segments

    def map_timeline_to_source(self, timeline_pos):
        """Map a timeline position (logical) to source video position (physical)."""
        for seg in self.segments:
            if seg['start'] <= timeline_pos < seg['end']:
                offset = timeline_pos - seg['start']
                return seg['source_start'] + offset
        
        # If at exact end
        if self.segments and timeline_pos == self.segments[-1]['end']:
             return self.segments[-1]['source_end']
             
        return None # In gap or out of bounds (shouldn't happen with ripple delete)

    def map_source_to_timeline(self, source_pos):
        """Map a source video position (physical) to timeline position (logical)."""
        for seg in self.segments:
            if seg['source_start'] <= source_pos < seg['source_end']:
                offset = source_pos - seg['source_start']
                return seg['start'] + offset
                
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        
        # Ensure font has valid point size to prevent warnings
        f = painter.font()
        if f.pointSize() <= 0:
            f.setPointSize(9)
            painter.setFont(f)

        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        # Background
        painter.fillRect(event.rect(), QColor("#1e1e1e"))
        
        if self.duration <= 0:
            painter.end()
            return

        # Calculate Scale: fit total duration to width
        px_per_ms = w / self.duration
        
        # Optimization: Only draw visible range
        # Get exposed rect from event
        visible_rect = event.rect()
        view_start_x = visible_rect.left()
        view_end_x = visible_rect.right()
        
        # Convert to time
        start_ms = int(view_start_x / px_per_ms)
        end_ms = int(view_end_x / px_per_ms)
        
        # Add buffer to avoid clipping text/lines at edges
        start_ms = max(0, start_ms - 1000)
        end_ms = min(self.duration, end_ms + 1000)
        
        # 1. Draw Ruler (Top)
        painter.setPen(QColor("#666"))
        
        # Draw ticks
        # Aim for ~100px per major tick
        major_step_ms = 1000
        while (major_step_ms * px_per_ms) < 60:
            major_step_ms += 1000
            
        # Align start loop to grid
        first_tick = (start_ms // 1000) * 1000
        
        for t in range(first_tick, end_ms, 1000): # Small ticks every second
            x = t * px_per_ms
            if t % major_step_ms == 0:
                # Major tick
                painter.drawLine(int(x), 0, int(x), 15)
                seconds = t // 1000
                time_str = f"{seconds // 60}:{seconds % 60:02}"
                painter.drawText(int(x) + 4, 12, time_str)
            else:
                # Minor tick
                if (t * px_per_ms) - int(t/major_step_ms)*major_step_ms*px_per_ms > 10: # Don't overlap text
                    painter.drawLine(int(x), 0, int(x), 5)

        # 2. Draw Segments (Video Tracks)
        track_y = 30
        track_h = 50
        
        for seg in self.segments:
            sx = seg['start'] * px_per_ms
            ex = seg['end'] * px_per_ms
            
            # Skip if segment is not in visible range
            if ex < view_start_x or sx > view_end_x:
                continue
            
            # Visual gap between segments
            visual_w = max(1.0, (ex - sx) - 2.0) 
            
            # Clip Rect
            rect = QRectF(sx, track_y, visual_w, track_h)
            
            # Color
            if seg['selected']:
                # Selected: White outline + Lighter Blue Fill
                painter.setBrush(QColor("#4ea8de")) 
                painter.setPen(QPen(QColor("#ffffff"), 3)) # Thicker white border
                painter.drawRoundedRect(rect, 4, 4)
            else:
                # Normal: Standard Blue + No Border
                painter.setBrush(QColor("#3A86FF")) 
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(rect, 4, 4)
            
            # Draw waveform
            mid_y = track_y + track_h / 2
            
            # Helper to draw waveform
            def draw_waveform(data_tuple, color, y_offset=0, height_scale=1.0):
                if not data_tuple: return
                data, ms_per_point = data_tuple
                
                painter.setPen(color)
                
                # Calculate index range based on segment SOURCE start/end
                # But constrained by visible timeline range (start_ms, end_ms)
                
                # Intersection of Segment and Visible Range
                visible_seg_start = max(seg['start'], start_ms)
                visible_seg_end = min(seg['end'], end_ms)
                
                if visible_seg_start >= visible_seg_end: return
                
                # Map to Source Time
                source_offset_start = visible_seg_start - seg['start']
                source_start_time = seg['source_start'] + source_offset_start
                
                source_offset_end = visible_seg_end - seg['start']
                source_end_time = seg['source_start'] + source_offset_end
                
                # Convert to indices
                start_idx = int(source_start_time / ms_per_point)
                end_idx = int(source_end_time / ms_per_point)
                
                # Clip to available data
                start_idx = max(0, start_idx)
                end_idx = min(len(data), end_idx)
                
                if start_idx >= end_idx: return
                
                # Check pixel step
                pixel_step = ms_per_point * px_per_ms
                skip = 1
                if pixel_step < 0.5:
                    skip = int(0.5 / pixel_step) + 1
                
                # Draw relative to timeline X
                seg_start_x = seg['start'] * px_per_ms
                
                for i in range(start_idx, end_idx, skip):
                    amp = data[i]
                    if amp < 0.01: continue
                    
                    # Time offset from source start
                    time_offset = (i * ms_per_point) - seg['source_start']
                    x = int(seg_start_x + (time_offset * px_per_ms))
                    
                    # Double check X (though indices should be correct)
                    # if x < view_start_x or x > view_end_x: continue
                    
                    h_wave = amp * (track_h / 2 * 0.8) * height_scale
                    
                    # Center around mid_y + y_offset
                    cy = mid_y + y_offset
                    painter.drawLine(x, int(cy - h_wave), x, int(cy + h_wave))

            # If we have real data, draw it
            has_real_data = (self.waveform_mic is not None) or (self.waveform_sys is not None)
            
            if has_real_data:
                # Draw Mic in Cyan/Whiteish
                draw_waveform(self.waveform_mic, QColor(255, 255, 255, 180), y_offset=-5, height_scale=0.8)
                # Draw Sys in Yellowish/Orange
                draw_waveform(self.waveform_sys, QColor(255, 200, 50, 150), y_offset=5, height_scale=0.8)
            else:
                # Fallback to pseudo-random simulation
                painter.setPen(QColor(255, 255, 255, 40))
                
                # Only draw in visible range
                loop_start = max(int(sx), int(view_start_x))
                loop_end = min(int(ex), int(view_end_x))
                
                step = max(2, int(visual_w / 50))
                # Ensure step is at least 1
                step = max(1, step)
                
                if loop_start < loop_end:
                    for i in range(loop_start, loop_end, step):
                        h_wave = ((i * 7) % 15) + 5
                        painter.drawLine(int(i), int(mid_y - h_wave), int(i), int(mid_y + h_wave))

        # 3. Draw Playhead
        playhead_x = self.position * px_per_ms
        
        # Draw playhead only if visible
        if view_start_x <= playhead_x <= view_end_x + 10: # +10 for handle
            painter.setPen(QPen(QColor("#FF5252"), 1))
            painter.drawLine(int(playhead_x), 0, int(playhead_x), h)
            
            # Handle (Circle at top)
            painter.setBrush(QColor("#FF5252"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(int(playhead_x) - 4, 2, 8, 8)
        
        painter.end()

    def mousePressEvent(self, event):
        x = event.position().x()
        
        if self.duration <= 0: return
        
        # Check if clicked on a segment (Video Track Area)
        track_y = 30
        track_h = 50
        y = event.position().y()
        
        px_per_ms = self.width() / self.duration
        
        if track_y <= y <= track_y + track_h:
            # Check for segment click
            clicked_segment_index = -1
            for i, seg in enumerate(self.segments):
                sx = seg['start'] * px_per_ms
                ex = seg['end'] * px_per_ms
                if sx <= x <= ex:
                    clicked_segment_index = i
                    break
            
            if clicked_segment_index != -1:
                # Start dragging
                self.is_dragging_segment = True
                self.drag_segment_index = clicked_segment_index
                self.drag_start_x = x
                self.drag_original_start = self.segments[clicked_segment_index]['start']
                self.drag_original_end = self.segments[clicked_segment_index]['end']
                
                # Select this segment and deselect others
                for i, seg in enumerate(self.segments):
                    seg['selected'] = (i == clicked_segment_index)
                
                self.update()
                return # Don't seek when starting drag on a segment

        # If not dragging segment, behave as seek
        ms = int(x / self.width() * self.duration)
        ms = max(0, min(ms, self.duration))
        
        if track_y <= y <= track_y + track_h:
            # Deselect all if clicked in empty space in track area
            for seg in self.segments:
                seg['selected'] = False
        
        self.seekRequested.emit(ms)
        self.update()

    def mouseMoveEvent(self, event):
        x = event.position().x()
        
        if self.is_dragging_segment and self.drag_segment_index != -1:
            # Calculate delta time
            px_per_ms = self.width() / self.duration
            delta_px = x - self.drag_start_x
            delta_ms = int(delta_px / px_per_ms)
            
            # Apply to segment
            new_start = self.drag_original_start + delta_ms
            new_end = self.drag_original_end + delta_ms
            
            # Constraints
            duration = new_end - new_start
            
            # 1. Start >= 0
            if new_start < 0:
                new_start = 0
                new_end = duration
                
            # 2. End <= self.duration
            if new_end > self.duration:
                new_end = self.duration
                new_start = self.duration - duration
                
            # 3. Collision detection (Simple: don't overlap others)
            # Find neighbors
            # Sort segments by start time to find neighbors reliably? 
            # For now, just check against all other segments
            # Actually, standard behavior is often "snap" or "stop at neighbor"
            # Let's implement "Stop at neighbor"
            
            # Check left neighbor
            left_limit = 0
            for i, seg in enumerate(self.segments):
                if i != self.drag_segment_index:
                    if seg['end'] <= self.drag_original_start: # It's to the left
                        left_limit = max(left_limit, seg['end'])
            
            if new_start < left_limit:
                new_start = left_limit
                new_end = left_limit + duration
                
            # Check right neighbor
            right_limit = self.duration
            for i, seg in enumerate(self.segments):
                if i != self.drag_segment_index:
                    if seg['start'] >= self.drag_original_end: # It's to the right
                        right_limit = min(right_limit, seg['start'])
            
            if new_end > right_limit:
                new_end = right_limit
                new_start = right_limit - duration

            # Update segment
            self.segments[self.drag_segment_index]['start'] = new_start
            self.segments[self.drag_segment_index]['end'] = new_end
            
            self.update()
            return

        if event.buttons() & Qt.LeftButton:
            if self.duration > 0:
                ms = int(x / self.width() * self.duration)
                ms = max(0, min(ms, self.duration))
                self.seekRequested.emit(ms)

    def mouseReleaseEvent(self, event):
        if self.is_dragging_segment:
            self.is_dragging_segment = False
            self.drag_segment_index = -1
            # Sort segments by time to keep order consistent
            self.segments.sort(key=lambda s: s['start'])
            self.update()
