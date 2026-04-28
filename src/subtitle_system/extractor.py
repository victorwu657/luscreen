import os
import subprocess
import shutil
import datetime
from src.utils import get_ffmpeg_path

class AudioExtractor:
    @staticmethod
    def extract_audio(video_path, output_wav, mic_path=None):
        """
        Extract audio from video or copy/convert existing mic audio.
        Target format: 16kHz, 16bit, mono WAV (ASR friendly).
        
        Args:
            video_path (str): Path to the video file.
            output_wav (str): Path to save the processed audio.
            mic_path (str, optional): Path to existing mic recording. 
                                    If provided and valid, it will be used as source.
        """
        ffmpeg_exe = get_ffmpeg_path()
        
        # 1. Optimization: Use existing mic file if available
        if mic_path and os.path.exists(mic_path):
            # Check if we need conversion? 
            # To be safe, we always run it through ffmpeg to ensure 16k/mono, 
            # but it will be much faster than extracting from video.
            input_source = mic_path
        else:
            # 2. Fallback: Extract from video
            input_source = video_path

        try:
            input_source = os.path.abspath(input_source)
        except Exception:
            pass
        try:
            output_wav = os.path.abspath(output_wav)
        except Exception:
            pass
            
        cmd = [
            ffmpeg_exe, '-y',
            '-i', input_source,
            '-vn',                # No video
            '-acodec', 'pcm_s16le', # 16-bit PCM
            '-ar', '16000',       # 16kHz sample rate
            '-ac', '1',           # Mono
            output_wav
        ]
        
        # Hide console window on Windows
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        proc = subprocess.run(
            cmd,
            startupinfo=startupinfo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        out = (proc.stdout or "").strip()
        tail = out[-4000:] if len(out) > 4000 else out
        if proc.returncode != 0:
            try:
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                logs_dir = os.path.join(project_root, "logs")
                os.makedirs(logs_dir, exist_ok=True)
                log_path = os.path.join(logs_dir, "subtitle_ffmpeg_extract_error.log")
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(
                        f"[{ts}] code={proc.returncode}\n"
                        f"input={input_source}\n"
                        f"output={output_wav}\n"
                        f"cmd={cmd!r}\n"
                        f"{out}\n"
                        "----\n"
                    )
            except Exception:
                pass
            raise RuntimeError(f"FFmpeg audio extract failed (code={proc.returncode}).\ncmd={cmd!r}\n{tail}".strip())

        try:
            if not os.path.exists(output_wav) or os.path.getsize(output_wav) < 64:
                raise RuntimeError("output wav is empty")
            with open(output_wav, "rb") as f:
                head = f.read(12)
            if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                raise RuntimeError("output wav header invalid")
        except Exception as e:
            msg = f"FFmpeg produced an invalid WAV. The input may have no audio stream.\ninput={input_source!r}\noutput={output_wav!r}"
            if tail:
                msg = msg + "\n" + tail
            raise RuntimeError(msg) from e
