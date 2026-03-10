"""
Advanced Subtitle Generator for Shorts Videos.
Generates ASS subtitles with perfect timing, phrase-based chunking, and dynamic word highlighting.
Uses pysubs2 library for robust ASS file generation.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
import re
import pysubs2

from .models import WordTimestamp

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class Phrase:
    """Represents a phrase (group of words) for subtitle display."""
    words: List[WordTimestamp]
    start_time: float
    end_time: float
    text: str
    
    @property
    def word_count(self) -> int:
        return len(self.words)

class SubtitleGenerator:
    """Generates ASS subtitles with perfect timing and dynamic highlighting."""
    
    def __init__(
        self,
        video_width: int = 1080,
        video_height: int = 1920,
        max_words_per_phrase: int = 5,
        min_words_per_phrase: int = 2,
        max_phrase_duration: float = 3.0,  # seconds
        min_gap_between_phrases: float = 0.1,  # seconds
    ):
        """
        Initialize subtitle generator.
        
        Args:
            video_width: Video width in pixels
            video_height: Video height in pixels
            max_words_per_phrase: Maximum words per phrase
            min_words_per_phrase: Minimum words per phrase
            max_phrase_duration: Maximum duration for a phrase
            min_gap_between_phrases: Minimum gap between phrases to prevent overlap
        """
        self.video_width = video_width
        self.video_height = video_height
        self.max_words_per_phrase = max_words_per_phrase
        self.min_words_per_phrase = min_words_per_phrase
        self.max_phrase_duration = max_phrase_duration
        self.min_gap_between_phrases = min_gap_between_phrases
        
        logger.info(
            f"SubtitleGenerator initialized: "
            f"{video_width}x{video_height}, "
            f"{min_words_per_phrase}-{max_words_per_phrase} words/phrase"
        )
    
    def chunk_words_into_phrases(
        self,
        word_timestamps: List[WordTimestamp],
        audio_duration: float
    ) -> List[Phrase]:
        """
        Chunk words into phrases for optimal display.
        
        Rules:
        1. Phrases should have 2-5 words (configurable)
        2. Phrases should not exceed max_phrase_duration
        3. Gaps between words > 0.5s are natural phrase boundaries
        4. Ensure phrases don't overlap
        
        Args:
            word_timestamps: List of word timestamps
            audio_duration: Total audio duration
            
        Returns:
            List of Phrase objects
        """
        if not word_timestamps:
            return []
        
        phrases = []
        current_phrase_words = []
        current_phrase_start = word_timestamps[0].start
        
        for i, word_ts in enumerate(word_timestamps):
            # Add word to current phrase
            current_phrase_words.append(word_ts)
            
            # Check if we should end the current phrase
            should_end_phrase = False
            
            # Rule 1: Maximum words per phrase
            if len(current_phrase_words) >= self.max_words_per_phrase:
                should_end_phrase = True
            
            # Rule 2: Check gap to next word (if exists)
            if i + 1 < len(word_timestamps):
                next_word = word_timestamps[i + 1]
                gap = next_word.start - word_ts.end
                
                # Large gap (>0.5s) is a natural phrase boundary
                if gap > 0.5:
                    should_end_phrase = True
            
            # Rule 3: Check phrase duration
            phrase_duration = word_ts.end - current_phrase_start
            if phrase_duration > self.max_phrase_duration:
                should_end_phrase = True
            
            # Rule 4: Minimum words per phrase (except for last phrase)
            if should_end_phrase and len(current_phrase_words) < self.min_words_per_phrase:
                # Don't end yet, wait for more words
                should_end_phrase = False
            
            # End the phrase if needed
            if should_end_phrase or i == len(word_timestamps) - 1:
                # Create phrase
                phrase_end = word_ts.end
                phrase_text = " ".join(w.word for w in current_phrase_words)
                
                phrase = Phrase(
                    words=current_phrase_words.copy(),
                    start_time=current_phrase_start,
                    end_time=phrase_end,
                    text=phrase_text
                )
                
                phrases.append(phrase)
                
                # Reset for next phrase
                current_phrase_words = []
                if i + 1 < len(word_timestamps):
                    current_phrase_start = word_timestamps[i + 1].start
        
        # Ensure phrases don't overlap and have minimum gaps
        phrases = self._adjust_phrase_timing(phrases, audio_duration)
        
        logger.info(f"Chunked {len(word_timestamps)} words into {len(phrases)} phrases")
        for i, phrase in enumerate(phrases):
            logger.debug(
                f"Phrase {i+1}: {phrase.word_count} words, "
                f"{phrase.start_time:.2f}s - {phrase.end_time:.2f}s, "
                f"'{phrase.text[:50]}...'"
            )
        
        return phrases
    
    def _adjust_phrase_timing(
        self,
        phrases: List[Phrase],
        audio_duration: float
    ) -> List[Phrase]:
        """
        Adjust phrase timing to ensure no overlaps and proper gaps.
        
        IMPORTANT: This method adjusts PHRASE display timing only.
        Word timestamps from ElevenLabs MUST remain unchanged to preserve
        exact synchronization with audio.
        
        Args:
            phrases: List of phrases
            audio_duration: Total audio duration
            
        Returns:
            Adjusted list of phrases
        """
        if not phrases:
            return phrases
        
        adjusted_phrases = []
        
        for i, phrase in enumerate(phrases):
            # Make a copy to modify
            adjusted_phrase = Phrase(
                words=phrase.words.copy(),  # Copy words but DON'T modify their timestamps
                start_time=phrase.start_time,
                end_time=phrase.end_time,
                text=phrase.text
            )
            
            # Ensure phrase doesn't start before 0
            adjusted_phrase.start_time = max(0.0, adjusted_phrase.start_time)
            
            # Ensure phrase doesn't end after audio
            adjusted_phrase.end_time = min(audio_duration, adjusted_phrase.end_time)
            
            # Ensure minimum gap with previous phrase
            if i > 0:
                prev_phrase = adjusted_phrases[-1]
                gap = adjusted_phrase.start_time - prev_phrase.end_time
                
                if gap < self.min_gap_between_phrases:
                    # Move current phrase start to create minimum gap
                    adjusted_phrase.start_time = prev_phrase.end_time + self.min_gap_between_phrases
                    
                    # CRITICAL: DO NOT modify word timestamps
                    # Word timestamps from ElevenLabs must remain exact
                    # The phrase adjustment only affects visual grouping, not audio sync
                    logger.debug(
                        f"Phrase {i+1} adjusted by {adjusted_phrase.start_time - phrase.start_time:.3f}s "
                        f"for minimum gap, word timestamps preserved"
                    )
            
            # Ensure phrase has minimum duration
            phrase_duration = adjusted_phrase.end_time - adjusted_phrase.start_time
            if phrase_duration < 0.3:  # Minimum 300ms
                adjusted_phrase.end_time = adjusted_phrase.start_time + 0.3
                logger.debug(
                    f"Phrase {i+1} extended to minimum 0.3s duration: "
                    f"{phrase_duration:.3f}s -> 0.300s"
                )
            
            adjusted_phrases.append(adjusted_phrase)
        
        # Log adjustment summary
        if len(phrases) > 0 and len(adjusted_phrases) > 0:
            original_total = sum(p.end_time - p.start_time for p in phrases)
            adjusted_total = sum(p.end_time - p.start_time for p in adjusted_phrases)
            logger.info(
                f"Phrase timing adjusted: {len(phrases)} phrases, "
                f"total duration {original_total:.2f}s -> {adjusted_total:.2f}s"
            )
        
        return adjusted_phrases
    
    def _create_pysubs2_styles(self) -> Dict[str, pysubs2.SSAStyle]:
        """
        Create pysubs2 styles for ASS subtitle generation.
        
        Returns:
            Dictionary of style name -> SSAStyle objects
        """
        styles = {}
        
        # Default style (white text)
        default_style = pysubs2.SSAStyle(
            fontname="Arial",
            fontsize=80,
            primarycolor=pysubs2.Color(255, 255, 255),  # White
            secondarycolor=pysubs2.Color(255, 255, 255),  # White
            outlinecolor=pysubs2.Color(0, 0, 0),         # Black
            backcolor=pysubs2.Color(0, 0, 0, 0),         # Transparent
            bold=True,
            italic=False,
            underline=False,
            strikeout=False,
            scalex=100,
            scaley=100,
            spacing=0,
            angle=0,
            borderstyle=1,
            outline=8,
            shadow=0,
            alignment=pysubs2.Alignment.MIDDLE_CENTER,
            marginl=0,
            marginr=0,
            marginv=100,
            encoding=1
        )
        
        styles["Default"] = default_style
        
        # Base style (white text) - kept for backward compatibility
        base_style = pysubs2.SSAStyle(
            fontname="Arial",
            fontsize=80,
            primarycolor=pysubs2.Color(255, 255, 255),  # White
            secondarycolor=pysubs2.Color(255, 255, 255),  # White
            outlinecolor=pysubs2.Color(0, 0, 0),         # Black
            backcolor=pysubs2.Color(0, 0, 0, 0),         # Transparent
            bold=True,
            italic=False,
            underline=False,
            strikeout=False,
            scalex=100,
            scaley=100,
            spacing=0,
            angle=0,
            borderstyle=1,
            outline=8,
            shadow=0,
            alignment=pysubs2.Alignment.MIDDLE_CENTER,
            marginl=0,
            marginr=0,
            marginv=100,
            encoding=1
        )
        
        styles["Base"] = base_style
        
        # Highlight style (yellow text) - kept for backward compatibility
        highlight_style = pysubs2.SSAStyle(
            fontname="Arial",
            fontsize=80,
            primarycolor=pysubs2.Color(255, 255, 0),    # Yellow
            secondarycolor=pysubs2.Color(255, 255, 0),  # Yellow
            outlinecolor=pysubs2.Color(0, 0, 0),        # Black
            backcolor=pysubs2.Color(0, 0, 0, 0),        # Transparent
            bold=True,
            italic=False,
            underline=False,
            strikeout=False,
            scalex=100,
            scaley=100,
            spacing=0,
            angle=0,
            borderstyle=1,
            outline=8,
            shadow=0,
            alignment=pysubs2.Alignment.MIDDLE_CENTER,
            marginl=0,
            marginr=0,
            marginv=100,
            encoding=1
        )
        
        styles["Highlight"] = highlight_style
        
        return styles
    
    def generate_ass_header(self) -> str:
        """
        Generate ASS file header with styles.
        
        Returns:
            ASS header string
        """
        # TikTok/Shorts style: Large, bold, centered text
        # Style 1: Default style (white text) - used for frame-by-frame highlighting
        # Style 2: Base style (white text) - kept for backward compatibility
        # Style 3: Highlight style (yellow text with scale) - kept for backward compatibility
        
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {self.video_width}
PlayResY: {self.video_height}
ScaledBorderAndShadow: yes
WrapStyle: 0
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,8,0,5,0,0,100,1
Style: Base,Arial,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,8,0,5,0,0,100,1
Style: Highlight,Arial,80,&H0000FFFF,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,8,0,5,0,0,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        return header
    
    def format_time(self, seconds: float) -> str:
        """
        Format time in ASS format: H:MM:SS.cc
        
        Args:
            seconds: Time in seconds
            
        Returns:
            Formatted time string
        """
        # Handle negative times (shouldn't happen, but just in case)
        if seconds < 0:
            seconds = 0.0
        
        # Calculate hours, minutes, seconds
        total_seconds = seconds
        hours = int(total_seconds // 3600)
        total_seconds %= 3600
        minutes = int(total_seconds // 60)
        secs = total_seconds % 60
        
        # Round to nearest centisecond (0.01s) using Decimal for precise rounding
        # This avoids banker's rounding issues with values like 0.125
        from decimal import Decimal, ROUND_HALF_UP
        decimal_secs = Decimal(str(secs)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        rounded_secs = float(decimal_secs)
        
        # Handle rollover if rounding pushed seconds to 60.0
        if rounded_secs >= 60.0:
            minutes += 1
            rounded_secs -= 60.0
        
        # Handle rollover if minutes reached 60
        if minutes >= 60:
            hours += 1
            minutes -= 60
        
        # Format with exactly 2 decimal places for centiseconds
        return f"{hours}:{minutes:02d}:{rounded_secs:05.2f}"
    
    def generate_word_highlight_tags(
        self,
        phrase: Phrase,
        current_time: float
    ) -> Tuple[str, str]:
        """
        Generate ASS override tags for word highlighting.
        
        Args:
            phrase: The phrase containing words
            current_time: Current time within the phrase
            
        Returns:
            Tuple of (base_text, highlight_text) with ASS tags
        """
        # Build the full phrase text
        full_text = " ".join(word.word.upper() for word in phrase.words)
        
        # Find which word should be highlighted at current_time
        highlighted_word_idx = -1
        for i, word in enumerate(phrase.words):
            if word.start <= current_time <= word.end:
                highlighted_word_idx = i
                break
        
        if highlighted_word_idx == -1:
            # No word highlighted, show all in white
            return full_text, ""
        
        # Build text with highlighting
        highlighted_word = phrase.words[highlighted_word_idx].word.upper()
        
        # Create highlight tags: yellow color, slight scale
        highlight_tags = "{\\\\c&H00FFFF&\\\\fscx110\\\\fscy110}"
        highlight_text = f"{highlight_tags}{highlighted_word}"
        
        return full_text, highlight_text
    
    def generate_phrase_subtitles(self, phrase: Phrase) -> List[str]:
        """
        Generate ASS dialogue lines for a single phrase using frame-by-frame approach.
        
        Creates a separate dialogue line for EACH word in the phrase with precise timing.
        Each line shows the ENTIRE phrase, but only the active word is highlighted in yellow.
        
        CRITICAL TIMING LOGIC:
        1. For word N (non-last): Start = word.start, End = word[N+1].start
        2. For last word: Start = word.start, End = word.end
        This ensures text stays on screen continuously without flickering.
        
        Args:
            phrase: Phrase to generate subtitles for
            
        Returns:
            List of ASS dialogue lines (one line per word in the phrase)
        """
        dialogue_lines = []
        
        # For each word in the phrase
        for i, current_word in enumerate(phrase.words):
            # Calculate timing using exact ElevenLabs timestamps
            start_time = self.format_time(current_word.start)
            
            # CRITICAL: End time is start of next word for non-last words,
            # or current word's end for the last word in the phrase
            if i + 1 < len(phrase.words):
                next_word = phrase.words[i + 1]
                end_time = self.format_time(next_word.start)
                
                # Log timing details for debugging
                gap = next_word.start - current_word.end
                if gap > 0:
                    logger.debug(
                        f"Word {i+1} ('{current_word.word}'): "
                        f"start={current_word.start:.3f}s, end={current_word.end:.3f}s, "
                        f"next_start={next_word.start:.3f}s, gap={gap:.3f}s"
                    )
                else:
                    # Overlap case (speech overlaps)
                    overlap = current_word.end - next_word.start
                    logger.debug(
                        f"Word {i+1} ('{current_word.word}'): "
                        f"start={current_word.start:.3f}s, end={current_word.end:.3f}s, "
                        f"next_start={next_word.start:.3f}s, OVERLAP={overlap:.3f}s"
                    )
            else:
                # Last word in phrase
                end_time = self.format_time(current_word.end)
                logger.debug(
                    f"Last word {i+1} ('{current_word.word}'): "
                    f"start={current_word.start:.3f}s, end={current_word.end:.3f}s, "
                    f"duration={current_word.end - current_word.start:.3f}s"
                )
            
            # Build the text with optimized color tags
            text_parts = []
            current_color = None
            
            # For each word in the phrase
            for j, word in enumerate(phrase.words):
                word_text = word.word.upper()
                
                # Determine color for this word
                if j == i:
                    # Current word - yellow
                    needed_color = "\\c&H00FFFF&"
                else:
                    # Other words - white
                    needed_color = "\\c&HFFFFFF&"
                
                # Only add color tag if it's different from current color
                if needed_color != current_color:
                    text_parts.append("{" + needed_color + "}")
                    current_color = needed_color
                
                text_parts.append(word_text)
                
                # Add space between words (but not after last word)
                if j < len(phrase.words) - 1:
                    text_parts.append(" ")
            
            # Join all parts
            ass_text = "".join(text_parts)
            
            # Create dialogue line on layer 0 with Default style
            dialogue_line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{ass_text}"
            dialogue_lines.append(dialogue_line)
        
        logger.debug(
            f"Generated {len(dialogue_lines)} dialogue lines for phrase: "
            f"'{phrase.text[:50]}...' ({len(phrase.words)} words)"
        )
        
        return dialogue_lines
    
    def _generate_highlighted_phrase_text(self, phrase: Phrase) -> str:
        """
        Generate ASS text with word-by-word highlighting using frame-by-frame approach.
        This method is kept for backward compatibility but is no longer used by generate_phrase_subtitles.
        
        Args:
            phrase: Phrase to generate text for
            
        Returns:
            ASS text with timing-based highlighting tags
        """
        # This method is deprecated in favor of the frame-by-frame approach
        # but kept for backward compatibility
        return ""
    
    def _generate_phrase_events_with_pysubs2(self, phrase: Phrase) -> List[pysubs2.SSAEvent]:
        """
        Generate pysubs2 events for a single phrase using frame-by-frame approach.
        
        CRITICAL TIMING LOGIC:
        1. For word N (non-last): Start = word.start, End = word[N+1].start
        2. For last word: Start = word.start, End = word.end
        This ensures text stays on screen continuously without flickering.
        
        Each event shows the ENTIRE phrase, but only the active word is highlighted in yellow.
        
        Args:
            phrase: Phrase to generate events for
            
        Returns:
            List of pysubs2.SSAEvent objects (one event per word in the phrase)
        """
        events = []
        
        for i, current_word in enumerate(phrase.words):
            # Convert seconds to milliseconds (pysubs2 uses ms)
            start_ms = int(current_word.start * 1000)
            
            # CRITICAL: End time is start of next word for non-last words,
            # or current word's end for the last word in the phrase
            if i + 1 < len(phrase.words):
                next_word = phrase.words[i + 1]
                end_ms = int(next_word.start * 1000)
            else:
                end_ms = int(current_word.end * 1000)
            
            # Build text with color tags for the entire phrase
            # We need to use double backslashes for ASS override tags in pysubs2
            text_parts = []
            current_color = None
            
            for j, word in enumerate(phrase.words):
                word_text = word.word.upper()
                
                # Determine color for this word
                if j == i:
                    # Current word - yellow
                    needed_color = "\\c&H00FFFF&"
                else:
                    # Other words - white
                    needed_color = "\\c&HFFFFFF&"
                
                # Only add color tag if it's different from current color
                if needed_color != current_color:
                    text_parts.append("{" + needed_color + "}")
                    current_color = needed_color
                
                text_parts.append(word_text)
                
                # Add space between words (but not after last word)
                if j < len(phrase.words) - 1:
                    text_parts.append(" ")
            
            # Join all parts
            ass_text = "".join(text_parts)
            
            # Create pysubs2 event
            event = pysubs2.SSAEvent(
                start=start_ms,
                end=end_ms,
                style="Default",
                text=ass_text
            )
            
            events.append(event)
        
        logger.debug(
            f"Generated {len(events)} pysubs2 events for phrase: "
            f"'{phrase.text[:50]}...' ({len(phrase.words)} words)"
        )
        
        return events
    
    def _create_pysubs2_file(self, phrases: List[Phrase]) -> pysubs2.SSAFile:
        """
        Create a complete pysubs2 SSAFile from phrases.
        
        Args:
            phrases: List of phrases to generate subtitles for
            
        Returns:
            pysubs2.SSAFile object with all events and styles
        """
        subs = pysubs2.SSAFile()
        
        # Add script info
        subs.info.update({
            "PlayResX": str(self.video_width),
            "PlayResY": str(self.video_height),
            "WrapStyle": "0",
            "ScaledBorderAndShadow": "yes",
            "ScriptType": "v4.00+",
            "YCbCr Matrix": "TV.709"
        })
        
        # Add styles
        styles = self._create_pysubs2_styles()
        for style_name, style_obj in styles.items():
            subs.styles[style_name] = style_obj
        
        # Add events for all phrases
        for phrase in phrases:
            events = self._generate_phrase_events_with_pysubs2(phrase)
            for event in events:
                subs.append(event)
        
        logger.info(f"Created pysubs2 file with {len(subs.events)} events for {len(phrases)} phrases")
        
        return subs
    
    def generate_ass_with_pysubs2(
        self,
        word_timestamps: List[WordTimestamp],
        audio_duration: float,
        output_path: Path
    ) -> bool:
        """
        Generate ASS subtitles using pysubs2 library.
        
        Args:
            word_timestamps: List of word timestamps
            audio_duration: Total audio duration
            output_path: Path to save ASS file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Step 1: Chunk words into phrases
            phrases = self.chunk_words_into_phrases(word_timestamps, audio_duration)
            
            if not phrases:
                logger.error("No phrases generated from word timestamps")
                return False
            
            # Step 2: Create pysubs2 file
            subs = self._create_pysubs2_file(phrases)
            
            # Step 3: Save to file
            subs.save(str(output_path))
            
            logger.info(f"ASS subtitles generated with pysubs2: {output_path}")
            logger.info(f"  Phrases: {len(phrases)}")
            logger.info(f"  Words: {len(word_timestamps)}")
            logger.info(f"  Duration: {audio_duration:.2f}s")
            logger.info(f"  Events: {len(subs.events)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to generate ASS subtitles with pysubs2: {e}")
            return False
    
    def generate_ass_from_word_timestamps(
        self,
        word_timestamps: List[WordTimestamp],
        audio_duration: float,
        output_path: Path
    ) -> bool:
        """
        Generate complete ASS subtitle file from word timestamps using pysubs2.
        
        Args:
            word_timestamps: List of word timestamps
            audio_duration: Total audio duration
            output_path: Path to save ASS file
            
        Returns:
            True if successful, False otherwise
        """
        return self.generate_ass_with_pysubs2(word_timestamps, audio_duration, output_path)
    
    def filter_and_adjust_timestamps(
        self,
        word_timestamps: List[WordTimestamp],
        title_word_count: int
    ) -> Tuple[List[WordTimestamp], float]:
        """
        Filter out title words and return story timestamps with original absolute timestamps.
        
        Args:
            word_timestamps: List of word timestamps for combined title+story audio
            title_word_count: Number of words in the title (to filter out)
            
        Returns:
            Tuple of (story_timestamps_with_original_absolute_times, title_duration)
        """
        if title_word_count <= 0 or title_word_count >= len(word_timestamps):
            logger.warning(f"Invalid title_word_count {title_word_count}, total words {len(word_timestamps)}. Returning original timestamps.")
            return word_timestamps, 0.0
        
        # Get title duration (end time of last title word)
        last_title_word = word_timestamps[title_word_count - 1]
        title_duration = last_title_word.end
        
        logger.info(f"Filtering {title_word_count} title words, title duration: {title_duration:.3f}s")
        
        # Extract story-only timestamps (keep original absolute timestamps)
        story_word_timestamps = word_timestamps[title_word_count:]
        
        logger.info(f"Filtered to {len(story_word_timestamps)} story words, first word at {story_word_timestamps[0].start:.3f}s")
        
        return story_word_timestamps, title_duration
    
    def generate_ass_with_title_filter(
        self,
        word_timestamps: List[WordTimestamp],
        title_word_count: int,
        audio_duration: float,
        output_path: Path
    ) -> Tuple[bool, float]:
        """
        Generate ASS subtitles for story only, filtering out title words.
        
        Args:
            word_timestamps: List of word timestamps for combined title+story audio
            title_word_count: Number of words in the title (to filter out)
            audio_duration: Total audio duration (including title)
            output_path: Path to save ASS file
            
        Returns:
            Tuple of (success, title_duration)
        """
        try:
            # Filter title words and adjust timestamps
            story_timestamps, title_duration = self.filter_and_adjust_timestamps(
                word_timestamps, title_word_count
            )
            
            # Calculate story duration for logging
            story_duration = audio_duration - title_duration
            if story_duration <= 0:
                logger.error(f"Invalid story duration: {story_duration:.3f}s (audio: {audio_duration:.3f}s, title: {title_duration:.3f}s)")
                return False, title_duration
            
            # Generate subtitles for story only using full audio duration
            # Story timestamps are absolute (starting at title_duration), so we need the full duration
            success = self.generate_ass_with_pysubs2(
                story_timestamps, audio_duration, output_path
            )
            
            if success:
                logger.info(f"Generated ASS with title filter: {output_path}, title duration: {title_duration:.3f}s, story duration: {story_duration:.3f}s")
            
            return success, title_duration
            
        except Exception as e:
            logger.error(f"Failed to generate ASS with title filter: {e}")
            return False, 0.0
    
    def generate_ass_from_text(
        self,
        text: str,
        audio_duration: float,
        output_path: Path
    ) -> bool:
        """
        Generate ASS subtitles from plain text (without word timestamps).
        TEMPORARILY DISABLED - Will raise exception to crash loudly.
        
        Args:
            text: Plain text
            audio_duration: Audio duration
            output_path: Path to save ASS file
            
        Returns:
            True if successful, False otherwise
        """
        raise RuntimeError(
            "Fallback subtitle generation disabled. ElevenLabs API is returning 401: "
            "'Unusual activity detected. Free Tier usage disabled.' "
            "Need to fix API key or purchase paid plan."
        )


