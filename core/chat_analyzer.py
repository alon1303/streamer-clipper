"""
Chat Analyzer for Streamer Clipper.
Finds viral moments by detecting message velocity spikes (Hype) in chat replays.
"""

import re
import logging
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ChatAnalyzer:
    """Analyzes chat replay files to find the most active moments in a stream."""
    
    def __init__(self, bucket_size_seconds: int = 15):
        # We group messages into "buckets" of 15 seconds to measure velocity
        self.bucket_size = bucket_size_seconds
        logger.info("ChatAnalyzer initialized.")

    def _parse_vtt_timestamps(self, vtt_path: Path) -> List[int]:
        """Extracts the exact second each chat message was sent from the VTT file."""
        timestamps = []
        # Matches VTT timing lines like: 00:45:12.000 --> 00:45:15.000
        pattern = re.compile(r"(?:(\d{2}):)?(\d{2}):(\d{2})\.\d{3}\s*-->")
        
        try:
            with open(vtt_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    match = pattern.search(line)
                    if match:
                        h, m, s = match.groups()
                        h = int(h) if h else 0
                        total_seconds = h * 3600 + int(m) * 60 + int(s)
                        timestamps.append(total_seconds)
            return timestamps
        except Exception as e:
            logger.error(f"Failed to parse chat file: {e}")
            return []

    def find_hype_moments(self, chat_path: Path, top_k: int = 5, clip_duration: int = 60) -> List[Dict[str, Any]]:
        """
        Finds the biggest spikes in chat activity.
        
        Returns:
            List of dictionaries with 'start_time', 'end_time', and 'score' (message count).
        """
        if not chat_path or not chat_path.exists():
            logger.warning("No chat file provided to ChatAnalyzer.")
            return []

        logger.info(f"Analyzing chat velocity from {chat_path.name}...")
        timestamps = self._parse_vtt_timestamps(chat_path)
        
        if not timestamps:
            logger.warning("No messages found in chat file.")
            return []

        # Count messages per bucket
        buckets = defaultdict(int)
        for ts in timestamps:
            bucket_idx = ts // self.bucket_size
            buckets[bucket_idx] += 1

        # Sort buckets from most active to least active
        sorted_buckets = sorted(buckets.items(), key=lambda x: x[1], reverse=True)

        hype_moments = []
        used_ranges = []

        for bucket_idx, count in sorted_buckets:
            # The exact second the chat peaked
            peak_time = bucket_idx * self.bucket_size
            
            # THE SECRET SAUCE:
            # Chat usually reacts 15-20 seconds AFTER the funny thing happened on screen.
            # So if chat peaked at 01:00:20, the actual event probably started at 01:00:00.
            # We set start_time to 75% of the clip duration BEFORE the peak.
            start_time = max(0.0, float(peak_time - int(clip_duration * 0.75)))
            end_time = start_time + float(clip_duration)

            # Prevent overlapping clips (if a hype train lasted 3 minutes, we just want 1 clip)
            overlap = False
            for r_start, r_end in used_ranges:
                # If the proposed clip overlaps with an existing one
                if max(start_time, r_start) < min(end_time, r_end):
                    overlap = True
                    break
            
            if not overlap:
                used_ranges.append((start_time, end_time))
                hype_moments.append({
                    "start_time": start_time,
                    "end_time": end_time,
                    "score": count,
                    "reason": f"Chat exploded with {count} messages in {self.bucket_size}s."
                })

            if len(hype_moments) >= top_k:
                break

        # Sort the final clips chronologically (by start_time)
        hype_moments = sorted(hype_moments, key=lambda x: x["start_time"])
        logger.info(f"Found {len(hype_moments)} massive hype moments in chat!")
        return hype_moments