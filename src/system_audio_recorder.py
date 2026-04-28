# import soundcard as sc # 移动到 run 方法内
import soundfile as sf
import threading
import time
import logging
import os
import sys
import warnings
import socket
import numpy as np

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
            
        logs_dir = os.path.join(base_path, 'logs')
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
            
        log_file = os.path.join(logs_dir, 'system_audio_debug.log')
        
        fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
    return logger

def _patch_soundcard_numpy_compat():
    try:
        import numpy as _np
        major = int(str(getattr(_np, "__version__", "0")).split(".", 1)[0] or 0)
        if major < 2:
            return False
    except Exception:
        return False

    try:
        import soundcard.mediafoundation as mf
    except Exception:
        return False

    try:
        if not hasattr(mf, "numpy"):
            return False
        if not hasattr(mf.numpy, "frombuffer"):
            return False
        if not hasattr(mf.numpy, "fromstring"):
            return False

        def _safe_fromstring(buf, dtype=None, count=-1, sep=""):
            return mf.numpy.frombuffer(buf, dtype=dtype, count=count).copy()

        mf.numpy.fromstring = _safe_fromstring
        return True
    except Exception:
        return False

def _patch_soundcard_com_shutdown():
    try:
        import soundcard.mediafoundation as mf
        cls = getattr(mf, "_COMLibrary", None)
        if cls is None:
            return False
        orig = getattr(cls, "__del__", None)
        if orig is None:
            return False
        if getattr(orig, "__luscreen_patched__", False):
            return True

        def _safe_del(self):
            try:
                return orig(self)
            except Exception:
                return None

        setattr(_safe_del, "__luscreen_patched__", True)
        cls.__del__ = _safe_del
        return True
    except Exception:
        return False

class SystemAudioRecorder(threading.Thread):
    def __init__(self, filename, stream_port=None):
        super().__init__()
        self.filename = filename
        self.stream_port = stream_port
        self.is_recording = False
        self.is_paused = False
        self.stop_event = threading.Event()
        self.data_chunks = []
        self.samplerate = 48000 # Standard for video
        self.logger = setup_logger()

    def run(self):
        self.logger.info("Starting SystemAudioRecorder thread")
        self.logger.info(f"Target filename: {self.filename}")
        
        # Lazy import to avoid COM conflicts on main thread
        try:
            import soundcard as sc
            from soundcard import SoundcardRuntimeWarning
            # Filter the specific warning about data discontinuity
            warnings.filterwarnings("ignore", category=SoundcardRuntimeWarning, message="data discontinuity in recording")
            self.logger.info("Successfully imported soundcard")
            if _patch_soundcard_numpy_compat():
                self.logger.info("Applied NumPy>=2 compatibility patch for soundcard (fromstring -> frombuffer().copy())")
            if _patch_soundcard_com_shutdown():
                self.logger.info("Applied soundcard COM shutdown patch (suppress __del__ exceptions)")
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
            
            # Connect to stream port if provided (with retry)
            stream_sock = None
            if self.stream_port:
                for _ in range(10):
                    try:
                        stream_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        stream_sock.connect(('127.0.0.1', self.stream_port))
                        self.logger.info(f"Connected to system audio stream port {self.stream_port}")
                        break
                    except Exception:
                        stream_sock = None
                        time.sleep(0.5)
                        
                if not stream_sock:
                    self.logger.error(f"Failed to connect to system audio stream port {self.stream_port} after retries")

            with mic_recorder.recorder(samplerate=self.samplerate) as mic:
                file = None
                channels = None
                try:
                    while not self.stop_event.is_set():
                        if self.is_paused:
                            time.sleep(0.1)
                            try:
                                mic.record(numframes=4096)
                            except Exception:
                                pass
                            continue

                        try:
                            data = mic.record(numframes=4096)
                            if data is None:
                                continue
                            if channels is None:
                                try:
                                    channels = int(getattr(data, "shape", [0, 0])[1]) if getattr(data, "ndim", 0) == 2 else 1
                                except Exception:
                                    channels = 2
                                channels = 1 if channels <= 1 else 2
                                file = sf.SoundFile(self.filename, mode='w', samplerate=self.samplerate, channels=channels)
                            file.write(data)

                            if stream_sock:
                                try:
                                    int_data = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
                                    stream_sock.sendall(int_data.tobytes())
                                except Exception:
                                    stream_sock.close()
                                    stream_sock = None
                        except Exception as e:
                            self.logger.error(f"Error during recording loop: {e}")
                            break
                finally:
                    try:
                        if file is not None:
                            file.close()
                    except Exception:
                        pass
            
            if stream_sock:
                stream_sock.close()
                        
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
        # Deprecated: Streaming to disk implemented
        pass