# Utility function for direct use
def generate_subtitles(
    word_timestamps: List[WordTimestamp],
    audio_duration: float,
    output_path: Path,
    **kwargs
) -> bool:
    """
    Convenience function to generate subtitles.
    
    Args:
        word_timestamps: List of word timestamps
        audio_duration: Audio duration
        output_path: Path to save ASS file
        **kwargs: Additional arguments for SubtitleGenerator
        
    Returns:
        True if successful, False otherwise
    """
    generator = SubtitleGenerator(**kwargs)
    return generator.generate_ass_from_word_timestamps(
        word_timestamps, audio_duration, output_path
    )


# Example usage
if __name__ == "__main__":
    # Test with sample data
    test_word_timestamps = [
        WordTimestamp(word="Hello", start=0.0, end=0.3, confidence=0.95),
        WordTimestamp(word="this", start=0.35, end=0.5, confidence=0.92),
        WordTimestamp(word="is", start=0.55, end=0.7, confidence=0.94),
        WordTimestamp(word="a", start=0.75, end=0.8, confidence=0.90),
        WordTimestamp(word="test", start=0.85, end=1.1, confidence=0.96),
        WordTimestamp(word="of", start=1.15, end=1.3, confidence=0.91),
        WordTimestamp(word="the", start=1.35, end=1.5, confidence=0.93),
        WordTimestamp(word="subtitle", start=1.55, end=2.0, confidence=0.95),
        WordTimestamp(word="generator", start=2.05, end=2.5, confidence=0.94),
    ]
    
    test_duration = 3.0
    
    generator = SubtitleGenerator()
    
    # Test phrase chunking
    phrases = generator.chunk_words_into_phrases(test_word_timestamps, test_duration)
    print(f"Chunked {len(test_word_timestamps)} words into {len(phrases)} phrases")
    
    for i, phrase in enumerate(phrases):
        print(f"\nPhrase {i+1}:")
        print(f"  Text: '{phrase.text}'")
        print(f"  Timing: {phrase.start_time:.2f}s - {phrase.end_time:.2f}s")
        print(f"  Words: {phrase.word_count}")
    
    # Test ASS generation
    import tempfile
    temp_dir = tempfile.gettempdir()
    test_output = Path(temp_dir) / "test_subtitles.ass"
    
    success = generator.generate_ass_from_word_timestamps(
        test_word_timestamps, test_duration, test_output
    )
    
    if success:
        print(f"\n✅ ASS file generated successfully: {test_output}")
        
        # Show first few lines
        with open(test_output, 'r') as f:
            lines = f.readlines()[:20]
            print("\nFirst 20 lines of generated ASS file:")
            print("".join(lines))
    else:
        print("\n❌ Failed to generate ASS file")
