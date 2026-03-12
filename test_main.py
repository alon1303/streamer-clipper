import logging
from pathlib import Path
from dotenv import load_dotenv

from core.downloader import VideoDownloader
from video_processing.video_composer import process_stream_into_clips

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestClipper")

def main():
    load_dotenv()
    
    temp_dir = Path("temp")
    output_dir = Path("output")
    temp_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    
    downloader = VideoDownloader(temp_dir=str(temp_dir))
    
    video_url = input("Enter Stream/Video URL for testing: ")
    minutes_str = input("Enter number of minutes to test (e.g., 20): ")
    
    try:
        minutes = int(minutes_str)
    except ValueError:
        logger.warning("Invalid input for minutes. Defaulting to 20 minutes.")
        minutes = 20
        
    duration_seconds = minutes * 60
    
    logger.info(f"Starting TEST run for the first {minutes} minutes of the stream...")
    download_result = downloader.download(video_url, duration_limit_seconds=duration_seconds)
    
    if not download_result:
        logger.error("Download failed. Exiting.")
        return
        
    full_video_path, full_audio_path, chat_path = download_result
    chat_path_str = str(chat_path) if chat_path else None
    
    result = process_stream_into_clips(
        str(full_video_path), 
        str(full_audio_path), 
        chat_path_str, 
        str(output_dir)
    )
    
    if result.get('success'):
        logger.info(f"🎉 TEST Pipeline finished! Created {result.get('videos_created')} clips.")
    else:
        logger.error(f"TEST Pipeline failed: {result.get('error')}")

if __name__ == "__main__":
    main()