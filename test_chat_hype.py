import logging
from pathlib import Path
from core.chat_analyzer import ChatAnalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LocalTest")

def main():
    print("\n" + "="*50)
    print("   LOCAL CHAT TRAFFIC & SPIKE ANALYSIS")
    print("="*50)
    
    file_path = input("Enter the path to your JSON file: ")
    chat_path = Path(file_path)
    
    if not chat_path.exists():
        print(f"❌ Error: File not found at {file_path}")
        return

    analyzer = ChatAnalyzer(bucket_size_seconds=15)
    moments = analyzer.find_hype_moments(chat_path, top_k=10) # נבדוק 10 רגעים הפעם
    
    if not moments:
        print("❌ No data found.")
        return

    avg_score = moments[0]['avg_stream_score']
    print(f"\n📊 Stream Statistics:")
    print(f"   Average Score per 15s: {avg_score:.2f}")
    print("-" * 50)
    
    print(f"{'#':<3} | {'Time Range':<15} | {'Score':<7} | {'% Above Avg':<12}")
    print("-" * 50)
    
    for i, m in enumerate(moments, 1):
        s_min, s_sec = divmod(int(m['start_time']), 60)
        e_min, e_sec = divmod(int(m['end_time']), 60)
        time_str = f"{s_min:02d}:{s_sec:02d}-{e_min:02d}:{e_sec:02d}"
        
        # הדגשה מיוחדת לזינוקים מעל 100%
        spike_str = f"{m['percent_above_avg']:+.1f}%"
        if m['percent_above_avg'] > 100:
            spike_str = f"🔥 {spike_str}"
            
        print(f"{i:<3} | {time_str:<15} | {m['score']:<7.0f} | {spike_str:<12}")
    
    print("-" * 50)
    print("\nRecommendation: Focus on clips with > 100% spike for better results.\n")

if __name__ == "__main__":
    main()