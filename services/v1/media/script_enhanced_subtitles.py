import os
import json
import srt
import logging
import difflib
import unicodedata
import datetime
from datetime import timedelta
from typing import List, Dict, Tuple, Optional, Union
from services.cloud_storage import upload_to_cloud_storage
import re
import tempfile

# Import PyThaiNLP for better Thai word segmentation
try:
    from pythainlp.tokenize import word_tokenize
    PYTHAINLP_AVAILABLE = True
except ImportError:
    PYTHAINLP_AVAILABLE = False
    logging.warning("PyThaiNLP not available. Thai word segmentation will be limited.")

# Set up logging
logger = logging.getLogger(__name__)

def align_script_with_subtitles(script_text: str, srt_file_path: str, output_srt_path: Optional[str] = None, upload_to_cloud: bool = True) -> Union[str, Dict[str, str]]:
    """
    Align a voice-over script with automatically generated subtitles to create more accurate subtitles.
    
    Args:
        script_text: The voice-over script text (accurate text)
        srt_file_path: Path to the SRT file generated by transcription
        output_srt_path: Path to save the enhanced SRT file (optional)
        upload_to_cloud: Whether to upload the SRT file to cloud storage (default: True)
        
    Returns:
        If upload_to_cloud is True: Dict with local_path and cloud_url of the enhanced SRT file
        If upload_to_cloud is False: Path to the enhanced SRT file (local path)
    """
    logger.info(f"Aligning script with subtitles from {srt_file_path}")
    
    # Read the SRT file
    try:
        with open(srt_file_path, 'r', encoding='utf-8-sig') as f:
            srt_content = f.read()
            
        # Parse the SRT content
        subtitles = list(srt.parse(srt_content))
        
        if not subtitles:
            logger.warning("No subtitles found in SRT file")
            return srt_file_path
            
        logger.info(f"Found {len(subtitles)} subtitle segments")
    except Exception as e:
        logger.error(f"Error reading SRT file: {str(e)}")
        return srt_file_path
    
    # Process the script text
    # Remove extra whitespace and normalize line breaks
    script_text = script_text.strip()
    
    # Special handling for Thai text - normalize Unicode characters
    script_text = unicodedata.normalize('NFC', script_text)
    
    # Clean up script text - remove excess whitespace and normalize line breaks
    script_text = re.sub(r'\s+', ' ', script_text)
    script_lines = [line.strip() for line in script_text.split('\n') if line.strip()]
    
    # If script is empty, return original SRT
    if not script_lines:
        logger.warning("Script text is empty")
        return srt_file_path
    
    # Join all script lines into a single string for alignment
    full_script = ' '.join(script_lines)
    
    # Extract all transcribed text from subtitles
    transcribed_text = ' '.join([sub.content for sub in subtitles])
    
    # Special handling for Thai text - normalize Unicode characters
    transcribed_text = unicodedata.normalize('NFC', transcribed_text)
    
    logger.info(f"Script length: {len(full_script)} characters")
    logger.info(f"Transcription length: {len(transcribed_text)} characters")
    
    # Determine if we're working with Thai text
    is_thai = any('\u0E00' <= c <= '\u0E7F' for c in full_script)
    if is_thai:
        logger.info("Detected Thai text, using Thai-specific alignment")
        # For Thai, we need to do character-level alignment since Thai doesn't use spaces between words
        aligned_subtitles = align_thai_text(full_script, subtitles)
    else:
        # For non-Thai languages, use the standard word-level alignment
        aligned_subtitles = align_standard_text(full_script, subtitles)
    
    # Write the enhanced SRT file
    if not output_srt_path:
        dir_name = os.path.dirname(srt_file_path)
        base_name = os.path.basename(srt_file_path)
        output_srt_path = os.path.join(dir_name, f"enhanced_{base_name}")
    
    try:
        with open(output_srt_path, 'w', encoding='utf-8') as f:
            f.write(srt.compose(aligned_subtitles))
        logger.info(f"Enhanced SRT file written to {output_srt_path}")
        
        # Upload to cloud storage if requested
        if upload_to_cloud:
            try:
                # Generate a destination path with a unique name
                import uuid
                filename = os.path.basename(output_srt_path)
                destination_path = f"subtitles/{uuid.uuid4()}_{filename}"
                
                # Upload the file to cloud storage
                cloud_url = upload_to_cloud_storage(output_srt_path, destination_path)
                logger.info(f"Enhanced SRT file uploaded to cloud storage: {cloud_url}")
                
                # Return both the local path and cloud URL
                return {
                    "local_path": output_srt_path,
                    "cloud_url": cloud_url
                }
            except Exception as e:
                logger.error(f"Error uploading SRT file to cloud storage: {str(e)}")
                # If cloud upload fails, return the local path
                return output_srt_path
        
        # If cloud upload is not requested, return the local path
        return output_srt_path
        
    except Exception as e:
        logger.error(f"Error writing enhanced SRT file: {str(e)}")
        return srt_file_path

