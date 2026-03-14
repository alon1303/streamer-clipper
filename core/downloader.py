import logging
import subprocess
import json
import re
from pathlib import Path
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class VideoDownloader:
    def __init__(self, temp_dir: str = "temp"):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.cli_path = "./TwitchDownloaderCLI.exe" 
        logger.info(f"VideoDownloader initialized. Temp directory: {self.temp_dir}")

    def _extract_video_id(self, url: str) -> Optional[str]:
        match = re.search(r"videos/(\d+)", url)
        return match.group(1) if match else None

    def _optimize_chat_file(self, json_path: Path):
        """קורא את ה-JSON המלא ומשאיר רק רשימת זמנים (Timestamps)."""
        try:
            logger.info(f"Optimizing chat file for analysis...")
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            comments = data.get('comments', [])
            timestamps = [comment.get('content_offset_seconds') for comment in comments]
            timestamps = [t for t in timestamps if t is not None]
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({"timestamps": timestamps}, f)
                
            logger.info(f"✅ Optimization complete. Kept {len(timestamps)} messages.")
        except Exception as e:
            logger.error(f"Failed to optimize chat JSON: {e}")

    def download_chat(self, video_id: str, duration_limit: int) -> Optional[Path]:
        """מוריד את הצ'אט ומציג התקדמות בזמן אמת בטרמינל."""
        output_path = self.temp_dir / f"{video_id}_chat.json"
        logger.info(f"Downloading Twitch chat for ID: {video_id} (0 to {duration_limit}s)")
        
        try:
            cmd = [
                self.cli_path, "chatdownload",
                "--id", video_id,
                "-b", "0s",
                "-e", f"{duration_limit}s",
                "-o", str(output_path)
            ]
            
            # הרצה ללא capture_output כדי שהמשתמש יראה את הפלט בטרמינל
            result = subprocess.run(cmd)
            
            if result.returncode == 0 and output_path.exists():
                self._optimize_chat_file(output_path)
                return output_path
            return None
        except Exception as e:
            logger.error(f"Failed to download chat: {e}")
            return None

    def download(self, url: str, duration_limit_seconds: int = 1800):
        """מתודה לשימוש ב-Test בלבד להורדת צ'אט."""
        video_id = self._extract_video_id(url)
        if not video_id: return None
        return self.download_chat(video_id, duration_limit_seconds)