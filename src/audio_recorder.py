import pyaudio
import wave
import threading
import time
import os

class AudioRecorder(threading.Thread):
    def __init__(self, filename, device_index=None):
        super().__init__()
        self.filename = filename
        self.device_index = device_index
        self.is_recording = False
        self.is_paused = False
        self.stop_event = threading.Event()
        self.frames = []
        
        self.chunk = 1024
        self.format = pyaudio.paInt16
        self.channels = 2
        self.rate = 44100
        
        self.p = pyaudio.PyAudio()

    @staticmethod
    def get_input_devices():
        """返回所有输入设备（麦克风）的列表"""
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

    def run(self):
        self.is_recording = True
        
        # 尝试打开流，如果失败则重试
        stream = None
        try:
            # 第一次尝试：使用默认或检测到的通道数
            try:
                stream = self._open_stream(self.channels)
            except OSError as e:
                # 如果是通道数错误 (Errno -9998)，尝试单声道
                if e.errno == -9998 and self.channels > 1:
                    print(f"Failed with {self.channels} channels, retrying with mono...")
                    self.channels = 1
                    stream = self._open_stream(1)
                else:
                    raise e
            
            if stream:
                while not self.stop_event.is_set():
                    if self.is_paused:
                        time.sleep(0.1)
                        continue
                    try:
                        data = stream.read(self.chunk)
                        self.frames.append(data)
                    except:
                        pass
                
                stream.stop_stream()
                stream.close()
                
        except Exception as e:
            print(f"Audio recording error: {e}")
        finally:
            self.p.terminate()
            self.save_to_file()

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
        self.stop_event.set()
        self.join()

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def save_to_file(self):
        if not self.frames:
            return
            
        import numpy as np
        
        # 将原始 bytes 数据转换为 numpy 数组进行处理
        raw_data = b''.join(self.frames)
        # int16 范围是 -32768 到 32767
        audio_data = np.frombuffer(raw_data, dtype=np.int16)
        
        # 音量增强：归一化
        max_val = np.max(np.abs(audio_data))
        if max_val > 0:
            # 目标峰值 (int16 最大值的 95%)
            target_peak = 32767 * 0.95
            
            # 计算增益，限制最大增益防止过度放大底噪 (例如最大放大 10 倍)
            gain = target_peak / max_val
            gain = min(gain, 10.0) 
            
            if gain > 1.0:
                print(f"Applying mic gain: {gain:.2f}x")
                # 应用增益并裁剪防溢出
                audio_data = audio_data * gain
                audio_data = np.clip(audio_data, -32768, 32767)
                
        # 转回 bytes
        processed_data = audio_data.astype(np.int16).tobytes()

        wf = wave.open(self.filename, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(self.p.get_sample_size(self.format))
        wf.setframerate(self.rate)
        wf.writeframes(processed_data)
        wf.close()
        print(f"Audio saved to {self.filename}")