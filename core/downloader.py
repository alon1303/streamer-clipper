"""
Video Downloader for Streamer Clipper.
Uses yt-dlp to download video, extract audio, and fetch live chat/subtitles for hype detection.
"""

import logging
from pathlib import Path
from typing import Tuple, Optional
import yt_dlp
from yt_dlp.utils import download_range_func

# Configure logging
logger = logging.getLogger(__name__)

class VideoDownloader:
    """Handles downloading videos, audio, and chat logs."""
    
    def __init__(self, temp_dir: str = "temp"):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"VideoDownloader initialized. Temp directory: {self.temp_dir}")

    def download(self, url: str, duration_limit_seconds: Optional[int] = None) -> Optional[Tuple[Path, Path, Optional[Path]]]:
        """
        Downloads a video, extracts audio, and fetches chat/subtitles.
        If duration_limit_seconds is provided, downloads only that portion from the start.
        """
        output_template = str(self.temp_dir / "%(id)s.%(ext)s")
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_template,
            'keepvideo': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'writesubtitles': True,
            'subtitleslangs': ['live_chat', 'rechat', 'en'], 
            'subtitlesformat': 'vtt',
            'quiet': False,
            'no_warnings': True,
        }
        
        # הוספת מגבלת הזמן בצורה דינמית עבור טסטים
        if duration_limit_seconds:
            logger.info(f"Test mode: Limiting download to first {duration_limit_seconds} seconds.")
            ydl_opts['download_ranges'] = download_range_func(None, [(0, duration_limit_seconds)])
        
        try:
            logger.info(f"Starting download for URL: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                video_id = info_dict.get('id', 'unknown')
                
                video_path = self.temp_dir / f"{video_id}.mp4"
                audio_path = self.temp_dir / f"{video_id}.mp3"
                
                chat_path = None
                for file in self.temp_dir.glob(f"{video_id}*.vtt"):
                    chat_path = file
                    break
                
                if video_path.exists() and audio_path.exists():
                    logger.info("Successfully downloaded files.")
                    return video_path, audio_path, chat_path
                else:
                    logger.error("Download completed but files are missing.")
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to download video: {e}")
            return None