"""
YouTube Data API v3 uploader for ShortsGenerator project.
Handles OAuth2 authentication, video upload, and metadata management.
"""

import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import time

# Google API imports
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.exceptions import RefreshError, GoogleAuthError

# Configure logging
logger = logging.getLogger(__name__)

# If modifying these scopes, delete the file token.json
# Need both upload and read permissions: upload for uploading, read for fetching video details
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly'  # Added for reading video details after upload
]

@dataclass
class YouTubeUploadResult:
    """Result of a YouTube upload operation."""
    success: bool
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[int] = None
    quota_exceeded: bool = False
    metadata: Optional[Dict[str, Any]] = None

class YouTubeUploader:
    """YouTube uploader with OAuth2 token management."""
    
    def __init__(
        self, 
        client_secrets_path: Optional[Path] = None,
        token_path: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        max_retries: int = 3,
        retry_delay: int = 5,
    ):
        """
        Initialize YouTube uploader.
        
        Args:
            client_secrets_path: Path to client_secrets.json (default: backend_v2/client_secrets.json)
            token_path: Path to token.json (default: backend_v2/youtube/token.json)
            data_dir: Directory for storing tokens and logs (default: backend_v2/youtube)
            max_retries: Maximum number of retry attempts for upload
            retry_delay: Delay between retries in seconds
        """
        # Set up paths
        if data_dir is None:
            self.data_dir = Path(__file__).parent
        else:
            self.data_dir = Path(data_dir)
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        if client_secrets_path is None:
            self.client_secrets_path = Path(__file__).parent.parent / "client_secrets.json"
        else:
            self.client_secrets_path = Path(client_secrets_path)
        
        if token_path is None:
            self.token_path = self.data_dir / "token.json"
        else:
            self.token_path = Path(token_path)
        
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # YouTube API service
        self.service = None
        self.credentials = None
        
        # Try to generate client_secrets.json from environment variables if file doesn't exist
        self._generate_client_secrets_from_env()
        
        logger.info(f"YouTube uploader initialized")
        logger.info(f"  Client secrets: {self.client_secrets_path}")
        logger.info(f"  Token file: {self.token_path}")
        logger.info(f"  Data directory: {self.data_dir}")
    
    def _generate_client_secrets_from_env(self) -> bool:
        """
        Generate client_secrets.json from environment variables if it doesn't exist.
        
        Returns:
            True if file exists or was successfully generated, False otherwise
        """
        if self.client_secrets_path.exists():
            return True
        
        # Try to get credentials from environment variables
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        project_id = os.getenv("GOOGLE_PROJECT_ID")
        
        if not all([client_id, client_secret, project_id]):
            logger.warning(
                "client_secrets.json not found and environment variables not set. "
                "Please set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_PROJECT_ID "
                "in your .env file or obtain client_secrets.json from Google Cloud Console."
            )
            return False
        
        try:
            # Create client_secrets.json structure from environment variables
            client_secrets = {
                "web": {
                    "client_id": client_id,
                    "project_id": project_id,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_secret": client_secret
                }
            }
            
            # Write to file
            with open(self.client_secrets_path, 'w') as f:
                json.dump(client_secrets, f, indent=2)
            
            logger.info(f"Generated client_secrets.json from environment variables")
            logger.info(f"  Client ID: {client_id[:10]}...")
            logger.info(f"  Project ID: {project_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to generate client_secrets.json: {e}")
            return False
    
    def get_authenticated_service(self) -> Optional[Any]:
        """
        Get authenticated YouTube API service.
        Handles OAuth2 token management and refresh.
        
        Returns:
            YouTube API service object or None if authentication fails
        """
        try:
            # Check if client secrets file exists
            if not self.client_secrets_path.exists():
                # Try to generate from environment variables
                if not self._generate_client_secrets_from_env():
                    logger.error(f"Client secrets file not found: {self.client_secrets_path}")
                    logger.error("Please either:")
                    logger.error("1. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_PROJECT_ID in .env")
                    logger.error("2. Obtain client_secrets.json from Google Cloud Console")
                    logger.error("3. Enable YouTube Data API v3 and create OAuth 2.0 credentials")
                    return None
            
            # Load or get credentials
            credentials = None
            if self.token_path.exists():
                try:
                    credentials = Credentials.from_authorized_user_file(
                        str(self.token_path), SCOPES
                    )
                    logger.info(f"Loaded credentials from {self.token_path}")
                except Exception as e:
                    logger.warning(f"Error loading credentials: {e}")
                    credentials = None
            
            # If credentials don't exist or are invalid, get new ones
            if not credentials or not credentials.valid:
                if credentials and credentials.expired and credentials.refresh_token:
                    try:
                        credentials.refresh(Request())
                        logger.info("Credentials refreshed successfully")
                    except RefreshError as e:
                        logger.warning(f"Failed to refresh credentials: {e}")
                        credentials = None
            
            # If still no valid credentials, initiate OAuth flow
            if not credentials or not credentials.valid:
                logger.info("Initiating OAuth2 flow...")
                
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.client_secrets_path), SCOPES
                    )
                    
                    # For headless environments, you might need to use different flow
                    # For now, use local server which opens browser
                    credentials = flow.run_local_server(port=8080)
                    
                    # Save the credentials for next run
                    with open(self.token_path, 'w') as token_file:
                        token_file.write(credentials.to_json())
                    
                    logger.info(f"Credentials saved to {self.token_path}")
                    
                except Exception as e:
                    logger.error(f"OAuth2 flow failed: {e}")
                    logger.error("For headless environments, you may need to:")
                    logger.error("1. Run once locally to get refresh token")
                    logger.error("2. Copy token.json to production")
                    return None
            
            # Save credentials if they were refreshed
            if credentials and credentials.valid:
                with open(self.token_path, 'w') as token_file:
                    token_file.write(credentials.to_json())
            
            # Build YouTube API service
            self.service = build('youtube', 'v3', credentials=credentials)
            self.credentials = credentials
            
            logger.info("YouTube API service authenticated successfully")
            return self.service
            
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return None
    
    def _extract_quota_error(self, error: Dict) -> Tuple[bool, Optional[str]]:
        """
        Extract quota error information from API error.
        
        Args:
            error: Error dictionary from Google API
        
        Returns:
            Tuple of (quota_exceeded, error_message)
        """
        try:
            error_details = error.get('error', {})
            errors = error_details.get('errors', [])
            
            for err in errors:
                reason = err.get('reason', '').lower()
                domain = err.get('domain', '').lower()
                message = err.get('message', '')
                
                # Check for quota-related errors
                if any(quota_term in reason for quota_term in ['quota', 'rate', 'limit']):
                    return True, message
                
                if any(quota_term in domain for quota_term in ['usageLimits', 'quota']):
                    return True, message
            
            return False, error_details.get('message', str(error))
        except Exception:
            return False, str(error)
    
    def upload_video(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = "22",  # People & Blogs category
        privacy_status: str = "public",  # public, private, unlisted
        notify_subscribers: bool = False,
        is_shorts: bool = True,
    ) -> YouTubeUploadResult:
        """
        Upload a video to YouTube.
        
        Args:
            video_path: Path to video file
            title: Video title (will append #shorts if is_shorts=True)
            description: Video description
            tags: List of tags
            category_id: YouTube category ID (default: 22 - People & Blogs)
            privacy_status: Video privacy status
            notify_subscribers: Whether to notify subscribers
            is_shorts: Whether this is a YouTube Short (adds #shorts tag)
        
        Returns:
            YouTubeUploadResult with success status and details
        """
        try:
            # Validate input
            if not video_path.exists():
                return YouTubeUploadResult(
                    success=False,
                    error_message=f"Video file not found: {video_path}",
                )
            
            # Ensure file size is reasonable
            file_size_mb = video_path.stat().st_size / (1024 * 1024)
            if file_size_mb > 256:  # YouTube's maximum for Shorts
                logger.warning(f"Video file size ({file_size_mb:.1f}MB) exceeds typical Shorts limit")
            
            # Get authenticated service
            if not self.service:
                service = self.get_authenticated_service()
                if not service:
                    return YouTubeUploadResult(
                        success=False,
                        error_message="Failed to authenticate with YouTube API",
                    )
            
            # Prepare metadata
            if is_shorts:
                # Ensure #shorts is in title and description
                if "#shorts" not in title.lower():
                    title = f"{title} #shorts"
                
                if "#shorts" not in description.lower():
                    description = f"{description}\n\n#shorts"
            
            # Add Reddit attribution if not already present
            if "reddit" not in description.lower():
                description = f"{description}\n\nGenerated from Reddit story using ShortsGenerator"
            
            # Prepare request body
            body = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'tags': tags,
                    'categoryId': category_id,
                },
                'status': {
                    'privacyStatus': privacy_status,
                    'selfDeclaredMadeForKids': False,
                    'notifySubscribers': notify_subscribers,
                },
            }
            
            # Create media upload
            media = MediaFileUpload(
                str(video_path),
                chunksize=1024*1024,  # 1MB chunks
                resumable=True,
                mimetype='video/mp4'
            )
            
            logger.info(f"Uploading video: {video_path.name}")
            logger.info(f"  Title: {title}")
            logger.info(f"  Description length: {len(description)} chars")
            logger.info(f"  Tags: {len(tags)} tags")
            logger.info(f"  File size: {file_size_mb:.1f} MB")
            
            # Execute upload with retry logic
            for attempt in range(self.max_retries):
                try:
                    if attempt > 0:
                        wait_time = self.retry_delay * (2 ** (attempt - 1))  # Exponential backoff
                        logger.info(f"Retry attempt {attempt + 1}/{self.max_retries} after {wait_time}s")
                        time.sleep(wait_time)
                    
                    # Insert request
                    request = self.service.videos().insert(
                        part=','.join(body.keys()),
                        body=body,
                        media_body=media
                    )
                    
                    # Execute upload
                    response = request.execute()
                    
                    video_id = response.get('id')
                    video_url = f"https://youtube.com/watch?v={video_id}"
                    
                    logger.info(f"Upload successful!")
                    logger.info(f"  Video ID: {video_id}")
                    logger.info(f"  Video URL: {video_url}")
                    
                    # Get video details
                    video_details = self._get_video_details(video_id)
                    
                    return YouTubeUploadResult(
                        success=True,
                        video_id=video_id,
                        video_url=video_url,
                        metadata={
                            'response': response,
                            'details': video_details,
                            'file_size_mb': file_size_mb,
                            'upload_time': datetime.now().isoformat(),
                        }
                    )
                    
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Upload attempt {attempt + 1} failed: {error_msg}")
                    
                    # Check for quota errors
                    if hasattr(e, 'error_details') and e.error_details:
                        error_data = json.loads(e.error_details) if isinstance(e.error_details, str) else e.error_details
                        quota_exceeded, quota_message = self._extract_quota_error(error_data)
                        
                        if quota_exceeded:
                            logger.error(f"Quota exceeded: {quota_message}")
                            return YouTubeUploadResult(
                                success=False,
                                error_message=f"YouTube API quota exceeded: {quota_message}",
                                error_code=getattr(e, 'status_code', None),
                                quota_exceeded=True,
                            )
                    
                    # Check if we should retry
                    if attempt == self.max_retries - 1:
                        logger.error(f"All {self.max_retries} upload attempts failed")
                        return YouTubeUploadResult(
                            success=False,
                            error_message=f"Upload failed after {self.max_retries} attempts: {error_msg}",
                            error_code=getattr(e, 'status_code', None),
                        )
            
            # Should not reach here
            return YouTubeUploadResult(
                success=False,
                error_message="Upload failed",
            )
            
        except Exception as e:
            logger.error(f"Error in upload_video: {e}")
            return YouTubeUploadResult(
                success=False,
                error_message=f"Upload error: {str(e)}",
            )
    
    def _get_video_details(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        Get video details after upload.
        
        Args:
            video_id: YouTube video ID
        
        Returns:
            Video details dictionary or None if failed
        """
        try:
            if not self.service:
                return None
            
            request = self.service.videos().list(
                part="snippet,contentDetails,statistics,status",
                id=video_id
            )
            response = request.execute()
            
            items = response.get('items', [])
            if items:
                return items[0]
            return None
            
        except Exception as e:
            logger.warning(f"Failed to get video details: {e}")
            return None
    
    def check_quota_status(self) -> Dict[str, Any]:
        """
        Check YouTube API quota status.
        
        Returns:
            Dictionary with quota information
        """
        try:
            # Note: YouTube API doesn't provide direct quota information
            # We can only infer from rate limit errors
            return {
                'success': True,
                'message': 'YouTube API quota cannot be checked directly',
                'recommendations': [
                    'Monitor quota in Google Cloud Console',
                    'Limit uploads to avoid quota exhaustion',
                    'Consider applying for quota increase if needed',
                ]
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }
    
    def validate_credentials(self) -> bool:
        """
        Validate if credentials are valid and can authenticate.
        
        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            if not self.token_path.exists():
                logger.warning(f"Token file not found: {self.token_path}")
                return False
            
            credentials = Credentials.from_authorized_user_file(
                str(self.token_path), SCOPES
            )
            
            if not credentials.valid:
                if credentials.expired and credentials.refresh_token:
                    try:
                        credentials.refresh(Request())
                        return True
                    except RefreshError:
                        return False
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating credentials: {e}")
            return False
    
    def generate_default_tags(self, subreddit: str, story_title: str) -> List[str]:
        """
        Generate default tags for a Reddit story video.
        
        Args:
            subreddit: Source subreddit
            story_title: Story title
        
        Returns:
            List of tags
        """
        tags = [
            "#shorts",
            "reddit",
            "redditstories",
            "redditreads",
            "storytime",
            "shorts",
            "youtubeshorts",
        ]
        
        # Add subreddit-specific tags
        if subreddit:
            tags.append(subreddit.lower())
            tags.append(f"r/{subreddit.lower()}")
        
        # Extract keywords from story title
        title_words = story_title.lower().split()
        keywords = [word for word in title_words if len(word) > 3][:5]
        tags.extend(keywords)
        
        # Add generic tags
        tags.extend([
            "story",
            "narration",
            "texttospeech",
            "tts",
            "redditthread",
            "internetstories",
        ])
        
        # Ensure no duplicates and limit to YouTube's max (500 chars total, ~20-30 tags)
        unique_tags = list(dict.fromkeys(tags))[:25]
        
        return unique_tags
    
    @staticmethod
    def truncate_title_for_youtube(title: str, max_length: int = 100, suffix: str = "...") -> str:
        """
        Truncate title to fit YouTube's character limit.
        YouTube titles must be 100 characters or less.
        
        Args:
            title: Original title
            max_length: Maximum allowed length (default: 100 for YouTube)
            suffix: Suffix to add when truncating (default: "...")
        
        Returns:
            Truncated title that fits within max_length
        """
        if len(title) <= max_length:
            return title
        
        # Calculate available length for title content (minus suffix)
        available_length = max_length - len(suffix)
        
        # Truncate to available length, ensuring we don't cut in the middle of a word
        truncated = title[:available_length]
        
        # Try to find the last space to avoid cutting words
        last_space = truncated.rfind(' ')
        if last_space > available_length * 0.8:  # Only use if we're not losing too much
            truncated = truncated[:last_space]
        
        return truncated + suffix
    
    def generate_description(self, story_title: str, subreddit: str, reddit_url: str, video_parts: int = 1) -> str:
        """
        Generate YouTube description for a Reddit story video.
        
        Args:
            story_title: Reddit story title
            subreddit: Source subreddit
            reddit_url: Original Reddit URL
            video_parts: Number of video parts (for multi-part stories)
        
        Returns:
            YouTube description string
        """
        description = f"{story_title}\n\n"
        
        description += f"Original Reddit post from r/{subreddit}:\n"
        description += f"{reddit_url}\n\n"
        
        if video_parts > 1:
            description += f"This story is split into {video_parts} parts for optimal viewing.\n\n"
        
        description += "---\n"
        description += "⚠️ DISCLAIMER: This content is automatically generated from publicly available Reddit posts.\n"
        description += "All stories are narrated using text-to-speech technology.\n\n"
        
        description += "📱 Generated by ShortsGenerator - Automated Reddit Stories to YouTube Shorts\n"
        description += "This video was created using AI narration and automated video editing.\n\n"
        
        description += "#shorts #reddit #redditstories #storytime #redditreads\n"
        description += f"#{subreddit.lower()} #redditthread #internetstories\n\n"
        
        description += "Like and subscribe for more Reddit stories!"
        
        return description


class AsyncYouTubeUploader:
    """Async wrapper for YouTubeUploader."""
    
    def __init__(self, uploader: YouTubeUploader):
        self.uploader = uploader
    
    async def upload_video_async(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = "22",
        privacy_status: str = "public",
        notify_subscribers: bool = False,
        is_shorts: bool = True,
    ) -> YouTubeUploadResult:
        """
        Async wrapper for upload_video.
        
        Args:
            Same as YouTubeUploader.upload_video
        
        Returns:
            YouTubeUploadResult
        """
        # Run in thread pool since Google API is blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.uploader.upload_video(
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                category_id=category_id,
                privacy_status=privacy_status,
                notify_subscribers=notify_subscribers,
                is_shorts=is_shorts,
            )
        )


