"""
Audio Transcriber for Streamer Clipper.
Uses Groq API (Whisper model) to transcribe audio and get precise word-level timestamps.
"""

import os
import logging
from pathlib import Path
from typing import List, Optional
from groq import Groq

from core.models import WordTimestamp

# Configure logging
logger = logging.getLogger(__name__)

class AudioTranscriber:
    """Handles audio transcription using Groq's extremely fast Whisper API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initializes the Groq client.
        If api_key is not provided, it looks for GROQ_API_KEY in the environment variables.
        """
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            logger.warning("GROQ_API_KEY is not set. Transcription will fail if not provided.")
        
        # We only initialize the client if an API key is present
        self.client = Groq(api_key=self.api_key) if self.api_key else None
        logger.info("AudioTranscriber initialized with Groq API.")

    def transcribe(self, audio_path: Path, language: str = "en") -> Optional[List[WordTimestamp]]:
        """
        Transcribes the audio file and returns a list of words with timestamps.
        
        Args:
            audio_path: Path to the MP3 audio file.
            language: The language code of the audio (e.g., 'en', 'he').
            
        Returns:
            List of WordTimestamp objects, or None if failed.
        """
        if not self.client:
            logger.error("Groq client is not initialized. Check your API key.")
            return None

        if not audio_path.exists():
            logger.error(f"Audio file not found: {audio_path}")
            return None

        try:
            logger.info(f"Sending audio to Groq Whisper API for transcription: {audio_path.name}")
            
            with open(audio_path, "rb") as file:
                # We request verbose_json and word timestamp granularities
                transcription = self.client.audio.transcriptions.create(
                    file=(audio_path.name, file.read()),
                    model="whisper-large-v3",
                    response_format="verbose_json",
                    language=language,
                    timestamp_granularities=["word"]
                )
            
            # Extract the words array from the response
            words_data = getattr(transcription, 'words', [])
            
            if not words_data:
                logger.error("No word timestamps returned from the API.")
                return None

            word_timestamps = []
            for w in words_data:
                # Handle attributes dynamically in case Groq SDK changes object structure
                word_text = getattr(w, 'word', '').strip()
                start_time = getattr(w, 'start', 0.0)
                end_time = getattr(w, 'end', 0.0)
                
                # Exclude empty words or weird artifacts
                if word_text:
                    word_timestamps.append(
                        WordTimestamp(
                            word=word_text,
                            start=float(start_time),
                            end=float(end_time)
                        )
                    )

            logger.info(f"Successfully transcribed {len(word_timestamps)} words.")
            return word_timestamps

        except Exception as e:
            logger.error(f"Failed to transcribe audio: {e}")
            return None