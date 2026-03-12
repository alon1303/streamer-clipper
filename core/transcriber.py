"""
Audio Transcriber for Streamer Clipper.
Includes Auto-Chunking for files larger than 25MB (Groq API Limit).
"""

import os
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional
from groq import Groq

from core.models import WordTimestamp

logger = logging.getLogger(__name__)

class AudioTranscriber:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key) if self.api_key else None

    def _get_audio_duration(self, audio_path: Path) -> float:
        """מוצא את האורך המדויק של חתיכת אודיו בשניות"""
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)
            ], capture_output=True, text=True)
            return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"Failed to get audio duration: {e}")
            return 600.0

    def _transcribe_file(self, audio_path: Path, language: str, time_offset: float) -> List[WordTimestamp]:
        """מתמלל קובץ יחיד ומוסיף לו את הזמן היחסי (Offset) שלו"""
        if not self.client or not audio_path.exists():
            return []

        try:
            with open(audio_path, "rb") as file:
                transcription = self.client.audio.transcriptions.create(
                    file=(audio_path.name, file.read()),
                    model="whisper-large-v3",
                    response_format="verbose_json",
                    language=language,
                    timestamp_granularities=["word"]  # <--- הנה התיקון!
                )
            
            words_data = []
            if hasattr(transcription, 'model_dump'):
                words_data = transcription.model_dump().get('words', [])
            elif hasattr(transcription, 'words'):
                words_data = transcription.words
            elif isinstance(transcription, dict):
                words_data = transcription.get('words', [])
            
            word_timestamps = []
            for w in words_data:
                word_text = w.get('word', '').strip() if isinstance(w, dict) else getattr(w, 'word', '').strip()
                start_time = w.get('start', 0.0) if isinstance(w, dict) else getattr(w, 'start', 0.0)
                end_time = w.get('end', 0.0) if isinstance(w, dict) else getattr(w, 'end', 0.0)
                
                if word_text:
                    word_timestamps.append(WordTimestamp(
                        word=word_text, 
                        start=float(start_time) + time_offset, 
                        end=float(end_time) + time_offset
                    ))

            return word_timestamps

        except Exception as e:
            logger.error(f"Failed to transcribe chunk {audio_path.name}: {e}")
            return []

    def transcribe(self, audio_path: Path, language: str = "en") -> Optional[List[WordTimestamp]]:
        if not self.client:
            logger.error("Groq client is not initialized.")
            return None
            
        # בדיקת גודל הקובץ במגה-בייטים
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        
        # אם הוא קטן מהמגבלה של Groq (25MB), נשלח אותו כיחידה אחת
        if file_size_mb < 24.0:
            logger.info(f"File is {file_size_mb:.1f}MB. Sending as single file...")
            words = self._transcribe_file(audio_path, language, 0.0)
            return words if words else None
            
        # אם הוא ענק, מפצלים אותו לחתיכות
        logger.info(f"File is {file_size_mb:.1f}MB (over 25MB limit). Splitting into chunks...")
        all_words = []
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            chunk_pattern = str(temp_path / "chunk_%03d.mp3")
            
            # פיצול מהיר בעזרת FFmpeg ל-10 דקות (600 שניות) ללא קידוד מחדש
            subprocess.run([
                'ffmpeg', '-y', '-i', str(audio_path),
                '-f', 'segment', '-segment_time', '600',
                '-c', 'copy', chunk_pattern
            ], capture_output=True)
            
            chunks = sorted(list(temp_path.glob("chunk_*.mp3")))
            logger.info(f"Split into {len(chunks)} chunks for transcription.")
            
            current_offset = 0.0
            
            # תמלול כל חתיכה בנפרד
            for i, chunk in enumerate(chunks):
                logger.info(f"Transcribing chunk {i+1}/{len(chunks)}...")
                words = self._transcribe_file(chunk, language, current_offset)
                if words:
                    all_words.extend(words)
                else:
                    logger.warning(f"Chunk {i+1} returned no words. Continuing...")
                
                # מודדים את האורך המדויק של החתיכה הזו כדי שהבאה תתחיל בזמן הנכון
                chunk_duration = self._get_audio_duration(chunk)
                current_offset += chunk_duration

        logger.info(f"Successfully transcribed total of {len(all_words)} words across all chunks.")
        return all_words if all_words else None