def segment_thai_text(text: str) -> List[str]:
    """
    Segment Thai text into words using PyThaiNLP if available.
    Falls back to character-by-character segmentation if PyThaiNLP is not available.
    
    Args:
        text: Thai text to segment
        
    Returns:
        List of Thai words
    """
    if PYTHAINLP_AVAILABLE:
        try:
            # Use PyThaiNLP's neural network model for better segmentation
            words = word_tokenize(text, engine="newmm")
            return words
        except Exception as e:
            logger.warning(f"Error using PyThaiNLP for word segmentation: {str(e)}")
    
    # Fallback to simple character segmentation (not ideal but better than nothing)
    return list(text)

def align_thai_text(script_text: str, subtitles: List[srt.Subtitle]) -> List[srt.Subtitle]:
    """
    Align Thai script text with subtitles using improved Thai-specific alignment.
    
    Args:
        script_text: The Thai script text
        subtitles: List of subtitle objects
        
    Returns:
        List of aligned subtitle objects
    """
    # Create a list to store the aligned subtitles
    aligned_subtitles = []
    
    # Current position in the script text
    script_pos = 0
    
    # Pre-segment the script text for better alignment
    segmented_script = segment_thai_text(script_text)
    script_with_markers = " ".join(segmented_script)
    
    # Process each subtitle
    for i, sub in enumerate(subtitles):
        # Skip empty subtitles
        if not sub.content.strip():
            aligned_subtitles.append(sub)
            continue
        
        # Normalize and clean the subtitle content
        sub_content = unicodedata.normalize('NFC', sub.content.strip())
        
        # Segment the subtitle content
        segmented_sub = segment_thai_text(sub_content)
        
        # Find the best match for this subtitle in the script
        best_match = ""
        best_score = 0
        best_pos = script_pos
        
        # Try different window sizes around the current position
        # Use a larger window for better context
        window_size = max(len(sub_content) * 10, 200)  # Increased window size
        start_pos = max(0, script_pos - window_size)
        end_pos = min(len(script_text), script_pos + len(sub_content) + window_size)
        
        search_text = script_text[start_pos:end_pos]
        
        # Use a combination of approaches for better matching
        
        # 1. First try exact matching for short segments
        if len(sub_content) < 20:
            exact_match_pos = search_text.find(sub_content)
            if exact_match_pos >= 0:
                best_match = sub_content
                best_score = 1.0
                best_pos = start_pos + exact_match_pos
        
        # 2. If no exact match, use difflib with higher threshold
        if not best_match:
            # Use difflib to find the best match with improved algorithm
            matcher = difflib.SequenceMatcher(None, sub_content, search_text)
            match = matcher.find_longest_match(0, len(sub_content), 0, len(search_text))
            
            if match.size > 0:
                match_score = match.size / len(sub_content)
                if match_score > 0.5:  # Increased threshold from default
                    best_match = search_text[match.b:match.b + match.size]
                    best_score = match_score
                    best_pos = start_pos + match.b
        
        # 3. If still no good match, try word-level matching
        if not best_match or best_score < 0.7:
            # Try matching individual words
            best_word_matches = []
            for word in segmented_sub:
                if word in search_text:
                    word_pos = search_text.find(word)
                    best_word_matches.append((word, start_pos + word_pos))
            
            if best_word_matches:
                # Use the script text between the first and last matched word
                if len(best_word_matches) > 1:
                    first_match = min(best_word_matches, key=lambda x: x[1])
                    last_match = max(best_word_matches, key=lambda x: x[1])
                    first_pos = first_match[1]
                    last_pos = last_match[1] + len(last_match[0])
                    
                    if last_pos - first_pos < len(sub_content) * 2:  # Reasonable length check
                        best_match = script_text[first_pos:last_pos]
                        best_score = 0.8  # Consider this a good match
                        best_pos = first_pos
        
        # If we found a good match, use it
        if best_match and best_score >= 0.5:
            # Create a new subtitle with the matched script text but keep the timing
            new_sub = srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=best_match
            )
            aligned_subtitles.append(new_sub)
            
            # Update the position for the next search
            script_pos = best_pos + len(best_match)
        else:
            # If no good match found, keep the original subtitle
            # But try to clean it up a bit
            cleaned_content = sub_content
            # Remove common hallucination patterns
            cleaned_content = re.sub(r'minecraft', '', cleaned_content)
            cleaned_content = re.sub(r'and\s*$', '', cleaned_content)
            
            new_sub = srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=cleaned_content
            )
            aligned_subtitles.append(new_sub)
    
    return aligned_subtitles

