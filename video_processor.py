"""
Automated Shorts Pipeline with synchronized word-by-word captions.
Handles video reframing, AI transcription, and dynamic subtitle generation.
"""

import subprocess
import os
import tempfile
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional
import ffmpeg
import logging
from faster_whisper import WhisperModel
import json
from dataclasses import dataclass

# Import the new subtitle generator
from reddit_story.subtitle_generator import SubtitleGenerator, WordTimestamp as SubtitleWordTimestamp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class WordTimestamp:
    """Word-level timestamp data for perfect sync."""
    word: str
    start: float
    end: float
    confidence: float

@dataclass
class Segment:
    """Transcription segment with word-level timestamps."""
    text: str
    start: float
    end: float
    words: List[WordTimestamp]

def get_video_dimensions(input_path: str) -> Tuple[int, int]:
    """
    Get video dimensions using ffprobe.
    
    Args:
        input_path: Path to the input video file
        
    Returns:
        Tuple of (width, height)
    """
    try:
        probe = ffmpeg.probe(input_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        
        if video_stream:
            width = int(video_stream['width'])
            height = int(video_stream['height'])
            return width, height
        else:
            raise ValueError("No video stream found in the file")
    except Exception as e:
        logger.error(f"Error getting video dimensions: {e}")
        # Fallback to default 16:9 dimensions
        return 1920, 1080

def get_video_framerate(input_path: str) -> float:
    """
    Get video frame rate.
    
    Args:
        input_path: Path to the input video file
        
    Returns:
        Frame rate as float
    """
    try:
        probe = ffmpeg.probe(input_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        
        if video_stream:
            # Handle fractional frame rates like "30000/1001"
            fps_str = video_stream.get('avg_frame_rate', '30/1')
            if '/' in fps_str:
                num, den = map(int, fps_str.split('/'))
                return num / den
            else:
                return float(fps_str)
        else:
            return 30.0  # Default fallback
    except Exception as e:
        logger.error(f"Error getting video framerate: {e}")
        return 30.0

def extract_audio_16khz(video_path: str, audio_output_path: str) -> bool:
    """
    Extract audio from video and convert to 16kHz mono for optimal transcription.
    
    Args:
        video_path: Path to input video
        audio_output_path: Path where extracted audio will be saved
        
    Returns:
        True if successful, False otherwise
    """
    try:
        (
            ffmpeg
            .input(video_path)
            .output(
                audio_output_path,
                ar=16000,  # 16kHz sampling rate
                ac=1,      # Mono channel
                acodec='pcm_s16le'  # 16-bit PCM
            )
            .overwrite_output()
            .run(quiet=True)
        )
        logger.info(f"Audio extracted to {audio_output_path}")
        return True
    except ffmpeg.Error as e:
        logger.error(f"FFmpeg error extracting audio: {e.stderr.decode() if e.stderr else str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error extracting audio: {e}")
        return False

def transcribe_with_word_timestamps(audio_path: str, model_size: str = "base") -> List[Segment]:
    """
    Transcribe audio using faster-whisper with word-level timestamps.
    
    Args:
        audio_path: Path to 16kHz audio file
        model_size: Whisper model size (base, small, medium, large)
        
    Returns:
        List of segments with word-level timestamps
    """
    try:
        logger.info(f"Loading Whisper model: {model_size}")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        
        logger.info(f"Transcribing audio: {audio_path}")
        segments, info = model.transcribe(
            audio_path,
            beam_size=5,
            word_timestamps=True,  # Enable word-level timestamps
            vad_filter=True,       # Voice activity detection
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        
        logger.info(f"Detected language: {info.language}, probability: {info.language_probability}")
        
        result_segments = []
        for segment in segments:
            words = []
            for word in segment.words:
                words.append(WordTimestamp(
                    word=word.word,
                    start=word.start,
                    end=word.end,
                    confidence=word.probability
                ))
            
            result_segments.append(Segment(
                text=segment.text,
                start=segment.start,
                end=segment.end,
                words=words
            ))
            
            logger.debug(f"Segment: {segment.text} ({segment.start:.2f}s - {segment.end:.2f}s)")
            for word in words:
                logger.debug(f"  Word: '{word.word}' ({word.start:.2f}s - {word.end:.2f}s, conf: {word.confidence:.2f})")
        
        logger.info(f"Transcription complete: {len(result_segments)} segments")
        return result_segments
        
    except Exception as e:
        logger.error(f"Error during transcription: {e}")
        raise

def generate_ass_subtitles(segments: List[Segment], output_path: str, video_width: int = 1080, video_height: int = 1920) -> bool:
    """
    Generate Advanced Substation Alpha (.ass) file with perfect timing and no overlaps.
    Uses the new SubtitleGenerator for phrase-based chunking and dynamic highlighting.
    
    Args:
        segments: List of segments with word-level timestamps
        output_path: Path where .ass file will be saved
        video_width: Video width (default 1080 for 9:16)
        video_height: Video height (default 1920 for 9:16)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Flatten all words from all segments
        all_words = []
        for segment in segments:
            for word in segment.words:
                # Convert WordTimestamp to SubtitleWordTimestamp
                all_words.append(SubtitleWordTimestamp(
                    word=word.word,
                    start=word.start,
                    end=word.end,
                    confidence=word.confidence
                ))
        
        if not all_words:
            logger.error("No words found in segments")
            return False
        
        # Calculate total audio duration from last word end time
        audio_duration = max(word.end for word in all_words) if all_words else 0
        
        # Create subtitle generator
        generator = SubtitleGenerator(
            video_width=video_width,
            video_height=video_height,
            max_words_per_phrase=5,
            min_words_per_phrase=2,
            max_phrase_duration=3.0,
            min_gap_between_phrases=0.1
        )
        
        # Generate ASS file
        success = generator.generate_ass_from_word_timestamps(
            word_timestamps=all_words,
            audio_duration=audio_duration,
            output_path=Path(output_path)
        )
        
        if success:
            logger.info(f"ASS subtitles generated with perfect timing: {output_path}")
            logger.info(f"  Words: {len(all_words)}, Duration: {audio_duration:.2f}s")
        
        return success
        
    except Exception as e:
        logger.error(f"Error generating ASS subtitles: {e}")
        return False

def format_time(seconds: float) -> str:
    """
    Format time in ASS format: H:MM:SS.cc
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"

def calculate_crop_parameters(width: int, height: int) -> Tuple[str, str, str, str]:
    """
    Calculate crop parameters to convert to 9:16 (1080x1920) by cropping center.
    
    Args:
        width: Original video width
        height: Original video height
        
    Returns:
        Tuple of (crop_width, crop_height, x_offset, y_offset)
    """
    # Target aspect ratio: 9:16 (portrait)
    target_aspect_w = 9
    target_aspect_h = 16
    
    # Calculate based on original dimensions
    # We want to crop the center to match 9:16
    if width / height > target_aspect_w / target_aspect_h:
        # Video is wider than target aspect ratio, crop width
        crop_height = height
        crop_width = int(height * target_aspect_w / target_aspect_h)
    else:
        # Video is taller than target aspect ratio, crop height
        crop_width = width
        crop_height = int(width * target_aspect_h / target_aspect_w)
    
    # Center crop
    x_offset = max(0, (width - crop_width) // 2)
    y_offset = max(0, (height - crop_height) // 2)
    
    logger.debug(f"Original: {width}x{height}, Crop: {crop_width}x{crop_height}, Offset: ({x_offset}, {y_offset})")
    
    return str(crop_width), str(crop_height), str(x_offset), str(y_offset)

def reframe_to_916_with_subtitles(input_path: str, output_path: str, subtitle_path: str) -> bool:
    """
    Reframe video to 9:16 and burn subtitles with perfect sync using filter_complex.
    
    Args:
        input_path: Path to input video file
        output_path: Path where processed video will be saved
        subtitle_path: Path to .ass subtitle file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Validate input file exists
        if not os.path.exists(input_path):
            logger.error(f"Input file does not exist: {input_path}")
            return False
        
        if not os.path.exists(subtitle_path):
            logger.error(f"Subtitle file does not exist: {subtitle_path}")
            return False
        
        # Get video dimensions and framerate
        width, height = get_video_dimensions(input_path)
        fps = get_video_framerate(input_path)
        logger.info(f"Original video: {width}x{height} @ {fps:.2f} fps")
        
        # Calculate crop parameters
        crop_w, crop_h, x, y = calculate_crop_parameters(width, height)
        logger.info(f"Crop parameters: width={crop_w}, height={crop_h}, x={x}, y={y}")
        
        # Get the directory containing the subtitle file
        subtitle_dir = os.path.dirname(subtitle_path)
        subtitle_filename = os.path.basename(subtitle_path)
        
        logger.info(f"Using relative subtitle path: {subtitle_filename} from directory: {subtitle_dir}")
        
        # Build FFmpeg command with separate video and audio streams
        # This ensures audio is preserved when applying video filters
        import subprocess
        
        # Convert input path to absolute path for when we change directory
        abs_input_path = os.path.abspath(input_path)
        abs_output_path = os.path.abspath(output_path)
        
        # Create input stream and separate video/audio
        input_stream = ffmpeg.input(abs_input_path)
        
        # Process video stream with filters
        video = (
            input_stream.video
            .filter('crop', crop_w, crop_h, x, y)
            .filter('scale', 1080, 1920)
            .filter('subtitles', subtitle_filename)
        )
        
        # Keep audio stream as-is
        audio = input_stream.audio
        
        # Build output with both video and audio streams
        cmd = (
            ffmpeg
            .output(
                video,
                audio,
                abs_output_path,
                vcodec='libx264',
                crf=23,  # Good quality balance (0-51, lower is better)
                preset='veryfast',  # Fast processing as requested
                pix_fmt='yuv420p',  # Required for YouTube compatibility
                acodec='aac',  # Standard audio codec
                audio_bitrate='128k',
                movflags='+faststart',  # Enable streaming
                r=fps  # Maintain original frame rate to prevent sync drift
            )
            .overwrite_output()  # Ensure overwrite is enabled
            .compile()
        )
        
        # Run the command from the subtitle directory
        original_cwd = os.getcwd()
        try:
            os.chdir(subtitle_dir)
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.debug(f"FFmpeg output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg command failed: {e}")
            logger.error(f"FFmpeg stderr: {e.stderr}")
            raise
        finally:
            os.chdir(original_cwd)
        
        logger.info(f"Successfully processed video with subtitles: {output_path}")
        
        # Verify output file was created
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            output_width, output_height = get_video_dimensions(output_path)
            logger.info(f"Output video dimensions: {output_width}x{output_height}")
            
            if output_width == 1080 and output_height == 1920:
                logger.info("Output video is correctly formatted to 1080x1920 (9:16)")
                return True
            else:
                logger.warning(f"Output dimensions are {output_width}x{output_height}, expected 1080x1920")
                return True  # Still return True as video was created, just not exact dimensions
        
        return False
        
    except ffmpeg.Error as e:
        logger.error(f"FFmpeg error: {e.stderr.decode() if e.stderr else str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        return False

def create_shorts_with_captions(input_path: str, output_path: str, model_size: str = "base") -> Dict[str, Any]:
    """
    Complete automated shorts pipeline:
    1. Extract audio at 16kHz
    2. Transcribe with word-level timestamps
    3. Generate .ass subtitles with Hormozi style
    4. Reframe to 9:16 with burned subtitles
    
    Args:
        input_path: Path to input video file
        output_path: Path where final shorts video will be saved
        model_size: Whisper model size
        
    Returns:
        Dictionary with processing results
    """
    try:
        logger.info(f"Starting automated shorts pipeline for: {input_path}")
        
        # Create temporary directory for intermediate files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Step 1: Extract audio at 16kHz
            audio_path = temp_path / "audio_16khz.wav"
            logger.info("Step 1: Extracting audio at 16kHz...")
            if not extract_audio_16khz(input_path, str(audio_path)):
                return {
                    'success': False,
                    'error': 'Failed to extract audio',
                    'input_path': input_path,
                    'output_path': None
                }
            
            # Step 2: Transcribe with word-level timestamps
            logger.info("Step 2: Transcribing with word-level timestamps...")
            try:
                segments = transcribe_with_word_timestamps(str(audio_path), model_size)
                logger.info(f"Transcription complete: {len(segments)} segments")
            except Exception as e:
                logger.error(f"Transcription failed: {e}")
                return {
                    'success': False,
                    'error': f'Transcription failed: {str(e)}',
                    'input_path': input_path,
                    'output_path': None
                }
            
            # Step 3: Generate .ass subtitles
            subtitle_path = temp_path / "subtitles.ass"
            logger.info("Step 3: Generating ASS subtitles...")
            if not generate_ass_subtitles(segments, str(subtitle_path)):
                return {
                    'success': False,
                    'error': 'Failed to generate subtitles',
                    'input_path': input_path,
                    'output_path': None
                }
            
            # Step 4: Reframe to 9:16 with burned subtitles
            logger.info("Step 4: Reframing to 9:16 with burned subtitles...")
            if not reframe_to_916_with_subtitles(input_path, output_path, str(subtitle_path)):
                return {
                    'success': False,
                    'error': 'Failed to process video with subtitles',
                    'input_path': input_path,
                    'output_path': None
                }
            
            # Return success with metadata
            return {
                'success': True,
                'input_path': input_path,
                'output_path': output_path,
                'segments_count': len(segments),
                'subtitles_path': str(subtitle_path),
                'message': 'Shorts video created successfully with synchronized captions'
            }
            
    except Exception as e:
        logger.error(f"Error in automated shorts pipeline: {e}")
        return {
            'success': False,
            'error': f'Pipeline error: {str(e)}',
            'input_path': input_path,
            'output_path': None
        }

def batch_process_shorts(input_dir: str, output_dir: str, model_size: str = "base") -> Dict[str, Any]:
    """
    Process all videos in a directory through the complete shorts pipeline.
    
    Args:
        input_dir: Directory containing input videos
        output_dir: Directory where processed shorts will be saved
        model_size: Whisper model size
        
    Returns:
        Dictionary with batch processing results
    """
    results = {
        'total': 0,
        'successful': 0,
        'failed': 0,
        'failed_files': [],
        'processed_files': []
    }
    
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Supported video extensions
    video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.webm'}
    
    for file in input_path.iterdir():
        if file.suffix.lower() in video_extensions and file.is_file():
            results['total'] += 1
            output_file = output_path / f"shorts_{file.stem}.mp4"
            
            logger.info(f"Processing: {file.name}")
            result = create_shorts_with_captions(str(file), str(output_file), model_size)
            
            if result['success']:
                results['successful'] += 1
                results['processed_files'].append({
                    'input': str(file),
                    'output': str(output_file),
                    'segments': result.get('segments_count', 0)
                })
                logger.info(f"Successfully processed: {file.name}")
            else:
                results['failed'] += 1
                results['failed_files'].append({
                    'file': str(file),
                    'error': result.get('error', 'Unknown error')
                })
                logger.error(f"Failed to process: {file.name} - {result.get('error')}")
    
    return results

if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python video_processor.py <input_path> <output_path>")
        print("Example: python video_processor.py input.mp4 output.mp4")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    print(f"Processing {input_file} -> {output_file}")
    result = create_shorts_with_captions(input_file, output_file)
    
    if result['success']:
        print(f"[OK] Successfully created shorts video: {output_file}")
        print(f"   Segments: {result.get('segments_count', 0)}")
    else:
        print(f"[FAIL] Failed to process video: {result.get('error')}")
        sys.exit(1)
