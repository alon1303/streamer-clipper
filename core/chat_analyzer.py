"""
Smart Chat Analyzer for Streamer Clipper.
Calculates 'Spike Percentage' relative to the stream's average traffic.
"""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ChatAnalyzer:
    def __init__(self, bucket_size_seconds: int = 15):
        self.bucket_size = bucket_size_seconds
        # מילות מפתח ומשקלים לסינון איכותי
        self.weights = {
            "lol": 5, "lmao": 5, "laugh": 5, "חחח": 5, "💀": 5, "😂": 5,
            "pog": 8, "pogchamp": 8, "w": 3, "clutch": 10, "insane": 10,
            "omg": 7, "no way": 8, "holy": 7, "😲": 7, "😱": 7,
            "f": 4, "rip": 4, "fail": 6, "L": 2
        }

    def _parse_chat_json(self, json_path: Path) -> List[Dict[str, Any]]:
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # תמיכה בפורמט האופטימלי (רק זמנים)
            if 'timestamps' in data:
                return [{"time": int(ts), "text": ""} for ts in data['timestamps']]
            
            # תמיכה בפורמט הגולמי (כולל טקסט לניתוח משקלים)
            if 'comments' in data:
                return [
                    {
                        "time": int(c['content_offset_seconds']),
                        "text": c.get('message', {}).get('body', '').lower()
                    }
                    for c in data['comments'] if 'content_offset_seconds' in c
                ]
            return []
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            return []

    def _calculate_score(self, text: str) -> int:
        score = 1
        for word, weight in self.weights.items():
            if word in text:
                score += weight
        return score

    def find_hype_moments(self, chat_path: Path, top_k: int = 5, clip_duration: int = 60) -> List[Dict[str, Any]]:
        if not chat_path or not chat_path.exists():
            return []

        messages = self._parse_chat_json(chat_path)
        if not messages:
            return []

        # סכימת ניקוד בבלוקים
        buckets = defaultdict(int)
        for msg in messages:
            bucket_idx = msg['time'] // self.bucket_size
            buckets[bucket_idx] += self._calculate_score(msg['text'])

        # חישוב ממוצע כללי לבלוק (כדי להבין מהו "רעש רקע")
        total_score = sum(buckets.values())
        num_buckets = len(buckets)
        avg_score = total_score / num_buckets if num_buckets > 0 else 1

        sorted_buckets = sorted(buckets.items(), key=lambda x: x[1], reverse=True)

        hype_moments = []
        used_ranges = []

        for bucket_idx, score in sorted_buckets:
            # חישוב אחוז הזינוק מעל הממוצע
            # למשל: אם הממוצע הוא 10 והניקוד הוא 30, הזינוק הוא 200% מעל הממוצע
            percent_above_avg = ((score / avg_score) - 1) * 100
            
            peak_time = bucket_idx * self.bucket_size
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
                    "score": score,
                    "percent_above_avg": percent_above_avg,
                    "avg_stream_score": avg_score
                })

            if len(hype_moments) >= top_k:
                break

        return sorted(hype_moments, key=lambda x: x["start_time"])