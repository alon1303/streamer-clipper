import logging
from pathlib import Path
from dotenv import load_dotenv

from core.downloader import VideoDownloader
from core.chat_analyzer import ChatAnalyzer
from video_processing.video_composer import process_stream_into_clips

# הגדרת לוגים
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestClipper")

def main():
    load_dotenv()
    
    temp_dir = Path("temp")
    output_dir = Path("output")
    temp_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    
    downloader = VideoDownloader(temp_dir=str(temp_dir))
    chat_analyzer = ChatAnalyzer(bucket_size_seconds=15)
    
    video_url = input("Enter Twitch Video URL for testing: ")
    minutes_str = input("Enter number of minutes to analyze (e.g., 30): ")
    
    try:
        minutes = int(minutes_str)
    except ValueError:
        logger.warning("Invalid input for minutes. Defaulting to 20 minutes.")
        minutes = 20
        
    duration_seconds = minutes * 60
    
    logger.info(f"--- Starting TEST Analysis for the first {minutes} minutes ---")
    
    # 1. הורדת צ'אט ווידאו (המוריד כבר מבצע אופטימיזציה ל-JSON)
    download_result = downloader.download(video_url, duration_limit_seconds=duration_seconds)
    
    if not download_result:
        logger.error("Download failed. Exiting.")
        return
        
    full_video_path, full_audio_path, chat_path = download_result
    
    # 2. ניתוח צ'אט והצגת רגעי השיא
    logger.info("Step 2: Identifying Hype Moments from Chat...")
    hype_moments = chat_analyzer.find_hype_moments(Path(chat_path), top_k=5, clip_duration=60)
    
    if not hype_moments:
        logger.error("No hype moments found in the chat for this segment.")
        return

    print("\n" + "="*50)
    print(f"🔥 DETECTED HYPE MOMENTS (First {minutes} min) 🔥")
    print("="*50)
    for i, moment in enumerate(hype_moments, 1):
        start_min = int(moment['start_time'] // 60)
        start_sec = int(moment['start_time'] % 60)
        end_min = int(moment['end_time'] // 60)
        end_sec = int(moment['end_time'] % 60)
        
        print(f"Moment #{i}:")
        print(f"  - Start Time: {start_min:02d}:{start_sec:02d} ({moment['start_time']:.1f}s)")
        print(f"  - End Time:   {end_min:02d}:{end_sec:02d} ({moment['end_time']:.1f}s)")
        print(f"  - Traffic Score: {moment['score']} messages in 15s")
        print(f"  - Reason: {moment['reason']}")
        print("-" * 30)
    print("="*50 + "\n")

    # 3. בחירה האם להמשיך לעיבוד וידאו מלא
    user_choice = input("Do you want to proceed with full AI transcription and clipping? (y/n): ")
    
    if user_choice.lower() == 'y':
        logger.info("Proceeding to full pipeline...")
        result = process_stream_into_clips(
            str(full_video_path), 
            str(full_audio_path), 
            str(chat_path), 
            str(output_dir)
        )
        
        if result.get('success'):
            logger.info(f"🎉 Pipeline finished! Created {result.get('videos_created')} clips.")
        else:
            logger.error(f"Pipeline failed: {result.get('error')}")
    else:
        logger.info("Test finished. You can now check the timestamps above in the original video.")

if __name__ == "__main__":
    main()