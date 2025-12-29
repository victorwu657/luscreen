# import soundcard as sc # 移动到 run 方法内
import soundfile as sf
import threading
import time
import logging
import os
import sys

def setup_logger():
    """Setup a logger that writes to a file in the executable's directory."""
    logger = logging.getLogger('SystemAudioRecorder')
    logger.setLevel(logging.DEBUG)
    
    # Check if handlers already exist to avoid duplicates
    if not logger.handlers:
        # Determine log path: use executable directory
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
        log_file = os.path.join(base_path, 'system_audio_debug.log')
        
        fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
    return logger

class SystemAudioRecorder(threading.Thread):
    def __init__(self, filename):
        super().__init__()
        self.filename = filename
        self.is_recording = False
        self.is_paused = False
        self.stop_event = threading.Event()
        self.data_chunks = []
        self.samplerate = 44100 # soundcard defaults to 44100 or 48000
        self.logger = setup_logger()

    def run(self):
        self.logger.info("Starting SystemAudioRecorder thread")
        self.logger.info(f"Target filename: {self.filename}")
        
        # Lazy import to avoid COM conflicts on main thread
        try:
            import soundcard as sc
            self.logger.info("Successfully imported soundcard")
        except Exception as e:
            self.logger.error(f"Failed to import soundcard: {e}")
            return
        
        self.is_recording = True
        try:
            # Get default speaker
            try:
                default_speaker = sc.default_speaker()
                self.logger.info(f"Default speaker found: {default_speaker.name} (ID: {default_speaker.id})")
            except Exception as e:
                self.logger.error(f"Failed to get default speaker: {e}")
                return
            
            # Robust Loopback device lookup
            mic_recorder = None
            
            # 1. Try by ID
            try:
                self.logger.info(f"Attempting to get mic by ID: {default_speaker.id}")
                mic_recorder = sc.get_microphone(id=str(default_speaker.id), include_loopback=True)
                self.logger.info("Successfully got mic by ID")
            except Exception as e:
                self.logger.warning(f"Failed to get mic by ID: {e}")
            
            # 2. If failed, search by name
            if mic_recorder is None:
                self.logger.info("Searching for loopback device by name...")
                try:
                    all_mics = sc.all_microphones(include_loopback=True)
                    self.logger.info(f"Found {len(all_mics)} total microphones")
                    for mic in all_mics:
                        self.logger.debug(f"Checking mic: {mic.name} (Loopback: {mic.isloopback})")
                        if mic.isloopback and (mic.name == default_speaker.name or default_speaker.name in mic.name):
                            mic_recorder = mic
                            self.logger.info(f"Match found: {mic.name}")
                            break
                except Exception as e:
                    self.logger.error(f"Failed to search mics: {e}")

            if mic_recorder is None:
                self.logger.error("Error: Could not find a valid loopback device. System audio will not be recorded.")
                return

            self.logger.info(f"Recording from: {mic_recorder.name}")
            
            with mic_recorder.recorder(samplerate=self.samplerate) as mic:
                while not self.stop_event.is_set():
                    if self.is_paused:
                        time.sleep(0.1)
                        try:
                            mic.record(numframes=4096)
                        except:
                            pass
                        continue
                        
                    # Read 4096 frames (~93ms)
                    try:
                        data = mic.record(numframes=4096)
                        self.data_chunks.append(data)
                    except Exception as e:
                        self.logger.error(f"Error during recording loop: {e}")
                        break
                    
        except Exception as e:
            self.logger.error(f"System audio recording fatal error: {e}")
        finally:
            self.logger.info("Recording loop finished, saving file...")
            self.save_to_file()

    def stop(self):
        self.logger.info("Stop requested")
        self.stop_event.set()
        self.join()

    def pause(self):
        self.logger.info("Paused")
        self.is_paused = True

    def resume(self):
        self.logger.info("Resumed")
        self.is_paused = False

    def save_to_file(self):
        if not self.data_chunks:
            self.logger.warning("No data chunks to save")
            return
        
        try:
            import numpy as np
            # Merge all chunks
            all_data = np.concatenate(self.data_chunks, axis=0)
            
            # Simple gain normalization
            max_val = np.max(np.abs(all_data))
            if max_val > 0:
                target_peak = 0.95
                gain = target_peak / max_val
                gain = min(gain, 3.0) # Max 3x gain
                
                if gain > 1.0:
                    self.logger.info(f"Applying gain: {gain:.2f}x")
                    all_data = all_data * gain
            
            # Save as wav
            sf.write(self.filename, all_data, self.samplerate)
            self.logger.info(f"System audio saved to {self.filename}")
        except Exception as e:
            self.logger.error(f"Failed to save file: {e}")
