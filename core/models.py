"""
Core Data Models for Streamer Clipper.
"""
from dataclasses import dataclass

@dataclass
class WordTimestamp:
    """Represents a single word and its timing in the audio."""
    word: str
    start: float
    end: float
    confidence: float = 1.0  # משמש למטרות תאימות עם מחולל הכתוביות