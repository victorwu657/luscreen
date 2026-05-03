import wave
import threading
import time
import os
import socket

import logging
import numpy as np

# Setup logger
# Reuse global logger if available to ensure output to file
if logging.getLogger("Global").handlers:
    logger = logging.getLogger("Global")
else:
    logger = logging.getLogger('AudioRecorder')
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)

def _get_pyaudio():
    try:
        import pyaudio  # type: ignore
        return pyaudio
    except Exception as e:
        msg = (
            "未检测到麦克风录制组件（PyAudio）或其系统运行库缺失/损坏。"
            "请安装/修复 Microsoft Visual C++ 2010 运行库（VC10，包含 msvcr100.dll/atl100.dll），"
            "然后重启软件。"
        )
        raise RuntimeError(f"{msg} | {type(e).__name__}: {e}")

class AudioRecorder(threading.Thread):
    def __init__(self, filename, device_index=None, stream_port=None):
        super().__init__()
        self.filename = filename
        self.device_index = device_index
        self.stream_port = stream_port
        self.is_recording = False
        self.is_paused = False
        self.stop_event = threading.Event()
        self.frames = []
        
        self.chunk = 1024
        pyaudio = _get_pyaudio()
        self.format = pyaudio.paInt16
        self.channels = 2
        self.rate = 48000 # Standard for video
        
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.stream_sock = None

    @staticmethod
    def get_input_devices():
        """返回所有输入设备（麦克风）的列表"""
        pyaudio = _get_pyaudio()
        p = pyaudio.PyAudio()
        devices = []
        info = p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        
        for i in range(0, numdevices):
            if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                name = p.get_device_info_by_host_api_device_index(0, i).get('name')
                # 过滤掉一些奇怪的设备，或者是中文乱码处理（视情况而定）
                try:
                    # Windows 上 pyaudio 返回的名称可能是 gbk 编码的
                    name = name.encode('cp1252').decode('gbk')
                except:
                    pass
                devices.append({'index': i, 'name': name})
                
        p.terminate()
        return devices

    @staticmethod
    def get_device_index_by_name(target_name):
        """根据名称查找设备索引，用于设备插拔后的重连"""
        if not target_name:
            return None
            
        pyaudio = _get_pyaudio()
        p = pyaudio.PyAudio()
        try:
            info = p.get_host_api_info_by_index(0)
            numdevices = info.get('deviceCount')
            
            # Exact match first
            for i in range(0, numdevices):
                if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                    name = p.get_device_info_by_host_api_device_index(0, i).get('name')
                    try:
                        name = name.encode('cp1252').decode('gbk')
                    except:
                        pass
                        
                    if name == target_name:
                        return i
            
            # Partial match second
            for i in range(0, numdevices):
                if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                    name = p.get_device_info_by_host_api_device_index(0, i).get('name')
                    try:
                        name = name.encode('cp1252').decode('gbk')
                    except:
                        pass
                        
                    if target_name in name:
                        return i
                        
        finally:
            p.terminate()
        return None

    def run(self):
        self.is_recording = True
        logger.info(f"Starting audio recording to {self.filename}")
        
        wf = None
        
        try:
            # Check device capabilities
            target_device_index = self.device_index
            try:
                if target_device_index is not None:
                    dev_info = self.p.get_device_info_by_index(target_device_index)
                else:
                    dev_info = self.p.get_default_input_device_info()
                    target_device_index = dev_info.get('index')
                
                # 1. Channels Detection
                max_channels = int(dev_info.get('maxInputChannels', 1))
                if max_channels > 0:
                    self.channels = min(2, max_channels)
                else:
                    self.channels = 1
                
                # 2. Rate Detection
                default_rate = int(dev_info.get('defaultSampleRate', 44100))
                # Try 48000 first (standard for video), if supported
                try:
                    is_supported = self.p.is_format_supported(
                        rate=48000, 
                        input_device=target_device_index, 
                        input_channels=self.channels, 
                        input_format=self.format,
                        input_parameters=None
                    )
                    if is_supported:
                        self.rate = 48000
                    else:
                        self.rate = default_rate
                except ValueError:
                    # 48000 not supported, fallback to default
                    self.rate = default_rate
                    logger.warning(f"48000Hz not supported, falling back to {self.rate}Hz")
                except Exception as e:
                    logger.warning(f"Rate check failed: {e}, using default {default_rate}Hz")
                    self.rate = default_rate

                logger.info(f"Device: {dev_info.get('name')}, MaxCh: {max_channels}, DefRate: {dev_info.get('defaultSampleRate')}")
                logger.info(f"Configuring: Ch={self.channels}, Rate={self.rate}")
            except Exception as e:
                logger.error(f"Failed to query device info: {e}. Falling back to default settings.")
                # Keep defaults: channels=2 (from init), rate=48000 (from init) -> This might be risky, 
                # let's be conservative if detection fails
                self.channels = 1
                self.rate = 44100

            # Initialize Wave File
            wf = wave.open(self.filename, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.p.get_sample_size(self.format))
            wf.setframerate(self.rate)
            
            # Open Stream
            self.stream = self.p.open(format=self.format,
                                channels=self.channels,
                                rate=self.rate,
                                input=True,
                                input_device_index=self.device_index,
                                frames_per_buffer=self.chunk)
            
            # Connect to stream port if provided (with retry)
            if self.stream_port:
                for _ in range(10): # Try for 5 seconds
                    try:
                        self.stream_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        self.stream_sock.connect(('127.0.0.1', self.stream_port))
                        logger.info(f"Connected to audio stream port {self.stream_port}")
                        break
                    except Exception:
                        self.stream_sock = None
                        time.sleep(0.5)
                
                if not self.stream_sock:
                    logger.error(f"Failed to connect to audio stream port {self.stream_port} after retries")

            if self.stream:
                logger.info("Audio stream opened successfully")
                total_frames = 0
                while not self.stop_event.is_set():
                    if self.is_paused:
                        try:
                            # Read and discard to prevent buffer overflow
                            self.stream.read(self.chunk, exception_on_overflow=False)
                        except:
                            pass
                        time.sleep(0.1)
                        continue
                        
                    try:
                        data = self.stream.read(self.chunk, exception_on_overflow=False)
                        wf.writeframes(data)
                        total_frames += 1
                        if self.stream_sock:
                            try:
                                self.stream_sock.sendall(data)
                            except:
                                self.stream_sock.close()
                                self.stream_sock = None
                    except Exception as e:
                        logger.error(f"Error reading/writing audio stream: {e}")
                        # Don't break, try to continue
                        pass
                
                logger.info(f"Audio recording loop ended. Total frames written: {total_frames} (Approx {total_frames * self.chunk / self.rate:.2f} seconds)")
                
        except Exception as e:
            logger.error(f"Audio recording fatal error: {e}", exc_info=True)
        finally:
            if self.stream_sock:
                try:
                    self.stream_sock.close()
                except:
                    pass
                self.stream_sock = None
            if self.stream:
                try:
                    self.stream.stop_stream()
                except:
                    pass
                try:
                    self.stream.close()
                except:
                    pass
                self.stream = None
                logger.info("Audio stream closed")
            if wf:
                try:
                    wf.close()
                except:
                    pass
            if self.p:
                try:
                    self.p.terminate()
                except:
                    pass
            logger.info("Audio recording finished")

    def _open_stream(self, channels):
        kwargs = {
            'format': self.format,
            'channels': channels,
            'rate': self.rate,
            'input': True,
            'frames_per_buffer': self.chunk
        }
        if self.device_index is not None:
            kwargs['input_device_index'] = self.device_index
            
        return self.p.open(**kwargs)

    def stop(self):
        logger.info("AudioRecorder stop requested alive=%s paused=%s", self.is_alive(), self.is_paused)
        self.stop_event.set()
        self.join(timeout=0.8)
        if self.is_alive():
            logger.warning("AudioRecorder still alive after soft stop, forcing stream shutdown")
            if self.stream:
                try:
                    self.stream.stop_stream()
                except:
                    pass
                try:
                    self.stream.close()
                except:
                    pass
            if self.stream_sock:
                try:
                    self.stream_sock.close()
                except:
                    pass
            self.join(timeout=2.5)
        logger.info("AudioRecorder stop completed alive=%s", self.is_alive())

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def save_to_file(self):
        # Already saved to file during recording loop
        pass
