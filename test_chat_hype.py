import logging
from pathlib import Path
from core.downloader import VideoDownloader
from core.chat_analyzer import ChatAnalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ChatHypeTest")

def main():
    url = input("Enter Twitch URL: ")
    mins = int(input("How many minutes to analyze from start? "))
    
    downloader = VideoDownloader()
    analyzer = ChatAnalyzer()
    
    logger.info(f"Step 1: Downloading chat for the first {mins} minutes...")
    chat_file = downloader.download(url, duration_limit_seconds=mins * 60)
    
    if not chat_file:
        logger.error("Failed to get chat data.")
        return

    logger.info("Step 2: Finding top 5 high-traffic moments...")
    moments = analyzer.find_hype_moments(chat_file, top_k=5)
    
    print("\n" + "!"*30)
    print("TOP 5 VIRAL CANDIDATES FOUND")
    print("!"*30)
    
    for i, m in enumerate(moments, 1):
        s_min, s_sec = divmod(int(m['start_time']), 60)
        e_min, e_sec = divmod(int(m['end_time']), 60)
        print(f"{i}. TIME: {s_min:02d}:{s_sec:02d} to {e_min:02d}:{e_sec:02d} | TRAFFIC: {m['score']} msgs")
    
    print("\nCheck these timestamps manually in the stream to see if they are interesting!")

if __name__ == "__main__":
    main()