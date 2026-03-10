"""
Video Composer for Reddit Stories Shorts.
Combines audio narration with background videos and adds Shorts-style subtitles.
"""

import logging
import tempfile
import subprocess
import json
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import uuid

from config.settings import settings
from .background_manager import BackgroundManager
from .models import AudioChunk, WordTimestamp
from .subtitle_generator import SubtitleGenerator, generate_subtitles
from .audio_utils import analyze_audio_for_offset, adjust_word_timestamps, detect_silence_at_beginning
from .image_generator_new import TitlePopupTimingCalculator, RedditImageGenerator
from .audio_mixer import AudioMixer

# Configure logging
logger = logging.getLogger(__name__)

class VideoComposer:
    """Composes Shorts videos by combining audio, background, and subtitles."""
    
    def __init__(self, background_manager: Optional[BackgroundManager] = None):
        """
        Initialize video composer.
        
        Args:
            background_manager: Optional BackgroundManager instance
        """
        self.background_manager = background_manager or BackgroundManager()
        self.audio_mixer = AudioMixer()
        
        logger.info("VideoComposer initialized")
    
    def create_subtitles_for_text(
        self,
        text: str,
        audio_duration: float,
        output_path: Path,
        word_timestamps: Optional[List[WordTimestamp]] = None,
        audio_path: Optional[Path] = None,
        title_offset: float = 0.0,
        title_word_count: int = 0
    ) -> bool:
        """
        Create ASS subtitles for text with word-level highlighting.
        Uses the new SubtitleGenerator for perfect timing and no overlaps.
        
        Args:
            text: Text to create subtitles for
            audio_duration: Duration of the audio in seconds
            output_path: Path where subtitles will be saved
            word_timestamps: Optional list of WordTimestamp objects for precise word timing
            audio_path: Optional path to audio file for offset detection
            title_offset: Offset to apply to all subtitle timestamps (for title audio)
            title_word_count: Number of title words to filter out from subtitles (if > 0)
            
        Returns:
            True if successful, raises exception otherwise
        """
        # Create subtitle generator
        generator = SubtitleGenerator(
            video_width=1080,
            video_height=1920,
            max_words_per_phrase=5,
            min_words_per_phrase=2,
            max_phrase_duration=3.0,
            min_gap_between_phrases=0.1
        )
        
        # Apply audio offset correction if audio_path is provided
        adjusted_word_timestamps = word_timestamps
        if audio_path and audio_path.exists() and word_timestamps:
            # Detect silence at beginning of audio
            silence_offset = detect_silence_at_beginning(audio_path)
            if silence_offset > 0.05:  # More than 50ms of silence
                logger.info(f"Detected {silence_offset:.3f}s silence at beginning of audio, adjusting subtitles")
                adjusted_word_timestamps = adjust_word_timestamps(word_timestamps, -silence_offset)
        
        if adjusted_word_timestamps:
            # If title_word_count is provided, filter out title words from subtitles
            if title_word_count > 0:
                # When using title filter, timestamps are already absolute and should NOT be shifted
                # The title offset is already accounted for in the absolute timestamps
                # So we skip applying title_offset adjustment for title_word_count > 0
                success, _ = generator.generate_ass_with_title_filter(
                    word_timestamps=adjusted_word_timestamps,
                    title_word_count=title_word_count,
                    audio_duration=audio_duration + title_offset,
                    output_path=output_path
                )
                if not success:
                    raise RuntimeError("Failed to generate subtitles with title filter")
                return True
            else:
                # Apply title offset only when NOT using title filter (title_word_count <= 0)
                if title_offset > 0 and adjusted_word_timestamps:
                    logger.info(f"Applying title offset: {title_offset:.3f}s")
                    adjusted_word_timestamps = adjust_word_timestamps(adjusted_word_timestamps, title_offset)
                
                # Use precise word timestamps from ElevenLabs (with offset correction if needed)
                success = generator.generate_ass_from_word_timestamps(
                    word_timestamps=adjusted_word_timestamps,
                    audio_duration=audio_duration + title_offset,  # Total duration includes title offset
                    output_path=output_path
                )
                if not success:
                    raise RuntimeError("Failed to generate subtitles from word timestamps")
                return True
        else:
            # Generate simulated timestamps from text
            # This will raise RuntimeError if it fails
            return generator.generate_ass_from_text(
                text=text,
                audio_duration=audio_duration + title_offset,  # Total duration includes title offset
                output_path=output_path
            )
    
    def combine_audio_with_background(
        self,
        audio_path: Path,
        background_path: Path,
        output_path: Path,
        subtitle_path: Optional[Path] = None,
        overlay_image_path: Optional[Path] = None,
        pop_sfx_path: Optional[Path] = None,
        timing_data: Optional[Dict[str, Any]] = None,
        hook_duration: Optional[float] = None
    ) -> bool:
        """
        Combine audio with background video and optionally add subtitles, overlay image, and pop SFX.
        Uses sequential steps to avoid complex filter_complex issues.
        
        Args:
            audio_path: Path to audio file
            background_path: Path to background video
            output_path: Path where combined video will be saved
            subtitle_path: Optional path to subtitle file
            overlay_image_path: Optional path to overlay image (Reddit post)
            pop_sfx_path: Optional path to pop sound effect
            timing_data: Optional timing data dict with 'card_start_time' and 'card_end_time'
            hook_duration: Optional hook duration in seconds (used when timing_data not provided)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get audio duration
            audio_cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(audio_path)
            ]
            
            audio_result = subprocess.run(audio_cmd, capture_output=True, text=True)
            audio_duration = float(audio_result.stdout.strip()) if audio_result.stdout else 0
            
            if audio_duration <= 0:
                logger.error(f"Invalid audio duration: {audio_duration}")
                return False
            
            # Get background video duration
            bg_cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(background_path)
            ]
            
            bg_result = subprocess.run(bg_cmd, capture_output=True, text=True)
            bg_duration = float(bg_result.stdout.strip()) if bg_result.stdout else 0
            
            # Check if background duration matches audio duration (sequential background should match)
            if bg_duration < (audio_duration - 0.5):
                logger.warning(f"Background ({bg_duration:.1f}s) is shorter than audio ({audio_duration:.1f}s), but using sequential background should have matched")
            else:
                logger.info(f"Background duration ({bg_duration:.1f}s) is sufficient for audio ({audio_duration:.1f}s)")
            
            # Create temporary directory for intermediate files
            import tempfile
            import shutil
            temp_dir = tempfile.mkdtemp()
            temp_path = Path(temp_dir)
            
            # Copy all input files to temp directory
            logger.info(f"Copying input files to temp directory: {temp_path}")
            
            # Copy audio file
            audio_temp = temp_path / audio_path.name
            shutil.copy2(audio_path, audio_temp)
            logger.debug(f"Copied audio: {audio_path} -> {audio_temp}")
            
            # Copy background video
            background_temp = temp_path / background_path.name
            shutil.copy2(background_path, background_temp)
            logger.debug(f"Copied background: {background_path} -> {background_temp}")
            
            # Copy overlay image if provided
            overlay_temp = None
            if overlay_image_path and overlay_image_path.exists():
                overlay_temp = temp_path / overlay_image_path.name
                shutil.copy2(overlay_image_path, overlay_temp)
                logger.debug(f"Copied overlay: {overlay_image_path} -> {overlay_temp}")
            
            # Copy pop SFX if provided
            pop_sfx_temp = None
            if pop_sfx_path and pop_sfx_path.exists():
                pop_sfx_temp = temp_path / pop_sfx_path.name
                shutil.copy2(pop_sfx_path, pop_sfx_temp)
                logger.debug(f"Copied pop SFX: {pop_sfx_path} -> {pop_sfx_temp}")
            
            # Copy subtitle file if provided
            subtitle_temp = None
            if subtitle_path and subtitle_path.exists():
                subtitle_temp = temp_path / subtitle_path.name
                shutil.copy2(subtitle_path, subtitle_temp)
                logger.debug(f"Copied subtitles: {subtitle_path} -> {subtitle_temp}")
            
            # Step 3: Mix audio with pop SFX if provided (using AudioMixer)
            current_audio_path = audio_temp
            if pop_sfx_temp and pop_sfx_temp.exists():
                logger.info(f"Mixing pop SFX with audio using AudioMixer: {pop_sfx_temp.name}")
                
                # Use AudioMixer for precise mixing
                mixed_audio_path = self.audio_mixer.mix_title_with_pop_sfx(
                    main_audio_path=audio_temp,
                    pop_sfx_path=pop_sfx_temp,
                    pop_start_time=0.0,  # Pop at the very beginning
                    pop_volume_delta=-6.0,  # Quieter pop sound
                    output_path=temp_path / "audio_mixed.mp3"
                )
                
                if mixed_audio_path and mixed_audio_path.exists():
                    current_audio_path = mixed_audio_path
                    logger.info(f"Audio mixed successfully: {mixed_audio_path}")
                else:
                    logger.error("Failed to mix audio with AudioMixer")
                    # Continue without pop SFX
                    logger.warning("Continuing without pop SFX")
            
            # Unified FFmpeg processing (replaces Steps 1, 2, 4)
            # Build single unified FFmpeg command
            
            # Initialize command
            cmd = ['ffmpeg', '-y']
            
            # Background Input
            cmd.extend(['-i', background_temp.name])
            
            # Overlay Input (if exists)
            overlay_input_index = None
            if overlay_temp and overlay_temp.exists():
                overlay_input_index = len(cmd) // 2  # Count inputs before adding
                cmd.extend(['-loop', '1', '-framerate', '30', '-i', overlay_temp.name])
            
            # Audio Input
            audio_input_index = len(cmd) // 2
            cmd.extend(['-i', current_audio_path.name])
            
            # Build unified filter_complex
            filter_complex = None
            
            # Determine overlay timing and animation (same logic as before)
            if overlay_temp and overlay_temp.exists():
                if timing_data and 'card_start_time' in timing_data and 'card_end_time' in timing_data:
                    card_start = timing_data['card_start_time']
                    card_end = timing_data['card_end_time']
                    
                    # Check if we have enough data to use TitlePopupTimingCalculator for pop-in animation
                    if ('title_audio_duration' in timing_data and 'buffer_seconds' in timing_data and
                        'pop_in_duration' in timing_data):
                        # Apply a small visual gap to prevent overlap with subtitles
                        visual_gap = 0.15
                        adjusted_duration = max(0.5, timing_data['title_audio_duration'] - visual_gap)
                        
                        # Create calculator for pop-in animation
                        calculator = TitlePopupTimingCalculator(
                            title_audio_duration=adjusted_duration,
                            buffer_seconds=timing_data['buffer_seconds']
                        )
                        filter_complex = calculator.get_ffmpeg_filter_for_animation(overlay_temp)
                        logger.info(f"Using pop-in animation with timing: {card_start:.2f}s to {card_end:.2f}s")
                    else:
                        # Fallback to simple scale overlay
                        visual_gap = 0.15
                        adjusted_card_end = max(0.5, card_end - visual_gap)
                        filter_complex = (
                            f'[1:v]scale=900:-1[overlay_scaled];'
                            f'[0:v][overlay_scaled]overlay=x=(W-w)/2:y=(H-h)/2:enable=\'between(t,{card_start},{adjusted_card_end})\''
                        )
                        logger.info(f"Using simple overlay timing: {card_start:.2f}s to {adjusted_card_end:.2f}s")
                else:
                    # Use hook_duration if provided, otherwise default to 4 seconds
                    card_start = 0.0
                    if hook_duration is not None and hook_duration > 0:
                        card_end = hook_duration
                        logger.info(f"Using hook_duration for overlay timing: {card_start:.2f}s to {card_end:.2f}s")
                    else:
                        # Default to first 4 seconds (legacy behavior)
                        card_end = 4.0
                        logger.info(f"Using default overlay timing: {card_start:.2f}s to {card_end:.2f}s")
                    
                    filter_complex = (
                        f'[1:v]scale=900:-1[overlay_scaled];'
                        f'[0:v][overlay_scaled]overlay=x=(W-w)/2:y=(H-h)/2:enable=\'between(t,{card_start},{card_end})\''
                    )
            
            # Add subtitles to filter_complex if provided
            if subtitle_temp and subtitle_temp.exists():
                if filter_complex:
                    # Chain subtitles after overlay
                    filter_complex += f',subtitles={subtitle_temp.name}[vout]'
                else:
                    # No overlay, just subtitles
                    filter_complex = f'[0:v]subtitles={subtitle_temp.name}[vout]'
            elif filter_complex:
                # No subtitles, but overlay exists - need output pad
                filter_complex += '[vout]'
            
            # Add filters and mapping to command
            if filter_complex:
                cmd.extend(['-filter_complex', filter_complex])
                cmd.extend(['-map', '[vout]'])
            else:
                # No filter complex (no overlay, no subtitles)
                cmd.extend(['-map', '0:v'])  # Raw background video
            
            # Map audio stream
            # Audio input index depends on whether overlay exists
            if overlay_temp and overlay_temp.exists():
                # Overlay exists, audio is at input index 2
                cmd.extend(['-map', '2:a'])
            else:
                # No overlay, audio is at input index 1
                cmd.extend(['-map', '1:a'])
            
            # Final output settings
            cmd.extend([
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-crf', '23',
                '-pix_fmt', 'yuv420p',  # Required for YouTube compatibility
                '-c:a', 'aac',
                '-b:a', '128k',
                '-t', str(audio_duration),  # Hard-stop at audio duration
                '-movflags', '+faststart',
                output_path.name
            ])
            
            logger.info(f"Running unified FFmpeg command with {'overlay' if overlay_temp and overlay_temp.exists() else 'no overlay'}, "
                       f"{'subtitles' if subtitle_temp and subtitle_temp.exists() else 'no subtitles'}, dynamic background")
            logger.debug(f"FFmpeg command (cwd={temp_path}): {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=temp_path)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg failed: {result.stderr}")
                # Clean up temp directory
                shutil.rmtree(temp_dir, ignore_errors=True)
                return False
            
            # Copy output file from temp directory to final location
            output_temp = temp_path / output_path.name
            if output_temp.exists():
                shutil.copy2(output_temp, output_path)
                logger.debug(f"Copied output: {output_temp} -> {output_path}")
            
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            # Verify output
            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.error(f"Output file not created: {output_path}")
                return False
            
            logger.info(f"Video created successfully: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to combine audio with background: {e}")
            # Clean up temp directory if it exists
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir, ignore_errors=True)
            return False
    
    def apply_1_4x_speed(self, input_path: Path, output_path: Path) -> bool:
        try:
            cmd = [
                'ffmpeg', '-y',
                '-i', str(input_path),
                '-filter_complex', '[0:v]setpts=0.714*PTS[v];[0:a]atempo=1.4[a]',
                '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-c:a', 'aac',
                str(output_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"FFmpeg 1.4x speed failed: {result.stderr}")
                return False

            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.error("1.4x speed output file empty or missing.")
                return False

            return True
        except Exception as e:
            logger.error(f"Error applying 1.4x speed: {e}")
            return False
    
    def create_video_part(
        self,
        audio_chunk: AudioChunk,
        theme: Optional[str] = None,
        output_path: Optional[Path] = None,
        overlay_image_path: Optional[Path] = None,
        pop_sfx_path: Optional[Path] = None,
        timing_data: Optional[Dict[str, Any]] = None,
        hook_duration: Optional[float] = None
    ) -> Optional[Path]:
        """
        Create a complete video part from an audio chunk.
        
        Args:
            audio_chunk: AudioChunk with narration
            theme: Optional theme for background
            output_path: Optional output path
            overlay_image_path: Optional path to overlay image (Reddit post)
            pop_sfx_path: Optional path to pop sound effect
            timing_data: Optional timing data for overlay display
            
        Returns:
            Path to created video, raises exception on failure
        """
        # Validate audio chunk
        if not audio_chunk.audio_path.exists():
            raise FileNotFoundError(f"Audio file does not exist: {audio_chunk.audio_path}")
        
        if audio_chunk.duration_seconds <= 0:
            raise ValueError(f"Invalid audio duration: {audio_chunk.duration_seconds}")
        
        # Create output path if not provided
        if output_path is None:
            temp_dir = Path(tempfile.gettempdir())
            output_path = temp_dir / f"video_part_{uuid.uuid4()}.mp4"
        
        # Create temporary directory for intermediate files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Step 1: Create sequential background clip with dynamic changing backgrounds
            logger.info(f"Creating sequential background clip for {audio_chunk.duration_seconds:.1f}s audio")
            background_path = self.background_manager.create_sequential_background_clip(
                duration=audio_chunk.duration_seconds,
                theme=None,
                output_path=temp_path / "background.mp4",
                max_clip_duration=(audio_chunk.duration_seconds / 2.0)
            )
            
            if not background_path:
                raise RuntimeError("Failed to create background clip")
            
            # Step 2: Create subtitles
            subtitle_path = temp_path / "subtitles.ass"
            logger.info(f"Creating subtitles for text: {audio_chunk.text[:50]}...")
            
            # Extract title offset and title word count from timing_data if available
            title_offset = 0.0
            title_word_count = 0
            if timing_data:
                if 'subtitle_start_time' in timing_data:
                    title_offset = timing_data['subtitle_start_time']
                    logger.info(f"Using title offset from timing_data: {title_offset:.3f}s")
                if 'title_word_count' in timing_data:
                    title_word_count = timing_data['title_word_count']
                    logger.info(f"Using title word count from timing_data: {title_word_count} words")
            
            # This will raise an exception if subtitle generation fails
            self.create_subtitles_for_text(
                text=audio_chunk.text,
                audio_duration=audio_chunk.duration_seconds,
                output_path=subtitle_path,
                word_timestamps=audio_chunk.word_timestamps,
                audio_path=audio_chunk.audio_path,  # Pass audio path for offset detection
                title_offset=title_offset,  # Pass title offset for subtitle timing
                title_word_count=title_word_count  # Pass title word count for filtering
            )
            
            # Step 3: Combine audio with background, subtitles, overlay, and pop SFX
            logger.info("Combining audio with background and visual hook")
            success = self.combine_audio_with_background(
                audio_path=audio_chunk.audio_path,
                background_path=background_path,
                output_path=output_path,
                subtitle_path=subtitle_path,
                overlay_image_path=overlay_image_path,
                pop_sfx_path=pop_sfx_path,
                timing_data=timing_data,
                hook_duration=hook_duration
            )
            
            if not success:
                raise RuntimeError("Failed to combine audio with background")
        
        # Apply 1.4x speed post-processing
        final_speed_path = output_path.parent / f"{output_path.stem}_1_4x{output_path.suffix}"
        speed_success = self.apply_1_4x_speed(output_path, final_speed_path)
        
        if speed_success and final_speed_path.exists() and final_speed_path.stat().st_size > 0:
            final_return_path = final_speed_path
        else:
            final_return_path = output_path
            
        logger.info(f"Video part created successfully: {final_return_path}")
        return final_return_path
    
    def concatenate_videos(
        self,
        video_paths: List[Path],
        output_path: Path
    ) -> bool:
        """
        Concatenate multiple video files into a single video.
        
        Args:
            video_paths: List of paths to video files
            output_path: Path where concatenated video will be saved
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not video_paths:
                logger.error("No video files to concatenate")
                return False
            
            # Create file list for ffmpeg
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                for video_path in video_paths:
                    if video_path.exists():
                        # Escape single quotes and backslashes for Windows paths
                        path_str = str(video_path).replace('\\', '\\\\').replace("'", "'\\''")
                        f.write(f"file '{path_str}'\n")
                    else:
                        logger.warning(f"Video file does not exist, skipping: {video_path}")
                
                filelist_path = Path(f.name)
            
            try:
                # Build ffmpeg command for concatenation with YouTube-compatible encoding
                cmd = [
                    'ffmpeg',
                    '-y',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', str(filelist_path),
                    '-c:v', 'libx264',  # Re-encode video for YouTube compatibility
                    '-preset', 'veryfast',
                    '-crf', '23',
                    '-pix_fmt', 'yuv420p',  # Required for YouTube compatibility
                    '-c:a', 'aac',  # Standard audio codec for YouTube
                    '-b:a', '128k',
                    '-movflags', '+faststart',  # Move moov atom to beginning for streaming
                    str(output_path)
                ]
                
                logger.info(f"Concatenating {len(video_paths)} videos")
                logger.debug(f"FFmpeg command: {' '.join(cmd)}")
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    logger.error(f"FFmpeg concatenation failed: {result.stderr}")
                    return False
                
                # Verify output
                if not output_path.exists() or output_path.stat().st_size == 0:
                    logger.error(f"Concatenated video not created: {output_path}")
                    return False
                
                logger.info(f"Videos concatenated successfully: {output_path}")
                return True
                
            finally:
                # Clean up file list
                filelist_path.unlink()
                
        except Exception as e:
            logger.error(f"Failed to concatenate videos: {e}")
            return False
    
    def create_complete_shorts_video(
        self,
        audio_chunks: List[AudioChunk],
        theme: Optional[str] = None,
        output_path: Optional[Path] = None,
        overlay_image_path: Optional[Path] = None,
        pop_sfx_path: Optional[Path] = None
    ) -> Path:
        """
        Create a complete Shorts video from multiple audio chunks.
        
        Args:
            audio_chunks: List of AudioChunk objects
            theme: Optional theme for background
            output_path: Optional output path
            overlay_image_path: Optional path to overlay image (Reddit post)
            pop_sfx_path: Optional path to pop sound effect
            
        Returns:
            Path to created video, raises exception on failure
        """
        if not audio_chunks:
            raise ValueError("No audio chunks provided")
        
        # Create output path if not provided
        if output_path is None:
            output_dir = settings.OUTPUT_DIR / "reddit_stories"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"shorts_{uuid.uuid4()}.mp4"
        
        # Create temporary directory for intermediate files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_parts = []
            
            # Create video part for each audio chunk
            for i, audio_chunk in enumerate(audio_chunks, 1):
                logger.info(f"Creating video part {i}/{len(audio_chunks)}")
                
                # Skip chunks with 0.0s duration (audio generation failed)
                if audio_chunk.duration_seconds <= 0:
                    logger.warning(f"Skipping audio chunk {i} with 0.0s duration (audio generation failed)")
                    continue
                
                # Create unique part path to prevent overwriting
                part_path = temp_path / f"part_{i}_{uuid.uuid4().hex[:8]}.mp4"
                # create_video_part will raise exception on failure
                video_part = self.create_video_part(
                    audio_chunk=audio_chunk,
                    theme=theme,
                    output_path=part_path,
                    overlay_image_path=overlay_image_path if i == 1 else None,  # Only add overlay to first part
                    pop_sfx_path=pop_sfx_path if i == 1 else None  # Only add pop SFX to first part
                )
                
                video_parts.append(video_part)
                logger.info(f"Video part {i} created: {video_part}")
            
            if not video_parts:
                raise RuntimeError("No video parts were created successfully")
            
            # Concatenate all video parts
            if len(video_parts) == 1:
                # Only one part, just copy it
                import shutil
                shutil.copy2(video_parts[0], output_path)
                logger.info(f"Single video part copied to: {output_path}")
            else:
                # Concatenate multiple parts - will raise exception on failure
                success = self.concatenate_videos(video_parts, output_path)
                if not success:
                    raise RuntimeError("Failed to concatenate video parts")
            
            # Verify final video
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError(f"Final video not created: {output_path}")

            # Get video metadata
            try:
                cmd = [
                    'ffprobe',
                    '-v', 'quiet',
                    '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    str(output_path)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                duration = float(result.stdout.strip()) if result.stdout else 0
                logger.info(f"Final video created: {output_path} ({duration:.1f}s)")
            except Exception as e:
                logger.warning(f"Could not get final video duration: {e}")

            return output_path
    
    def create_separate_video_parts(
        self,
        audio_chunks: List[AudioChunk],
        output_dir: Path,
        theme: Optional[str] = None,
        overlay_image_path: Optional[Path] = None,
        pop_sfx_path: Optional[Path] = None
    ) -> List[Path]:
        """
        Create separate video parts for each audio chunk and save them to the specified directory.
        
        Args:
            audio_chunks: List of AudioChunk objects
            output_dir: Directory where video parts will be saved
            theme: Optional theme for background
            overlay_image_path: Optional path to overlay image (Reddit post)
            pop_sfx_path: Optional path to pop sound effect
            
        Returns:
            List of paths to created video parts, raises exception on failure
        """
        if not audio_chunks:
            raise ValueError("No audio chunks provided")
        
        # Create output directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Creating separate video parts in directory: {output_dir}")
        
        video_parts = []
        
        # Create video part for each audio chunk
        for i, audio_chunk in enumerate(audio_chunks, 1):
            logger.info(f"Creating video part {i}/{len(audio_chunks)}")
            
            # Skip chunks with 0.0s duration (audio generation failed)
            if audio_chunk.duration_seconds <= 0:
                logger.warning(f"Skipping audio chunk {i} with 0.0s duration (audio generation failed)")
                continue
            
            # Create unique part path with part number and UUID
            part_filename = f"part_{i}_{uuid.uuid4().hex[:8]}.mp4"
            part_path = output_dir / part_filename
            
            # Create video part - will raise exception on failure
            video_part = self.create_video_part(
                audio_chunk=audio_chunk,
                theme=theme,
                output_path=part_path,
                overlay_image_path=overlay_image_path if i == 1 else None,  # Only add overlay to first part
                pop_sfx_path=pop_sfx_path if i == 1 else None  # Only add pop SFX to first part
            )
            
            video_parts.append(video_part)
            logger.info(f"Video part {i} created: {video_part}")
        
        logger.info(f"Created {len(video_parts)} video parts in {output_dir}")
        return video_parts


# Utility functions for direct use
def create_shorts_video(
    audio_chunks: List[AudioChunk],
    theme: Optional[str] = None,
    output_path: Optional[Path] = None,
    overlay_image_path: Optional[Path] = None,
    pop_sfx_path: Optional[Path] = None
) -> Path:
    """
    Convenience function to create a Shorts video from audio chunks.
    
    Args:
        audio_chunks: List of AudioChunk objects
        theme: Optional theme for background
        output_path: Optional output path
        overlay_image_path: Optional path to overlay image (Reddit post)
        pop_sfx_path: Optional path to pop sound effect
    
    Returns:
        Path to created video, raises exception on failure
    """
    composer = VideoComposer()
    return composer.create_complete_shorts_video(
        audio_chunks, 
        theme, 
        output_path,
        overlay_image_path,
        pop_sfx_path
    )


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # Create mock audio chunks for testing
        mock_chunks = [
            AudioChunk(
                chunk_id="1",
                text="This is the first part of the Reddit story.",
                audio_path=Path("/tmp/test_audio1.mp3"),
                duration_seconds=5.0,
                voice_id="test_voice",
                file_size_bytes=1024,
            ),
            AudioChunk(
                chunk_id="2",
                text="This is the second part with more details.",
                audio_path=Path("/tmp/test_audio2.mp3"),
                duration_seconds=6.0,
                voice_id="test_voice",
                file_size_bytes=2048,
            ),
        ]
        
        # Create video composer
        composer = VideoComposer()
        
        # Test subtitle creation
        print("Testing subtitle creation...")
        subtitle_path = Path("/tmp/test_subtitles.ass")
        success = composer.create_subtitles_for_text(
            text="This is a test for subtitle generation.",
            audio_duration=5.0,
            output_path=subtitle_path
        )
        
        if success:
            print(f"Subtitles created: {subtitle_path}")
            # Clean up
            if subtitle_path.exists():
                subtitle_path.unlink()
        
        # Test video creation (will fail without actual audio files)
        print("\nTesting video creation (mock)...")
        print("Note: This will fail without actual audio files.")
        print("In real usage, provide actual AudioChunk objects with valid audio files.")
        
        # Show available themes
        themes = composer.background_manager.get_available_themes()
        print(f"\nAvailable background themes: {themes}")
        
        print("\nExample completed!")
    
    # Run example
    asyncio.run(example())
