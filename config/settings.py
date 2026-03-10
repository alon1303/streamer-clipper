"""
Configuration management for the ShortsGenerator application.
Handles environment variables, default values, and validation.
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from pydantic import Field, validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

class Settings(BaseSettings):
    """
    Application settings with environment variable support.
    Uses pydantic for validation and type conversion.
    """
    
    # Application
    APP_NAME: str = "ShortsGenerator Backend v2"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1
    
    # File paths
    BASE_DIR: Path = Path(__file__).parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    OUTPUT_DIR: Path = BASE_DIR / "outputs"
    DATA_DIR: Path = BASE_DIR / "data"
    CACHE_DIR: Path = BASE_DIR / "cache"
    ASSETS_DIR: Path = BASE_DIR / "assets"
    BACKGROUNDS_DIR: Path = ASSETS_DIR / "backgrounds"
    
    # File upload settings
    MAX_FILE_SIZE_MB: int = 100
    ALLOWED_EXTENSIONS: Union[str, List[str]] = [".mp4", ".avi", ".mkv", ".mov", ".webm"]
    
    # Reddit Settings (using public JSON endpoints - no API keys required)
    REDDIT_USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    # Reddit story settings
    DEFAULT_SUBREDDIT: str = "AskReddit"
    DEFAULT_TIME_FILTER: str = "day"  # hour, day, week, month, year, all
    MIN_STORY_SCORE: int = 100
    MIN_STORY_LENGTH: int = 200  # characters
    MAX_STORY_LENGTH: int = 5000  # characters
    EXCLUDE_NSFW: bool = True
    WORDS_PER_MINUTE: int = 150  # Narration speed
    
    # ElevenLabs API Settings (for Phase 2)
    ELEVENLABS_API_KEY: Optional[str] = None
    ELEVENLABS_VOICE_RACHEL: str = "21m00Tcm4TlvDq8ikWAM"  # Professional female
    ELEVENLABS_VOICE_ADAM: str = "pNInz6obpgDQGcFmaJgB"    # Deep male
    ELEVENLABS_VOICE_ELLI: str = "MF3mGyEYCl7XYWbV9V6O"    # Young female
    ELEVENLABS_VOICE_JOSH: str = "TxGEqnHWrfWFTfGW9XjX"    # Casual male
    
    # Edge TTS Voices (for TTS_ENGINE = "edge")
    EDGE_TTS_VOICE_FEMALE: str = "en-US-AriaNeural"        # Female voice
    EDGE_TTS_VOICE_MALE: str = "en-US-ChristopherNeural"   # Male voice
    
    DEFAULT_VOICE_ID: str = EDGE_TTS_VOICE_FEMALE  # Default to female Edge TTS voice
    
    # Edge TTS alias mapping for get_voice_id method
    EDGE_TTS_ALIASES: Dict[str, str] = Field(
        default_factory=lambda: {
            "female": "en-US-AriaNeural",
            "male": "en-US-ChristopherNeural", 
            "aria": "en-US-AriaNeural",
            "christopher": "en-US-ChristopherNeural",
            "default": "en-US-AriaNeural",
        },
        description="Mapping of voice aliases to Edge TTS voice IDs"
    )
    
    # TTS Engine Configuration
    TTS_ENGINE: str = "edge"  # "edge" or "elevenlabs"
    
    # Background video settings
    DEFAULT_BACKGROUND_THEME: str = "minecraft"
    BACKGROUND_THEMES: List[str] = ["minecraft", "abstract", "nature", "lofi"]
    MIN_BACKGROUND_DURATION: int = 60  # seconds
    MAX_BACKGROUND_DURATION: int = 300  # seconds
    
    # Video processing
    TARGET_WIDTH: int = 1080
    TARGET_HEIGHT: int = 1920
    TARGET_FPS: int = 30
    VIDEO_CRF: int = 23  # Quality (0-51, lower is better)
    VIDEO_PRESET: str = "veryfast"
    AUDIO_BITRATE: str = "128k"
    
    # Story segmentation
    MIN_PART_DURATION: int = 30  # seconds
    MAX_PART_DURATION: int = 60  # seconds
    MAX_PARTS: int = 5
    
    # Caching
    CACHE_TTL: int = 3600  # 1 hour in seconds
    ENABLE_CACHE: bool = True
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Allow extra environment variables (e.g., Google OAuth)
    
    @validator("UPLOAD_DIR", "OUTPUT_DIR", "DATA_DIR", "CACHE_DIR", "ASSETS_DIR", "BACKGROUNDS_DIR", pre=True)
    def validate_and_create_dirs(cls, v: Path) -> Path:
        """Validate and create directories if they don't exist."""
        if isinstance(v, str):
            v = Path(v)
        v.mkdir(parents=True, exist_ok=True)
        return v
    
    @validator("REDDIT_USER_AGENT")
    def validate_reddit_user_agent(cls, v, values):
        """Validate Reddit user agent is set."""
        if not v or v == "ShortsGenerator/1.0 by YourUsername":
            print(f"Warning: Using default Reddit user agent. Consider setting a custom REDDIT_USER_AGENT.")
        return v
    
    @validator("ALLOWED_EXTENSIONS", pre=True)
    def parse_allowed_extensions(cls, v):
        """Parse ALLOWED_EXTENSIONS from comma-separated string or list."""
        if isinstance(v, str):
            # Split by comma and strip whitespace
            extensions = [ext.strip() for ext in v.split(",") if ext.strip()]
            return extensions
        return v
    
    @validator("ELEVENLABS_API_KEY")
    def validate_elevenlabs_key(cls, v, values):
        """Validate ElevenLabs API key is set if TTS features are enabled."""
        # Only warn if not set, don't fail since TTS might not be needed
        if not v:
            print(f"Warning: ElevenLabs API key not set. TTS features will be disabled.")
        return v
    
    def get_allowed_extensions_set(self) -> set:
        """Get allowed file extensions as a set."""
        return set(self.ALLOWED_EXTENSIONS)
    
    def get_max_file_size_bytes(self) -> int:
        """Get maximum file size in bytes."""
        return self.MAX_FILE_SIZE_MB * 1024 * 1024
    
    def get_backgrounds_by_theme(self, theme: str) -> List[Path]:
        """Get list of background videos for a specific theme."""
        theme_dir = self.BACKGROUNDS_DIR / theme
        if not theme_dir.exists():
            return []
        
        video_files = []
        for ext in self.ALLOWED_EXTENSIONS:
            video_files.extend(list(theme_dir.glob(f"*{ext}")))
        
        return video_files
    
    def get_random_background(self, theme: Optional[str] = None) -> Optional[Path]:
        """Get a random background video path for the specified theme."""
        import random
        
        theme = theme or self.DEFAULT_BACKGROUND_THEME
        backgrounds = self.get_backgrounds_by_theme(theme)
        
        if not backgrounds:
            # Fallback to any available background
            all_backgrounds = []
            for t in self.BACKGROUND_THEMES:
                all_backgrounds.extend(self.get_backgrounds_by_theme(t))
            
            if not all_backgrounds:
                return None
            
            return random.choice(all_backgrounds)
        
        return random.choice(backgrounds)
    
    def is_reddit_configured(self) -> bool:
        """Check if Reddit is configured (always true for public endpoints)."""
        return True  # Always true since we use public JSON endpoints
    
    def is_elevenlabs_configured(self) -> bool:
        """Check if ElevenLabs API is properly configured."""
        return bool(self.ELEVENLABS_API_KEY)
    
    def get_voice_id(self, voice_name: Optional[str] = None) -> str:
        """
        Get voice ID by name or return default.
        Returns appropriate voice ID based on TTS_ENGINE setting.
        """
        # Determine which voice map to use based on TTS engine
        if self.TTS_ENGINE.lower() == "edge":
            if voice_name:
                voice_lower = voice_name.lower()
                # Check if it's a known alias
                if voice_lower in self.EDGE_TTS_ALIASES:
                    return self.EDGE_TTS_ALIASES[voice_lower]
                # Check if it's already a valid Edge TTS voice ID (contains "Neural")
                elif "neural" in voice_lower or "en-" in voice_lower:
                    return voice_name  # Assume it's already a valid Edge TTS voice ID
            # Return default Edge TTS voice
            return self.DEFAULT_VOICE_ID
            
        elif self.TTS_ENGINE.lower() == "elevenlabs":
            # ElevenLabs voice mapping
            elevenlabs_voice_map = {
                "rachel": self.ELEVENLABS_VOICE_RACHEL,
                "adam": self.ELEVENLABS_VOICE_ADAM,
                "elli": self.ELEVENLABS_VOICE_ELLI,
                "josh": self.ELEVENLABS_VOICE_JOSH,
            }
            
            if voice_name and voice_name.lower() in elevenlabs_voice_map:
                return elevenlabs_voice_map[voice_name.lower()]
            # Return default ElevenLabs voice (if configured) or fallback
            if self.is_elevenlabs_configured():
                return self.ELEVENLABS_VOICE_RACHEL
            else:
                # Fall back to Edge TTS if ElevenLabs not configured
                logger = logging.getLogger(__name__)
                logger.warning("ElevenLabs not configured, falling back to Edge TTS")
                self.TTS_ENGINE = "edge"
                return self.EDGE_TTS_VOICE_FEMALE
        
        # Default case (shouldn't happen)
        return self.DEFAULT_VOICE_ID
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary for API responses."""
        return {
            "app": {
                "name": self.APP_NAME,
                "version": self.APP_VERSION,
                "debug": self.DEBUG,
            },
            "server": {
                "host": self.HOST,
                "port": self.PORT,
                "workers": self.WORKERS,
            },
            "paths": {
                "base_dir": str(self.BASE_DIR),
                "upload_dir": str(self.UPLOAD_DIR),
                "output_dir": str(self.OUTPUT_DIR),
                "cache_dir": str(self.CACHE_DIR),
                "assets_dir": str(self.ASSETS_DIR),
                "backgrounds_dir": str(self.BACKGROUNDS_DIR),
            },
            "reddit": {
                "configured": self.is_reddit_configured(),
                "default_subreddit": self.DEFAULT_SUBREDDIT,
                "default_time_filter": self.DEFAULT_TIME_FILTER,
            },
            "elevenlabs": {
                "configured": self.is_elevenlabs_configured(),
                "default_voice": self.DEFAULT_VOICE_ID,
            },
            "video": {
                "target_resolution": f"{self.TARGET_WIDTH}x{self.TARGET_HEIGHT}",
                "target_fps": self.TARGET_FPS,
                "quality_crf": self.VIDEO_CRF,
                "preset": self.VIDEO_PRESET,
            },
            "story": {
                "min_part_duration": self.MIN_PART_DURATION,
                "max_part_duration": self.MAX_PART_DURATION,
                "max_parts": self.MAX_PARTS,
                "words_per_minute": self.WORDS_PER_MINUTE,
            },
        }


# Global settings instance
settings = Settings()

# Create necessary directories
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
settings.ASSETS_DIR.mkdir(parents=True, exist_ok=True)
settings.BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)

# Create theme directories
for theme in settings.BACKGROUND_THEMES:
    theme_dir = settings.BACKGROUNDS_DIR / theme
    theme_dir.mkdir(parents=True, exist_ok=True)


def print_settings_summary():
    """Print a summary of the current settings."""
    print("=" * 60)
    print(f"{settings.APP_NAME} v{settings.APP_VERSION}")
    print("=" * 60)
    
    print("\n📁 Directories:")
    print(f"  Uploads: {settings.UPLOAD_DIR}")
    print(f"  Outputs: {settings.OUTPUT_DIR}")
    print(f"  Cache: {settings.CACHE_DIR}")
    print(f"  Assets: {settings.ASSETS_DIR}")
    print(f"  Backgrounds: {settings.BACKGROUNDS_DIR}")
    
    print("\n🔧 Reddit Configuration:")
    print(f"  Configured: {settings.is_reddit_configured()}")
    if settings.is_reddit_configured():
        print(f"  Default Subreddit: r/{settings.DEFAULT_SUBREDDIT}")
        print(f"  Time Filter: {settings.DEFAULT_TIME_FILTER}")
    
    print("\n🎙️ ElevenLabs Configuration:")
    print(f"  Configured: {settings.is_elevenlabs_configured()}")
    if settings.is_elevenlabs_configured():
        print(f"  Default Voice: {settings.DEFAULT_VOICE_ID}")
    
    print("\n🎬 Video Settings:")
    print(f"  Resolution: {settings.TARGET_WIDTH}x{settings.TARGET_HEIGHT}")
    print(f"  FPS: {settings.TARGET_FPS}")
    print(f"  Quality (CRF): {settings.VIDEO_CRF}")
    print(f"  Preset: {settings.VIDEO_PRESET}")
    
    print("\n📖 Story Settings:")
    print(f"  Part Duration: {settings.MIN_PART_DURATION}-{settings.MAX_PART_DURATION}s")
    print(f"  Max Parts: {settings.MAX_PARTS}")
    print(f"  Narration Speed: {settings.WORDS_PER_MINUTE} wpm")
    
    print("\n🎨 Background Themes:")
    for theme in settings.BACKGROUND_THEMES:
        theme_dir = settings.BACKGROUNDS_DIR / theme
        bg_count = len(list(theme_dir.glob("*")))
        print(f"  {theme.capitalize()}: {bg_count} files")
    
    print("=" * 60)


if __name__ == "__main__":
    # Print settings summary when run directly
    print_settings_summary()