def align_standard_text(script_text: str, subtitles: List[srt.Subtitle]) -> List[srt.Subtitle]:
    """
    Align standard (non-Thai) script text with subtitles using word-level alignment.
    
    Args:
        script_text: The script text
        subtitles: List of subtitle objects
        
    Returns:
        List of aligned subtitle objects
    """
    # Create a list to store the aligned subtitles
    aligned_subtitles = []
    
    # Split the script into words
    script_words = script_text.split()
    
    # Current position in the script words
    script_pos = 0
    
    # Process each subtitle
    for sub in subtitles:
        # Skip empty subtitles
        if not sub.content.strip():
            aligned_subtitles.append(sub)
            continue
        
        # Split the subtitle content into words
        sub_words = sub.content.split()
        
        # Find the best match for this subtitle in the script
        best_match = ""
        best_score = 0
        best_pos = script_pos
        
        # Try different positions in the script
        for pos in range(max(0, script_pos - 10), min(len(script_words), script_pos + len(sub_words) + 10)):
            # Don't go past the end of the script
            if pos + len(sub_words) > len(script_words):
                break
                
            # Get the potential match
            potential_match = ' '.join(script_words[pos:pos + len(sub_words)])
            
            # Calculate the similarity score
            matcher = difflib.SequenceMatcher(None, sub.content.lower(), potential_match.lower())
            score = matcher.ratio()
            
            # Update the best match if this is better
            if score > best_score:
                best_match = potential_match
                best_score = score
                best_pos = pos
        
        # If we found a good match, use it
        if best_score > 0.6:
            new_sub = srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=best_match
            )
            aligned_subtitles.append(new_sub)
            script_pos = best_pos + len(sub_words)
        else:
            # If no good match, keep the original subtitle
            aligned_subtitles.append(sub)
            # Don't advance script_pos in this case
    
    return aligned_subtitles

