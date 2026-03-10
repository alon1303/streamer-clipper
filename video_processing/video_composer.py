"""
Video Composer for Streamer Clipper.
Takes a vertical (9:16) cropped video and bakes dynamic subtitles onto it.
"""

import logging
import subprocess
from pathlib import Path
from typing import List

from core.models import WordTimestamp
from video_processing.subtitle_generator import SubtitleGenerator

# Configure logging
logger = logging.getLogger(__name__)

class VideoComposer:
    """Composes the final vertical video by baking subtitles into it."""
    
    def __init__(self):
        logger.info("VideoComposer initialized for Streamer Clipper")
    
    def create_subtitles(
        self,
        word_timestamps: List[WordTimestamp],
        audio_duration: float,
        output_path: Path
    ) -> bool:
        """
        Creates the ASS subtitle file using exact word timestamps.
        
        Args:
            word_timestamps: List of WordTimestamp objects from the transcription AI
            audio_duration: Duration of the video/audio clip in seconds
            output_path: Path to save the .ass file
            
        Returns:
            True if successful, False otherwise
        """
        generator = SubtitleGenerator(
            video_width=1080,
            video_height=1920,
            max_words_per_phrase=5,
            min_words_per_phrase=2,
            max_phrase_duration=3.0,
            min_gap_between_phrases=0.1
        )
        
        logger.info(f"Generating subtitles for {len(word_timestamps)} words...")
        
        success = generator.generate_ass_from_word_timestamps(
            word_timestamps=word_timestamps,
            audio_duration=audio_duration,
            output_path=output_path
        )
        
        if not success:
            logger.error("Failed to generate ASS subtitles")
            
        return success

    def bake_subtitles_to_video(
        self,
        video_path: Path,
        subtitle_path: Path,
        output_path: Path
    ) -> bool:
        """
        Bakes the ASS subtitles into the video using FFmpeg.
        Assumes the input video is already cropped to 9:16.
        
        Args:
            video_path: Path to the cropped 9:16 video (contains original audio)
            subtitle_path: Path to the generated .ass file
            output_path: Path to save the final MP4 video
            
        Returns:
            True if successful, False otherwise
        """
        if not video_path.exists():
            logger.error(f"Input video not found: {video_path}")
            return False
            
        if not subtitle_path.exists():
            logger.error(f"Subtitle file not found: {subtitle_path}")
            return False

        try:
            # Note: We need to escape backslashes for Windows paths in the FFmpeg filter
            safe_subtitle_path = str(subtitle_path).replace('\\', '\\\\')
            
            cmd = [
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vf', f"subtitles='{safe_subtitle_path}'",
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-crf', '23',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'copy',  # Just copy the original audio, no need to re-encode!
                '-movflags', '+faststart',
                str(output_path)
            ]
            
            logger.info(f"Baking subtitles into video: {video_path.name}")
            logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg failed: {result.stderr}")
                return False
            
            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.error(f"Output file not created or is empty: {output_path}")
                return False
            
            logger.info(f"Final vertical video created successfully: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Exception during video composition: {e}")
            return False