# Example usage and testing
async def example_usage():
    """Example usage of the YouTube uploader."""
    import sys
    from pathlib import Path
    
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Create uploader
    uploader = YouTubeUploader()
    
    # Test credentials
    if not uploader.validate_credentials():
        print("Credentials not valid. Starting OAuth2 flow...")
        service = uploader.get_authenticated_service()
        if not service:
            print("Failed to authenticate. Exiting.")
            return
    
    # Example video path (use a test file)
    test_video = Path(__file__).parent.parent / "outputs" / "test_video.mp4"
    if not test_video.exists():
        print(f"Test video not found: {test_video}")
        print("Please create a test video first")
        return
    
    # Generate metadata
    title = "My Reddit Story #shorts"
    description = uploader.generate_description(
        story_title="AITA for refusing to give my mom my savings?",
        subreddit="AmItheAsshole",
        reddit_url="https://www.reddit.com/r/AmItheAsshole/comments/abc123/",
        video_parts=1,
    )
    tags = uploader.generate_default_tags("AmItheAsshole", "AITA for refusing to give my mom my savings?")
    
    print(f"Uploading test video: {test_video}")
    print(f"Title: {title}")
    print(f"Description preview: {description[:200]}...")
    print(f"Tags: {', '.join(tags[:10])}...")
    
    # Upload (commented out to prevent accidental upload)
    # result = uploader.upload_video(
    #     video_path=test_video,
    #     title=title,
    #     description=description,
    #     tags=tags,
    #     is_shorts=True,
    #     privacy_status="private",  # Use private for testing
    # )
    
    # print(f"\nResult: {result}")
    
    print("\nExample usage complete. Uncomment the upload line to actually upload.")


if __name__ == "__main__":
    # Run example if executed directly
    asyncio.run(example_usage())