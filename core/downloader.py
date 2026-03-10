"""
Video Downloader for Streamer Clipper.
Uses yt-dlp to download video and extract audio for processing.
"""

import logging
from pathlib import Path
from typing import Tuple, Optional
import yt_dlp

# Configure logging
logger = logging.getLogger(__name__)

class VideoDownloader:
    """Handles downloading videos and extracting audio from various platforms."""
    
    def __init__(self, temp_dir: str = "temp"):
        """
        Initializes the downloader and ensures the temp directory exists.
        """
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"VideoDownloader initialized. Temp directory: {self.temp_dir}")

    def download(self, url: str) -> Optional[Tuple[Path, Path]]:
        """
        Downloads a video and extracts its audio.
        
        Args:
            url: The URL of the video (YouTube, Twitch, etc.)
            
        Returns:
            A tuple containing (video_path, audio_path) if successful, None otherwise.
        """
        # We define the output template to use the video's unique ID
        output_template = str(self.temp_dir / "%(id)s.%(ext)s")
        
        ydl_opts = {
            # Download best video (MP4) and best audio, or fallback to best single file
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_template,
            'keepvideo': True,  # CRITICAL: Keep the video file after extracting audio
            'postprocessors': [{
                # Extract audio to MP3 using FFmpeg
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': False,
            'no_warnings': True,
        }
        
        try:
            logger.info(f"Starting download for URL: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info and download
                info_dict = ydl.extract_info(url, download=True)
                video_id = info_dict.get('id', 'unknown')
                
                # yt-dlp saves the video as <id>.mp4 and audio as <id>.mp3
                video_path = self.temp_dir / f"{video_id}.mp4"
                audio_path = self.temp_dir / f"{video_id}.mp3"
                
                if video_path.exists() and audio_path.exists():
                    logger.info(f"Successfully downloaded video: {video_path.name}")
                    logger.info(f"Successfully extracted audio: {audio_path.name}")
                    return video_path, audio_path
                else:
                    logger.error("Download completed but files are missing in temp folder.")
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to download video: {e}")
            return None

# Example usage for testing the module directly
if __name__ == "__main__":
    # Setup basic logging for the test
    logging.basicConfig(level=logging.INFO)
    
    downloader = VideoDownloader()
    # Using a short non-copyrighted or public domain video for testing is recommended
    test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw" # "Me at the zoo" (First YT video, very short)
    
    result = downloader.download(test_url)
    if result:
        vid_path, aud_path = result
        print(f"Success! Video: {vid_path}, Audio: {aud_path}")
    else:
        print("Download failed.")