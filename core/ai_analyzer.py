"""
AI Analyzer for Streamer Clipper.
Takes word-level timestamps, formats them, and uses an LLM to find viral clip opportunities.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI

from core.models import WordTimestamp

# Configure logging
logger = logging.getLogger(__name__)

class AIAnalyzer:
    """Analyzes transcripts to find the best viral clip moments."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.deepseek.com/v1"):
        """
        Initializes the AI client. 
        Defaults to DeepSeek, but can be easily pointed to OpenRouter or OpenAI.
        """
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            logger.warning("DEEPSEEK_API_KEY is not set. Analysis will fail if not provided.")
            
        self.client = OpenAI(api_key=self.api_key, base_url=base_url) if self.api_key else None
        self.model_name = "deepseek-chat" # שנה ל-"deepseek-reasoner" אם אתה רוצה את R1
        logger.info("AIAnalyzer initialized.")

    def _prepare_transcript_for_llm(self, words: List[WordTimestamp], chunk_duration: int = 15) -> str:
        """
        Groups word timestamps into blocks of X seconds so the LLM can read the timeline easily.
        Example output:
        [0.0 - 15.0] Hey guys welcome back to the stream today we are playing
        [15.0 - 30.0] some Minecraft and oh my god what is that creeper doing
        """
        if not words:
            return ""
            
        transcript_blocks = []
        current_chunk_words = []
        current_chunk_start = words[0].start
        
        for w in words:
            if w.start >= current_chunk_start + chunk_duration:
                # Close current block
                text = " ".join(current_chunk_words)
                transcript_blocks.append(f"[{current_chunk_start:.1f} - {w.start:.1f}] {text}")
                # Start new block
                current_chunk_words = [w.word]
                current_chunk_start = w.start
            else:
                current_chunk_words.append(w.word)
                
        # Add the remaining words in the last block
        if current_chunk_words:
            text = " ".join(current_chunk_words)
            end_time = words[-1].end
            transcript_blocks.append(f"[{current_chunk_start:.1f} - {end_time:.1f}] {text}")
            
        return "\n".join(transcript_blocks)

    def find_viral_clips(self, word_timestamps: List[WordTimestamp]) -> Optional[List[Dict[str, Any]]]:
        """
        Sends the formatted transcript to the LLM and asks for viral clip coordinates.
        
        Args:
            word_timestamps: List of WordTimestamp objects from the transcriber.
            
        Returns:
            A list of dictionaries, each containing: 
            'title', 'start_time', 'end_time', 'viral_score', 'reason'
        """
        if not self.client:
            logger.error("AI client is not initialized. Check your API key.")
            return None
            
        if not word_timestamps:
            logger.error("Empty transcript provided to AI.")
            return None

        formatted_transcript = self._prepare_transcript_for_llm(word_timestamps)
        logger.info(f"Prepared transcript for LLM: {len(formatted_transcript)} characters.")

        system_prompt = """You are an expert viral TikTok and YouTube Shorts editor.
Your task is to analyze the following video transcript (which includes timestamps in brackets) and find the absolute best 30 to 60-second segments that would make highly engaging, viral clips.

Look for:
- Funny reactions or fails.
- Interesting stories or strong opinions.
- Dramatic or exciting gaming moments.

Return your response ONLY as a valid JSON array of objects. Do not wrap it in markdown block quotes (` ```json `).
Each object MUST have the following keys exactly:
- "title": A catchy, clickbait-style title for the clip.
- "start_time": The exact start time in seconds (float).
- "end_time": The exact end time in seconds (float).
- "viral_score": A number from 1 to 10 predicting its viral potential.
- "reason": A short sentence explaining why this clip is good.

Output ONLY the raw JSON array. No conversational text."""

        try:
            logger.info("Sending transcript to LLM for analysis...")
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": formatted_transcript}
                ],
                temperature=0.3, # נמוך כדי לקבל JSON יציב וזמנים מדויקים
                max_tokens=2000
            )
            
            # Extract JSON string
            json_response = response.choices[0].message.content.strip()
            
            # Clean up potential markdown formatting if the model ignored the instruction
            if json_response.startswith("```json"):
                json_response = json_response[7:]
            if json_response.endswith("```"):
                json_response = json_response[:-3]
                
            clips = json.loads(json_response.strip())
            
            # Basic validation
            valid_clips = []
            for clip in clips:
                if all(k in clip for k in ("start_time", "end_time", "title")):
                    valid_clips.append(clip)
            
            logger.info(f"AI successfully found {len(valid_clips)} viral clips!")
            return valid_clips

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON. Response was: {json_response}")
            return None
        except Exception as e:
            logger.error(f"Error during AI analysis: {e}")
            return None