from abc import ABC, abstractmethod
from typing import List
from src.subtitle_system.formatter import SubtitleSegment

class ASRKeyInterface(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> List[SubtitleSegment]:
        """
        Transcribe audio file to subtitle segments.
        
        Args:
            audio_path: Path to 16kHz mono wav file.
            
        Returns:
            List of SubtitleSegment
        """
        pass
