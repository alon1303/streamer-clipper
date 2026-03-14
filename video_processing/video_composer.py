"""
Smart Streamer Clipper Pipeline.
Uses Chat Velocity (Hype) to find clips, transcribes only small chunks, and renders vertical video.
"""

import os
import re
import tempfile
import subprocess
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional
import ffmpeg
import logging

from core.transcriber import AudioTranscriber
from core.ai_analyzer import AIAnalyzer
from core.chat_analyzer import ChatAnalyzer
from core.models import WordTimestamp
from video_processing.subtitle_generator import SubtitleGenerator, WordTimestamp as SubtitleWordTimestamp

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_video_dimensions(input_path: str) -> Tuple[int, int]:
    try:
        probe = ffmpeg.probe(input_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        if video_stream:
            return int(video_stream['width']), int(video_stream['height'])
    except Exception as e:
        logger.error(f"Error getting video dimensions: {e}")
    return 1920, 1080

def get_video_framerate(input_path: str) -> float:
    try:
        probe = ffmpeg.probe(input_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        if video_stream:
            fps_str = video_stream.get('avg_frame_rate', '30/1')
            if '/' in fps_str:
                num, den = map(int, fps_str.split('/'))
                return num / den
            return float(fps_str)
    except Exception as e:
        logger.error(f"Error getting video framerate: {e}")
    return 30.0

def adjust_timestamps_for_clip(words: List[WordTimestamp], start_time: float, end_time: float) -> List[SubtitleWordTimestamp]:
    clip_words = []
    for w in words:
        if w.end > start_time and w.start < end_time:
            new_start = max(0.0, w.start - start_time)
            new_end = max(0.0, w.end - start_time)
            clip_words.append(SubtitleWordTimestamp(word=w.word, start=new_start, end=new_end, confidence=w.confidence))
    return clip_words

def generate_ass_subtitles(clip_words: List[SubtitleWordTimestamp], output_path: str, video_width: int = 1080, video_height: int = 1920) -> bool:
    try:
        if not clip_words:
            return False
        audio_duration = max(word.end for word in clip_words)
        generator = SubtitleGenerator(video_width=video_width, video_height=video_height)
        return generator.generate_ass_from_word_timestamps(clip_words, audio_duration, Path(output_path))
    except Exception as e:
        logger.error(f"Error generating ASS subtitles: {e}")
        return False

def calculate_crop_parameters(width: int, height: int) -> Tuple[str, str, str, str]:
    target_aspect_w, target_aspect_h = 9, 16
    if width / height > target_aspect_w / target_aspect_h:
        crop_height = height
        crop_width = int(height * target_aspect_w / target_aspect_h)
    else:
        crop_width = width
        crop_height = int(width * target_aspect_h / target_aspect_w)
    x_offset = max(0, (width - crop_width) // 2)
    y_offset = max(0, (height - crop_height) // 2)
    return str(crop_width), str(crop_height), str(x_offset), str(y_offset)

def reframe_to_916_with_subtitles(input_path: str, output_path: str, subtitle_path: str, start_time: float, duration: float) -> bool:
    try:
        width, height = get_video_dimensions(input_path)
        fps = get_video_framerate(input_path)
        crop_w, crop_h, x, y = calculate_crop_parameters(width, height)
        
        subtitle_dir = os.path.dirname(subtitle_path)
        subtitle_filename = os.path.basename(subtitle_path)
        
        abs_input_path = os.path.abspath(input_path)
        abs_output_path = os.path.abspath(output_path)
        
        input_stream = ffmpeg.input(abs_input_path, ss=start_time, t=duration)
        video = input_stream.video.filter('crop', crop_w, crop_h, x, y).filter('scale', 1080, 1920).filter('subtitles', subtitle_filename)
        
        cmd = ffmpeg.output(
            video, input_stream.audio, abs_output_path,
            vcodec='libx264', crf=23, preset='fast', pix_fmt='yuv420p',
            acodec='aac', audio_bitrate='128k', movflags='+faststart', r=fps
        ).overwrite_output().compile()
        
        original_cwd = os.getcwd()
        try:
            os.chdir(subtitle_dir)
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        finally:
            os.chdir(original_cwd)
            
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        return False

def extract_audio_segment(input_audio: str, output_audio: str, start_time: float, duration: float) -> bool:
    try:
        subprocess.run([
            'ffmpeg', '-y', '-ss', str(start_time), '-t', str(duration),
            '-i', input_audio, '-c', 'copy', output_audio
        ], capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to extract audio segment: {e.stderr}")
        return False

def process_stream_into_clips(input_video_path: str, input_audio_path: str, chat_path: Optional[str], output_dir: str) -> Dict[str, Any]:
    """
    מנהל את כל תהליך יצירת הקליפים.
    מעודכן: אם אין צ'אט או אין הייפ, הפונקציה עוצרת מיד.
    """
    try:
        logger.info(f"Starting Smart Streamer Clipper pipeline for: {input_video_path}")
        os.makedirs(output_dir, exist_ok=True)
        
        if not chat_path or not os.path.exists(chat_path):
            logger.error("❌ CRITICAL ERROR: Chat file is missing. Aborting pipeline as requested.")
            return {'success': False, 'error': 'Missing chat file'}
        
        transcriber = AudioTranscriber()
        analyzer = AIAnalyzer()
        chat_analyzer = ChatAnalyzer()
        
        processed_files = []
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # שלב 1: מציאת ההייפ מהצ'אט
            logger.info("Step 1: Analyzing Chat for Hype Moments...")
            hype_moments = chat_analyzer.find_hype_moments(Path(chat_path), top_k=5, clip_duration=60)
            
            if not hype_moments:
                logger.error("❌ ERROR: No hype moments found in chat. Aborting to save tokens.")
                return {'success': False, 'error': 'No hype moments detected'}
                
            logger.info(f"✅ Found {len(hype_moments)} viral moments based on chat velocity.")
            
            # שלב 2: עיבוד נקודתי של כל רגע הייפ
            for idx, hype in enumerate(hype_moments, 1):
                base_start = hype['start_time']
                base_end = hype['end_time']
                chunk_duration = base_end - base_start
                
                logger.info(f"\n--- Processing Hype Moment {idx}/{len(hype_moments)} ---")
                
                # גוזרים רק את האודיו הספציפי
                chunk_audio = temp_path / f"chunk_{idx}.mp3"
                if not extract_audio_segment(input_audio_path, str(chunk_audio), base_start, chunk_duration):
                    continue
                
                # תמלול נקודתי
                words = transcriber.transcribe(chunk_audio, language="en")
                if not words:
                    continue
                
                # ניתוח AI לזיקוק הקליפ
                clips = analyzer.find_viral_clips(words)
                if not clips:
                    continue
                    
                best_clip = clips[0]
                relative_start = float(best_clip.get("start_time", 0))
                relative_end = float(best_clip.get("end_time", chunk_duration))
                title = best_clip.get("title", f"viral_clip_{idx}")
                
                absolute_start = base_start + relative_start
                absolute_end = base_start + relative_end
                clip_duration = absolute_end - absolute_start
                
                clean_title = re.sub(r'[^a-zA-Z0-9א-ת]', '_', title).strip('_')
                final_output = Path(output_dir) / f"{clean_title}.mp4"
                subtitle_file = temp_path / f"subs_{idx}.ass"
                
                # יצירת כתוביות וחיתוך
                clip_words = adjust_timestamps_for_clip(words, relative_start, relative_end)
                if generate_ass_subtitles(clip_words, str(subtitle_file)):
                    if reframe_to_916_with_subtitles(input_video_path, str(final_output), str(subtitle_file), absolute_start, clip_duration):
                        processed_files.append(str(final_output))
                        logger.info(f"✅ Created: {final_output.name}")
                    
            return {
                'success': True,
                'videos_created': len(processed_files),
                'files': processed_files
            }
            
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        return {'success': False, 'error': str(e)}