import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ChatAnalyzer:
    def __init__(self, bucket_size_seconds: int = 15):
        self.bucket_size = bucket_size_seconds

    def find_hype_moments(self, chat_path: Path, top_k: int = 5, clip_duration: int = 60) -> List[Dict[str, Any]]:
        if not chat_path or not chat_path.exists():
            return []

        logger.info(f"Analyzing chat traffic patterns...")
        try:
            with open(chat_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                timestamps = data.get('timestamps', [])
        except Exception as e:
            logger.error(f"Error reading chat JSON: {e}")
            return []
        
        if not timestamps:
            return []

        # ספירה ב"דליים"
        buckets = defaultdict(int)
        for ts in timestamps:
            bucket_idx = int(ts) // self.bucket_size
            buckets[bucket_idx] += 1

        sorted_buckets = sorted(buckets.items(), key=lambda x: x[1], reverse=True)

        hype_moments = []
        used_ranges = []

        for bucket_idx, count in sorted_buckets:
            peak_time = bucket_idx * self.bucket_size
            # מתחילים 45 שניות לפני שיא הצ'אט כדי לתפוס את האירוע בוידאו
            start_time = max(0.0, float(peak_time - 45))
            end_time = start_time + float(clip_duration)

            overlap = False
            for r_start, r_end in used_ranges:
                if max(start_time, r_start) < min(end_time, r_end):
                    overlap = True
                    break
            
            if not overlap:
                used_ranges.append((start_time, end_time))
                hype_moments.append({
                    "start_time": start_time,
                    "end_time": end_time,
                    "score": count
                })

            if len(hype_moments) >= top_k:
                break

        return sorted(hype_moments, key=lambda x: x["start_time"])