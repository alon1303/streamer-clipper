import logging
import json
from pathlib import Path
from typing import Tuple, Optional
import yt_dlp
from yt_dlp.utils import download_range_func
from chat_downloader import ChatDownloader

logger = logging.getLogger(__name__)

class VideoDownloader:
    def __init__(self, temp_dir: str = "temp"):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"VideoDownloader initialized. Temp directory: {self.temp_dir}")

    def download_chat(self, url: str, video_id: str, duration_limit: Optional[int] = None) -> Optional[Path]:
        logger.info("Downloading full chat via yt-dlp (Twitch API restricts partial downloads)...")
        
        ydl_opts = {
            'skip_download': True,         # מוריד רק את הצ'אט, מדלג על הוידאו והאודיו!
            'writesubtitles': True,
            'subtitleslangs': ['rechat', 'live_chat'], # 'rechat' זה הפורמט של טוויץ'
            'subtitlesformat': 'vtt',      # נמיר ל-VTT כדי שיהיה קל לנתח
            'outtmpl': str(self.temp_dir / f"{video_id}.%(ext)s"),
            'quiet': False                 # משאיר את הלוגים כדי שתראה שזה רץ ולא תקוע
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
            # חיפוש קובץ ה-VTT שנוצר
            for file in self.temp_dir.glob(f"{video_id}*.vtt"):
                logger.info(f"✅ Chat downloaded successfully: {file.name}")
                return file
                
            logger.error("Chat file not found after download.")
            return None
        except Exception as e:
            logger.error(f"Failed to download chat via yt-dlp: {e}")
            return None
        
            
    def download(self, url: str, duration_limit_seconds: Optional[int] = None) -> Optional[Tuple[Path, Path, Optional[Path]]]:
        # 1. משיכת מזהה הסרטון
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                video_id = info.get('id', 'unknown')
        except Exception as e:
            logger.error(f"Failed to fetch video info: {e}")
            return None

        # 2. הורדת הצ'אט תחילה (מהיר ומוגבל בזמן)
        chat_path = self.download_chat(url, video_id, duration_limit_seconds)
        
        if not chat_path:
            logger.error("❌ No Live Chat found or failed to download! Aborting to save time.")
            return None

        # 3. הורדת הוידאו והאודיו
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
            'quiet': False,
            'no_warnings': True,
            # ביטלנו כאן את הורדת הכתוביות של yt-dlp כי אנחנו משתמשים ב-chat-downloader
        }
        
        if duration_limit_seconds:
            logger.info(f"Test mode: Limiting video download to first {duration_limit_seconds} seconds.")
            ydl_opts['download_ranges'] = download_range_func(None, [(0, duration_limit_seconds)])
        
        try:
            logger.info(f"Starting video/audio download for URL: {url}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
                video_path = self.temp_dir / f"{video_id}.mp4"
                audio_path = self.temp_dir / f"{video_id}.mp3"
                
                if video_path.exists() and audio_path.exists():
                    logger.info("✅ Successfully downloaded video and audio files.")
                    return video_path, audio_path, chat_path
                else:
                    logger.error("Download completed but video/audio files are missing.")
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to download video: {e}")
            return None