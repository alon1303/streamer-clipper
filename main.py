from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
import uuid
import asyncio
from pydantic import BaseModel
import logging
import subprocess

from video_processor import create_shorts_with_captions, batch_process_shorts

# Import Reddit Stories modules
from reddit_story.reddit_client import RedditClient, RedditStory
from reddit_story.story_processor import StoryProcessor
from reddit_story.tts_router import get_tts_client, generate_story_audio_compat as generate_story_audio
from reddit_story.video_composer import VideoComposer, create_shorts_video
from reddit_story.background_manager import BackgroundManager

# Import settings
from config.settings import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ShortsGenerator Backend v2 - Automated Pipeline", version="2.0.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create necessary directories
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

class Subtitle(BaseModel):
    text: str
    start: float
    end: float

class VideoUploadResponse(BaseModel):
    success: bool
    message: str
    original_path: Optional[str] = None
    processed_path: Optional[str] = None
    subtitles: Optional[List[Subtitle]] = None

class ProcessVideoRequest(BaseModel):
    input_path: str
    model_size: Optional[str] = "base"  # base, small, medium, large

class ProcessVideoResponse(BaseModel):
    success: bool
    message: str
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    segments_count: Optional[int] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class BatchProcessRequest(BaseModel):
    input_dir: str
    output_dir: Optional[str] = None
    model_size: Optional[str] = "base"

class BatchProcessResponse(BaseModel):
    success: bool
    message: str
    total: Optional[int] = None
    successful: Optional[int] = None
    failed: Optional[int] = None
    failed_files: Optional[List[Dict[str, str]]] = None
    processed_files: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


# Reddit Stories Models
class RedditStoryRequest(BaseModel):
    """Request model for Reddit story generation."""
    story_url: Optional[str] = None
    story_text: Optional[str] = None
    subreddit: Optional[str] = "AskReddit"
    theme: Optional[str] = None
    voice_id: Optional[str] = None
    max_duration_minutes: Optional[int] = 3
    split_strategy: Optional[str] = "HYBRID"
    split_into_parts: Optional[bool] = True


class RedditStoryResponse(BaseModel):
    """Response model for Reddit story generation."""
    success: bool
    message: str
    job_id: Optional[str] = None
    story_id: Optional[str] = None
    estimated_duration: Optional[float] = None
    parts_count: Optional[int] = None
    video_path: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class RedditStoryStatus(BaseModel):
    """Status model for Reddit story processing."""
    job_id: str
    status: str  # "pending", "processing", "completed", "failed"
    progress: float  # 0.0 to 1.0
    message: str
    story_id: Optional[str] = None
    video_path: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# In-memory job tracking (in production, use a database)
_jobs: Dict[str, Dict[str, Any]] = {}

@app.get("/")
async def root():
    return {
        "message": "ShortsGenerator Backend v2 - Automated Pipeline",
        "version": "2.0.0",
        "features": [
            "16:9 to 9:16 reframing",
            "AI transcription with word-level timestamps",
            "Dynamic .ass subtitle generation",
            "Word-by-word highlighting (Hormozi style)",
            "Perfect sync with original audio"
        ]
    }