def enhance_subtitles_from_segments(segments, script_text, language="en", settings=None):
    """
    Enhance subtitles from transcription segments and script text.
    
    Args:
        segments: List of transcription segments with start, end, and text
        script_text: Script text to align with segments
        language: Language code
        settings: Additional settings
        
    Returns:
        Tuple of (srt_path, ass_path)
    """
    try:
        logger = logging.getLogger(__name__)
        logger.info("Starting subtitle enhancement process")
        
        # Create a temporary directory for outputs
        temp_dir = tempfile.mkdtemp()
        logger.info(f"Created temporary directory: {temp_dir}")
        
        # Get settings
        settings_obj = settings if settings else {}
        
        # Set default font based on language
        if "font_name" not in settings_obj:
            if language.lower() == "th":
                settings_obj["font_name"] = "Sarabun"  # Default to Sarabun for Thai
            else:
                settings_obj["font_name"] = "Arial"  # Default to Arial for other languages
        
        font_name = settings_obj.get("font_name", "Arial")
        font_size = settings_obj.get("font_size", 24)
        max_width = settings_obj.get("max_width", 40)
        
        # For Thai language, ensure we're using Sarabun font
        if language.lower() == "th" and font_name.lower() != "sarabun":
            logger.info(f"Thai language detected, switching font from {font_name} to Sarabun for better Thai support")
            font_name = "Sarabun"
        
        logger.info(f"Using font: {font_name}, size: {font_size}, max width: {max_width}")
        
        # Generate SRT from segments
        srt_path = os.path.join(temp_dir, "subtitles.srt")
        logger.info(f"Generating SRT file at: {srt_path}")
        
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments, 1):
                start_time = segment.get("start", 0)
                end_time = segment.get("end", 0)
                text = segment.get("text", "").strip()
                
                # Format times as SRT format (HH:MM:SS,mmm)
                start_formatted = format_time_srt(start_time)
                end_formatted = format_time_srt(end_time)
                
                # Write SRT entry
                f.write(f"{i}\n")
                f.write(f"{start_formatted} --> {end_formatted}\n")
                f.write(f"{text}\n\n")
        
        logger.info(f"Generated SRT file with {len(segments)} segments")
        
        # Convert SRT to ASS with enhanced formatting
        ass_path = os.path.join(temp_dir, "subtitles.ass")
        logger.info(f"Converting SRT to ASS at: {ass_path}")
        
        # Get additional styling parameters
        bold = settings_obj.get("bold", True)  # Default to bold for better readability
        italic = settings_obj.get("italic", False)
        underline = settings_obj.get("underline", False)
        strikeout = settings_obj.get("strikeout", False)
        outline = settings_obj.get("outline", True)  # Default to outline for better contrast
        shadow = settings_obj.get("shadow", True)  # Default to shadow for better readability
        alignment = settings_obj.get("alignment", "center")  # Default to center alignment
        line_color = settings_obj.get("line_color", "white")  # Default to white text
        outline_color = settings_obj.get("outline_color", "black")  # Default to black outline
        margin_v = settings_obj.get("margin_v", 30)  # Default to 30px vertical margin
        
        # For Thai language, ensure we have proper styling
        if language.lower() == "th":
            # Increase font size slightly for better Thai readability if not already set
            if "font_size" not in settings_obj:
                font_size = 28
            
            # Ensure bold is enabled for Thai text
            bold = True
            
            # Ensure outline and shadow for better readability against any background
            outline = True
            shadow = True
        
        # Create font formatting string
        font_formatting = {
            "bold": bold,
            "italic": italic,
            "underline": underline,
            "strikeout": strikeout,
            "outline": outline,
            "shadow": shadow
        }
        
        # Convert alignment string to ASS alignment number
        if isinstance(alignment, str):
            if alignment.lower() == "left":
                alignment = 1
            elif alignment.lower() == "right":
                alignment = 3
            else:  # center or any other value
                alignment = 2
        
        # Convert SRT to ASS with Thai-specific handling
        if language.lower() == "th":
            from services.v1.video.caption_video import convert_srt_to_ass_for_thai
            
            # Create the ASS file path
            ass_path = os.path.join(temp_dir, "subtitles.ass")
            
            # First convert SRT to ASS with Thai-specific handling
            convert_srt_to_ass_for_thai(
                srt_path=srt_path,
                font_name=font_name,
                font_size=font_size,
                primary_color=line_color,
                outline_color=outline_color,
                alignment=alignment,
                margin_v=margin_v,
                max_words_per_line=settings_obj.get("max_words_per_line", 7),
                max_width=max_width
            )
            
            # Write the ASS file
            with open(srt_path, 'r', encoding='utf-8') as f_srt:
                srt_content = f_srt.read()
                
            # Check if the ASS file was created, if not create it
            if not os.path.exists(ass_path):
                logger.info(f"Creating ASS file at: {ass_path}")
                
                # Convert SRT content to ASS format
                ass_content = """[Script Info]
Title: Auto-generated Thai subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H{line_color},&H{line_color},&H{outline_color},&H80000000,1,0,0,0,100,100,0,0,1,2,2,{alignment},20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
                
                # Parse SRT content
                import re
                pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|\Z)'
                matches = re.findall(pattern, srt_content, re.MULTILINE)
                
                # Convert SRT time format to ASS time format
                def convert_time_to_ass(time_str):
                    # Convert from 00:00:00,000 to 0:00:00.00
                    h, m, s = time_str.split(':')
                    s, ms = s.split(',')
                    return f"{int(h)}:{m}:{s}.{ms[:2]}"
                
                # Add dialogue lines
                for match in matches:
                    _, start_time, end_time, text = match
                    start_time_ass = convert_time_to_ass(start_time)
                    end_time_ass = convert_time_to_ass(end_time)
                    
                    # Process Thai text with proper line breaks
                    if PYTHAINLP_AVAILABLE:
                        from pythainlp.tokenize import word_tokenize
                        words = word_tokenize(text, engine="newmm")
                        
                        # Apply line breaks
                        lines = []
                        current_line = ""
                        for word in words:
                            if len(current_line) + len(word) > max_width:
                                lines.append(current_line)
                                current_line = word
                            else:
                                current_line += word
                        
                        if current_line:
                            lines.append(current_line)
                        
                        text = "\\N".join(lines)
                    
                    # Add the dialogue line
                    ass_content += f"Dialogue: 0,{start_time_ass},{end_time_ass},Default,,0,0,0,,{text}\n"
                
                # Write the ASS file
                with open(ass_path, 'w', encoding='utf-8') as f_ass:
                    f_ass.write(ass_content)
        else:
            # Standard conversion for non-Thai languages
            from services.v1.video.caption_video import convert_srt_to_ass
            convert_srt_to_ass(
                srt_path=srt_path,
                ass_path=ass_path,
                font_name=font_name,
                font_size=font_size,
                line_color=line_color,
                outline_color=outline_color,
                word_color=settings_obj.get("word_color", "#FFFF00"),
                alignment=alignment,
                margin_v=margin_v,
                subtitle_style=settings_obj.get("subtitle_style", "classic"),
                max_width=max_width,
                all_caps=settings_obj.get("all_caps", False),
                font_formatting=font_formatting
            )
        
        logger.info(f"Generated ASS file with enhanced formatting")
        
        return srt_path, ass_path
        
    except Exception as e:
        logger.error(f"Error in subtitle enhancement: {str(e)}")
        raise

def format_time_srt(time_in_seconds):
    hours = int(time_in_seconds // 3600)
    minutes = int((time_in_seconds % 3600) // 60)
    seconds = int(time_in_seconds % 60)
    milliseconds = int((time_in_seconds - int(time_in_seconds)) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def convert_srt_time_to_ass(time_str):
    parts = time_str.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds_and_milliseconds = parts[2].split(",")
    seconds = int(seconds_and_milliseconds[0])
    milliseconds = int(seconds_and_milliseconds[1])
    
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    
    return f"{total_seconds:.3f}"
