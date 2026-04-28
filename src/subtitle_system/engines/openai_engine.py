import os
import importlib
from typing import List
from src.subtitle_system.engines.base import ASRKeyInterface
from src.subtitle_system.formatter import SubtitleSegment

class OpenAIEngine(ASRKeyInterface):
    def __init__(self, api_key: str, base_url: str = None):
        try:
            # Dynamic import to avoid Nuitka bundling openai
            openai_pkg = importlib.import_module("openai")
            self.OpenAI = openai_pkg.OpenAI
        except ImportError:
            raise ImportError("Please install openai: pip install openai")
            
        self.client = self.OpenAI(api_key=api_key, base_url=base_url)

    def transcribe(self, audio_path: str) -> List[SubtitleSegment]:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        with open(audio_path, "rb") as audio_file:
            transcript = self.client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                response_format="verbose_json"
            )
        
        segments = []
        # OpenAI returns an object with a 'segments' list
        for seg in transcript.segments:
            segments.append(SubtitleSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip()
            ))
            
        return segments