@app.post("/upload/video", response_model=VideoUploadResponse)
async def upload_video(file: UploadFile = File(...)):
    """
    Upload a video file for processing.
    The video will be processed through the complete automated shorts pipeline.
    """
    try:
        # Validate file type
        allowed_extensions = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
        file_extension = Path(file.filename).suffix.lower()
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}"
            )
        
        # Generate unique filename
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        original_path = UPLOAD_DIR / unique_filename
        
        # Save uploaded file
        with open(original_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Process video through complete pipeline
        processed_filename = f"shorts_{unique_filename}"
        processed_path = OUTPUT_DIR / processed_filename
        
        # Call automated shorts pipeline
        result = create_shorts_with_captions(str(original_path), str(processed_path))
        
        if result['success']:
            # Convert transcription segments to subtitle format
            # Note: In a real implementation, we would parse the actual segments
            # For now, return success with basic info
            mock_subtitles = [
                Subtitle(text="Automated transcription", start=0.0, end=2.0),
                Subtitle(text="with word-level sync", start=2.0, end=4.0),
                Subtitle(text="and Hormozi style captions", start=4.0, end=6.0),
            ]
            
            return VideoUploadResponse(
                success=True,
                message=f"Video processed successfully with {result.get('segments_count', 0)} transcription segments",
                original_path=str(original_path),
                processed_path=str(processed_path),
                subtitles=mock_subtitles
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process video: {result.get('error', 'Unknown error')}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing video upload: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing video: {str(e)}")

@app.post("/process-video", response_model=ProcessVideoResponse)
async def process_video(request: ProcessVideoRequest):
    """
    Process a video file from a local path through the complete automated shorts pipeline.
    
    Request body should contain:
    {
        "input_path": "/path/to/input/video.mp4",
        "model_size": "base"  # optional, defaults to "base"
    }
    """
    try:
        input_path = request.input_path
        model_size = request.model_size or "base"
        
        # Validate input file exists
        if not os.path.exists(input_path):
            return ProcessVideoResponse(
                success=False,
                message="Input file does not exist",
                input_path=input_path,
                error=f"File not found: {input_path}"
            )
        
        # Validate it's a video file
        allowed_extensions = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
        file_extension = Path(input_path).suffix.lower()
        
        if file_extension not in allowed_extensions:
            return ProcessVideoResponse(
                success=False,
                message="Invalid file type",
                input_path=input_path,
                error=f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}"
            )
        
        # Generate output path
        input_filename = Path(input_path).stem
        output_filename = f"shorts_{input_filename}.mp4"
        output_path = str(OUTPUT_DIR / output_filename)
        
        # Process through complete automated pipeline
        logger.info(f"Starting automated shorts pipeline for: {input_path}")
        result = create_shorts_with_captions(input_path, output_path, model_size)
        
        if result['success']:
            return ProcessVideoResponse(
                success=True,
                message="Video successfully processed through automated shorts pipeline",
                input_path=input_path,
                output_path=output_path,
                segments_count=result.get('segments_count'),
                metadata={
                    'subtitles_generated': True,
                    'word_level_timestamps': True,
                    'aspect_ratio': '9:16 (1080x1920)',
                    'subtitle_style': 'Hormozi style with karaoke effect'
                }
            )
        else:
            return ProcessVideoResponse(
                success=False,
                message="Failed to process video through automated pipeline",
                input_path=input_path,
                output_path=output_path,
                error=result.get('error', 'Unknown error')
            )
            
    except Exception as e:
        logger.error(f"Error in process-video endpoint: {e}")
        return ProcessVideoResponse(
            success=False,
            message="Internal server error",
            input_path=request.input_path,
            error=f"Unexpected error: {str(e)}"
        )

@app.post("/batch-process", response_model=BatchProcessResponse)
async def batch_process(request: BatchProcessRequest):
    """
    Process all videos in a directory through the automated shorts pipeline.
    
    Request body should contain:
    {
        "input_dir": "/path/to/input/directory",
        "output_dir": "/path/to/output/directory",  # optional, defaults to backend_v2/outputs
        "model_size": "base"  # optional
    }
    """
    try:
        input_dir = request.input_dir
        output_dir = request.output_dir or str(OUTPUT_DIR)
        model_size = request.model_size or "base"
        
        # Validate input directory exists
        if not os.path.exists(input_dir):
            return BatchProcessResponse(
                success=False,
                message="Input directory does not exist",
                error=f"Directory not found: {input_dir}"
            )
        
        if not os.path.isdir(input_dir):
            return BatchProcessResponse(
                success=False,
                message="Input path is not a directory",
                error=f"Not a directory: {input_dir}"
            )
        
        # Process batch
        logger.info(f"Starting batch processing for directory: {input_dir}")
        result = batch_process_shorts(input_dir, output_dir, model_size)
        
        return BatchProcessResponse(
            success=True,
            message=f"Batch processing complete: {result['successful']}/{result['total']} successful",
            total=result['total'],
            successful=result['successful'],
            failed=result['failed'],
            failed_files=result['failed_files'],
            processed_files=result['processed_files']
        )
            
    except Exception as e:
        logger.error(f"Error in batch-process endpoint: {e}")
        return BatchProcessResponse(
            success=False,
            message="Internal server error during batch processing",
            error=f"Unexpected error: {str(e)}"
        )


# Reddit Stories Endpoints
async def process_reddit_story_background(job_id: str, request: RedditStoryRequest):
    """
    Background task to process a Reddit story into a Shorts video.
    
    Args:
        job_id: Unique job ID
        request: Reddit story request
    """
    try:
        # Update job status to processing
        _jobs[job_id]["status"] = "processing"
        _jobs[job_id]["progress"] = 0.1
        _jobs[job_id]["message"] = "Starting Reddit story processing..."
        
        logger.info(f"Starting Reddit story processing for job {job_id}")
        
        # Initialize Reddit client for duplicate prevention and multi-subreddit fetching
        reddit_client = RedditClient()
        
        # Step 1: Get or create Reddit story
        story = None
        if request.story_url:
            # Fetch story from Reddit URL
            _jobs[job_id]["message"] = "Fetching story from Reddit URL..."
            _jobs[job_id]["progress"] = 0.2
            
            story = await reddit_client.fetch_story_from_url(request.story_url)
            
            if not story:
                raise ValueError(f"Failed to fetch story from URL: {request.story_url}")
                
        elif request.story_text:
            # Create story from provided text
            _jobs[job_id]["message"] = "Creating story from provided text..."
            _jobs[job_id]["progress"] = 0.2
            
            story = RedditStory(
                id=str(uuid.uuid4()),
                title="Custom Story",
                text=request.story_text,
                subreddit=request.subreddit or "AskReddit",
                url="",
                score=100,
                upvote_ratio=0.95,
                created_utc=0.0,
                author="custom",
                is_nsfw=False,
                word_count=len(request.story_text.split()),
                estimated_duration=len(request.story_text.split()) / 150 * 60,  # 150 WPM
            )
        elif request.subreddit:
            # Fetch trending story from subreddit using new multi-subreddit support
            _jobs[job_id]["message"] = f"Fetching trending story from r/{request.subreddit}..."
            _jobs[job_id]["progress"] = 0.2
            
            # Use the new multi-subreddit fetching (backward compatible with single subreddit)
            stories = await reddit_client.fetch_trending_stories(
                subreddit=request.subreddit,
                time_filter="day",
                limit=5,
                min_score=100,
                min_text_length=200,
                max_text_length=5000,
                exclude_nsfw=True,
                exclude_processed=True,  # Enable duplicate prevention
            )
            
            if not stories:
                raise ValueError(f"No trending stories found in r/{request.subreddit}")
            
            # Select the first story (highest score)
            story = stories[0]
            logger.info(f"Selected story from r/{request.subreddit}: {story.title[:50]}...")
        else:
            raise ValueError("Either story_url, story_text, or subreddit must be provided")
        
        # Store story ID
        _jobs[job_id]["story_id"] = story.id
        _jobs[job_id]["metadata"] = {
            "title": story.title,
            "subreddit": story.subreddit,
            "author": story.author,
            "word_count": story.word_count,
            "estimated_duration": story.estimated_duration,
        }
        
        # Step 2: Process story into parts
        _jobs[job_id]["message"] = "Processing story into parts..."
        _jobs[job_id]["progress"] = 0.3
        
        processor = StoryProcessor(min_part_duration=60, max_part_duration=90)
        processed_story = processor.process_story(story, split_into_parts=request.split_into_parts)
        
        _jobs[job_id]["parts_count"] = processed_story.total_parts
        _jobs[job_id]["estimated_duration"] = processed_story.total_duration
        _jobs[job_id]["message"] = f"Story split into {processed_story.total_parts} parts"
        
        # Step 3: Create post-specific folder
        _jobs[job_id]["message"] = "Creating post-specific folder..."
        _jobs[job_id]["progress"] = 0.4
        
        # Create post-specific folder using sanitized title or post ID
        import re
        sanitized_title = re.sub(r'[^\w\s-]', '', story.title).strip().replace(' ', '_')
        sanitized_title = sanitized_title[:50]  # Limit length
        
        # Create post-specific folder
        post_folder_name = f"{sanitized_title}_{story.id[:8]}"
        post_output_dir = OUTPUT_DIR / "reddit_stories" / post_folder_name
        post_output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Creating post-specific folder: {post_output_dir}")
        
        # Step 4: Generate title card
        _jobs[job_id]["message"] = "Generating title card..."
        _jobs[job_id]["progress"] = 0.45
        
        # Import title card generator - using new Playwright-based generator
        from reddit_story.image_generator_new import RedditImageGenerator, TitlePopupTimingCalculator
        
        # Generate title card using Playwright HTML-to-Image generator with transparent background
        title_card_generator = RedditImageGenerator()
        title_card_path = post_output_dir / "title_card.png"
        
        # Call async method directly since we're already in an async context
        output_path = await title_card_generator.generate_reddit_post_image(
            title=story.title,
            subreddit=story.subreddit,
            score=story.score,
            author=story.author,
            theme_mode="dark",  # Use dark theme for better contrast
            output_path=title_card_path
        )
        success = output_path is not None
        
        if not success or not title_card_path.exists():
            raise RuntimeError(f"Failed to generate title card: {title_card_path}")
        
        logger.info(f"Title card generated: {title_card_path}")
        
        # Step 5: Generate title and story audio with timing data
        _jobs[job_id]["message"] = "Generating audio narration with title popup timing..."
        _jobs[job_id]["progress"] = 0.55
        
        # Extract text chunks and add CTAs for audience retention
        text_chunks = []
        for i, part in enumerate(processed_story.parts, 1):
            text = part.text
            
            # Add Call To Action at the end of every chunk EXCEPT the last one
            if i < len(processed_story.parts):
                # Append CTA for audience retention
                cta = f" Like and subscribe for part {i + 1}!"
                text += cta
                logger.info(f"Added CTA to part {i}: '{cta}'")
            
            text_chunks.append(text)
        
        # Generate title and story audio with timing data
        from reddit_story.tts_router import generate_title_and_story_audio
        final_audio_path, story_audio_chunks, title_duration, timing_data = await generate_title_and_story_audio(
            title=story.title,
            story_text_chunks=text_chunks,
            voice=request.voice_id,
            title_voice=request.voice_id,
            engine=settings.TTS_ENGINE.lower(),
            buffer_seconds=0.0,
        )
        
        _jobs[job_id]["message"] = f"Audio generated for {len(story_audio_chunks)} parts"
        _jobs[job_id]["progress"] = 0.7
        
        # Store timing data in metadata
        _jobs[job_id]["metadata"]["title_duration"] = title_duration
        _jobs[job_id]["metadata"]["timing_data"] = timing_data
        
        # Step 6: Create separate video parts in post-specific folder
        _jobs[job_id]["message"] = "Creating separate video parts in post-specific folder with title popup..."
        _jobs[job_id]["progress"] = 0.8
        
        composer = VideoComposer()
        
        logger.info(f"Creating video parts in post-specific folder: {post_output_dir}")
        
        # Create separate video parts with title card and timing data
        video_parts = []
        for i, audio_chunk in enumerate(story_audio_chunks, 1):
            logger.info(f"Creating video part {i}/{len(story_audio_chunks)}")
            
            # Skip chunks with 0.0s duration (audio generation failed)
            if audio_chunk.duration_seconds <= 0:
                logger.warning(f"Skipping audio chunk {i} with 0.0s duration (audio generation failed)")
                continue
            
            # Create unique part path with part number and UUID
            part_filename = f"part_{i}_{uuid.uuid4().hex[:8]}.mp4"
            part_path = post_output_dir / part_filename
            
            try:
                # For the first part, include title card with timing data
                # For subsequent parts, don't include title card
                if i == 1:
                    video_part = composer.create_video_part(
                        audio_chunk=audio_chunk,
                        theme=request.theme,
                        output_path=part_path,
                        overlay_image_path=title_card_path,
                        pop_sfx_path=None,  # Optional: add pop SFX if available
                        timing_data=timing_data
                    )
                else:
                    video_part = composer.create_video_part(
                        audio_chunk=audio_chunk,
                        theme=request.theme,
                        output_path=part_path,
                        overlay_image_path=None,
                        pop_sfx_path=None,
                        timing_data=None
                    )
                
                video_parts.append(video_part)
                logger.info(f"Video part {i} created: {video_part}")
                
            except Exception as e:
                logger.error(f"Failed to create video part {i}: {e}")
                # Continue with remaining parts
                continue
        
        if not video_parts:
            raise ValueError("Failed to create video parts")
        
        # Step 7: Mark post as processed (duplicate prevention) if it's a real Reddit post
        # Only mark posts that have Reddit URLs (not custom stories)
        if story.url and story.url.startswith("https://reddit.com"):
            reddit_client.mark_post_as_processed(story.id)
            logger.info(f"Marked post {story.id} as processed in duplicate prevention system")
        
        # Step 8: Update job status
        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["progress"] = 1.0
        _jobs[job_id]["message"] = f"Reddit story video parts created successfully: {len(video_parts)} parts"
        _jobs[job_id]["video_path"] = str(post_output_dir)  # Store directory path instead of single file
        
        # Add video metadata
        try:
            total_duration = 0
            for video_part in video_parts:
                cmd = [
                    'ffprobe',
                    '-v', 'quiet',
                    '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    str(video_part)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                duration = float(result.stdout.strip()) if result.stdout else 0
                total_duration += duration
            
            _jobs[job_id]["metadata"]["video_duration"] = total_duration
            _jobs[job_id]["metadata"]["parts_count"] = len(video_parts)
            _jobs[job_id]["metadata"]["output_dir"] = str(post_output_dir)
            _jobs[job_id]["metadata"]["video_parts"] = [str(p) for p in video_parts]
        except Exception as e:
            logger.warning(f"Could not get video durations: {e}")
        
        logger.info(f"Reddit story processing completed for job {job_id}: {len(video_parts)} parts in {post_output_dir}")
        
    except Exception as e:
        logger.error(f"Error processing Reddit story for job {job_id}: {e}")
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["progress"] = 1.0
        _jobs[job_id]["message"] = f"Failed to process Reddit story: {str(e)}"
        _jobs[job_id]["error"] = str(e)


@app.post("/generate/reddit-story", response_model=RedditStoryResponse)
async def generate_reddit_story(
    request: RedditStoryRequest,
    background_tasks: BackgroundTasks
):
    """
    Generate a Shorts video from a Reddit story.
    
    This endpoint starts the processing in the background and immediately returns
    a job ID for tracking progress.
    
    Request body should contain either:
    - story_url: URL to a Reddit post
    - story_text: Direct text content
    
    Optional parameters:
    - theme: Background theme (e.g., "minecraft", "abstract")
    - voice_id: ElevenLabs voice ID
    - max_duration_minutes: Maximum video duration
    - split_strategy: How to split the story ("HYBRID", "PARAGRAPH", "SENTENCE")
    """
    try:
        # Validate request - allow subreddit-only input
        if not request.story_url and not request.story_text and not request.subreddit:
            return RedditStoryResponse(
                success=False,
                message="Either story_url, story_text, or subreddit must be provided",
                error="Missing required field"
            )
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Initialize job tracking
        _jobs[job_id] = {
            "status": "pending",
            "progress": 0.0,
            "message": "Job created, waiting to start",
            "story_id": None,
            "video_path": None,
            "error": None,
            "metadata": {},
            "created_at": asyncio.get_event_loop().time(),
        }
        
        # Add background task
        background_tasks.add_task(process_reddit_story_background, job_id, request)
        
        logger.info(f"Started Reddit story processing job: {job_id}")
        
        return RedditStoryResponse(
            success=True,
            message="Reddit story processing started in background",
            job_id=job_id,
            metadata={
                "job_id": job_id,
                "status": "pending",
                "estimated_time": "Processing time varies based on story length",
            }
        )
        
    except Exception as e:
        logger.error(f"Error starting Reddit story processing: {e}")
        return RedditStoryResponse(
            success=False,
            message="Failed to start Reddit story processing",
            error=str(e)
        )


@app.get("/reddit-story/status/{job_id}", response_model=RedditStoryStatus)
async def get_reddit_story_status(job_id: str):
    """
    Get the status of a Reddit story processing job.
    
    Args:
        job_id: Job ID returned by /generate/reddit-story
        
    Returns:
        Current status, progress, and result if available
    """
    if job_id not in _jobs:
        raise HTTPException(
            status_code=404,
            detail=f"Job not found: {job_id}"
        )
    
    job = _jobs[job_id]
    
    return RedditStoryStatus(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        story_id=job.get("story_id"),
        video_path=job.get("video_path"),
        error=job.get("error"),
        metadata=job.get("metadata", {}),
    )


@app.get("/reddit-story/jobs")
async def list_reddit_story_jobs():
    """
    List all Reddit story processing jobs.
    
    Returns:
        List of job IDs and their statuses
    """
    jobs_list = []
    for job_id, job in _jobs.items():
        jobs_list.append({
            "job_id": job_id,
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "story_id": job.get("story_id"),
            "created_at": job.get("created_at"),
        })
    
    # Sort by creation time (newest first)
    jobs_list.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    
    return {
        "total_jobs": len(jobs_list),
        "jobs": jobs_list,
    }


@app.get("/reddit-story/themes")
async def get_reddit_story_themes():
    """
    Get available background themes for Reddit stories.
    
    Returns:
        List of available theme names
    """
    try:
        background_manager = BackgroundManager()
        themes = background_manager.get_available_themes()
        
        return {
            "success": True,
            "themes": themes,
            "total_themes": len(themes),
        }
    except Exception as e:
        logger.error(f"Error getting themes: {e}")
        return {
            "success": False,
            "themes": [],
            "error": str(e),
        }


@app.get("/reddit-story/voices")
async def get_reddit_story_voices():
    """
    Get available voices for Reddit stories using Edge TTS engine.
    
    Returns:
        List of available voice IDs and names for Edge TTS
    """
    try:
        from config.settings import settings
        
        # Get voices from Edge TTS
        async with await get_tts_client() as tts_client:
            voices = await tts_client.get_available_voices()
        
        # Format voice information for Edge TTS
        formatted_voices = []
        for voice in voices:
            formatted_voices.append({
                "voice_id": voice.get("voice_id", voice.get("ShortName", "")),
                "name": voice.get("name", voice.get("FriendlyName", "")),
                "category": voice.get("category", voice.get("Locale", "")),
                "description": voice.get("description", f"Edge TTS voice: {voice.get('FriendlyName', 'Unknown')}"),
                "preview_url": voice.get("preview_url", ""),
                "engine": "edge",  # Only Edge TTS is supported
            })
        
        message = f"Using Microsoft Edge TTS (free) with {len(formatted_voices)} available voices"
        
        return {
            "success": True,
            "voices": formatted_voices,
            "total_voices": len(formatted_voices),
            "engine": "edge",
            "message": message,
        }
    except Exception as e:
        logger.error(f"Error getting voices: {e}")
        return {
            "success": False,
            "voices": [],
            "engine": "edge",
            "error": str(e),
        }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "service": "shorts-generator-backend-v2",
        "version": "2.0.0",
        "features": [
            "automated_pipeline",
            "ai_transcription",
            "word_level_sync",
            "ass_subtitles",
            "9:16_reframing"
        ]
    }

@app.get("/system-info")
async def system_info():
    """Get system information and pipeline status."""
    try:
        # Check if faster-whisper is available
        import faster_whisper
        whisper_status = "available"
    except ImportError:
        whisper_status = "not_available"
    
    try:
        import ffmpeg
        ffmpeg_status = "available"
    except ImportError:
        ffmpeg_status = "not_available"
    
    return {
        "pipeline_components": {
            "faster_whisper": whisper_status,
            "ffmpeg_python": ffmpeg_status,
            "tempfile": "available",
            "pathlib": "available"
        },
        "directories": {
            "uploads": str(UPLOAD_DIR.absolute()),
            "outputs": str(OUTPUT_DIR.absolute()),
            "uploads_exists": UPLOAD_DIR.exists(),
            "outputs_exists": OUTPUT_DIR.exists()
        },
        "supported_formats": [".mp4", ".avi", ".mkv", ".mov", ".webm"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
