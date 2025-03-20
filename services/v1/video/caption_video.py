import os
import time
import json
import tempfile
import subprocess
import logging
from typing import Dict, Any, List, Optional, Union

# Configure logging
logger = logging.getLogger(__name__)

# Import PyThaiNLP for Thai word segmentation
try:
    from pythainlp.tokenize import word_tokenize
    PYTHAINLP_AVAILABLE = True
except ImportError:
    PYTHAINLP_AVAILABLE = False
    logger.warning("PyThaiNLP not available. Using fallback method for Thai word segmentation.")

def add_subtitles_to_video(video_path, subtitle_path, output_path=None, job_id=None, 
                          font_name="Arial", font_size=24, margin_v=40, subtitle_style="classic",
                          max_width=None, position="bottom", max_words_per_line=None,
                          line_color=None, word_color=None, outline_color=None,
                          all_caps=False, x=None, y=None,
                          alignment="center", bold=False, italic=False, underline=False,
                          strikeout=False):
    try:
        # Start timing the processing
        start_time = time.time()
        
        # Log the input parameters for debugging
        logger.info(f"Job {job_id}: Adding subtitles to video with parameters:")
        logger.info(f"Job {job_id}: video_path: {video_path}")
        logger.info(f"Job {job_id}: subtitle_path: {subtitle_path}")
        logger.info(f"Job {job_id}: font_name: {font_name}")
        logger.info(f"Job {job_id}: font_size: {font_size}")
        logger.info(f"Job {job_id}: subtitle_style: {subtitle_style}")
        
        # Check if output path is provided
        if not output_path:
            output_path = os.path.join(os.path.dirname(video_path), f"{job_id}_captioned.mp4")
        
        # Check if the subtitle file exists
        if not os.path.exists(subtitle_path):
            logger.error(f"Job {job_id}: Subtitle file not found: {subtitle_path}")
            return None
        
        # Check if the video file exists
        if not os.path.exists(video_path):
            logger.error(f"Job {job_id}: Video file not found: {video_path}")
            return None
            
        # Check if text contains Thai characters
        def contains_thai(s):
            with open(subtitle_path, 'r', encoding='utf-8') as f:
                content = f.read()
                thai_range = range(0x0E00, 0x0E7F)
                return any(ord(c) in thai_range for c in content)
        
        is_thai = contains_thai(subtitle_path)
        logger.info(f"Job {job_id}: Contains Thai text: {is_thai}")
        
        # Apply predefined styles
        if subtitle_style:
            if subtitle_style == "classic":
                # Classic style: white text with black outline
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not bold:
                    bold = True
                if not max_words_per_line and is_thai:
                    max_words_per_line = 4
                if not max_width:
                    max_width = 80
                if is_thai and not font_name:
                    font_name = "Sarabun"  # Best overall Thai font
                
            elif subtitle_style == "modern":
                # Modern style: white text with semi-transparent background
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 28
                if not max_words_per_line and is_thai:
                    max_words_per_line = 3
                if not max_width:
                    max_width = 70
                if is_thai and not font_name:
                    font_name = "Sarabun"  # Best overall Thai font
                
            elif subtitle_style == "cinematic":
                # Cinematic style: larger text, bottom position, wider
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 32
                if not position:
                    position = "bottom"
                if not margin_v:
                    margin_v = 60
                if not max_words_per_line and is_thai:
                    max_words_per_line = 3
                if not max_width:
                    max_width = 90
                if not bold:
                    bold = True
                if is_thai and not font_name:
                    font_name = "Sarabun"  # Best overall Thai font
                    
            elif subtitle_style == "minimal":
                # Minimal style: smaller text, no background
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 22
                if not max_words_per_line and is_thai:
                    max_words_per_line = 5
                if not max_width:
                    max_width = 60
                if is_thai and not font_name:
                    font_name = "Garuda"  # Better for smaller text in Thai
                    
            elif subtitle_style == "bold":
                # Bold style: large text with strong outline
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 30
                if not bold:
                    bold = True
                if not max_words_per_line and is_thai:
                    max_words_per_line = 3
                if not max_width:
                    max_width = 75
                if is_thai and not font_name:
                    font_name = "Sarabun"  # Best overall Thai font
                    
            elif subtitle_style == "premium":
                # Premium style: optimized specifically for Thai text
                if not line_color:
                    line_color = "FFFFFF"  # White
                if not outline_color:
                    outline_color = "000000"  # Black
                if not font_size:
                    font_size = 28
                if not position:
                    position = "bottom"
                if not margin_v:
                    margin_v = 70
                if not max_words_per_line and is_thai:
                    max_words_per_line = 3
                if not max_width:
                    max_width = 75
                if not bold:
                    bold = True
                # Use Waree font which has better tone mark alignment for Thai
                if is_thai:
                    font_name = "Waree"
                
        # Process text for all_caps if needed
        subtitle_filters = []
        if all_caps:
            subtitle_filters.append("text=toupper")
        
        # Process max_words_per_line if needed
        if max_words_per_line and max_words_per_line > 0:
            logger.info(f"Job {job_id}: Reformatting SRT with max {max_words_per_line} words per line")
            temp_dir = os.path.dirname(subtitle_path)
            if not temp_dir:
                temp_dir = os.path.dirname(output_path) if output_path else '/tmp'
            
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            
            original_srt = subtitle_path
            limited_srt = os.path.join(temp_dir, f"limited_{job_id}.srt")
            
            with open(original_srt, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse and reformat SRT
            srt_data = []
            current_block = {"index": "", "time": "", "text": []}
            for line in content.split('\n'):
                line = line.strip()
                if not line:
                    if current_block["text"]:
                        srt_data.append(current_block)
                        current_block = {"index": "", "time": "", "text": []}
                    continue
                
                if not current_block["index"]:
                    current_block["index"] = line
                elif not current_block["time"] and '-->' in line:
                    current_block["time"] = line
                else:
                    current_block["text"].append(line)
            
            # Add the last block if it exists
            if current_block["text"]:
                srt_data.append(current_block)
            
            # Helper functions for time conversion
            def convert_time_to_seconds(time_str):
                """Convert SRT time format (HH:MM:SS,mmm) to seconds."""
                parts = time_str.replace(',', '.').split(':')
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds
            
            def convert_seconds_to_time(seconds):
                """Convert seconds to SRT time format (HH:MM:SS,mmm)."""
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                seconds = seconds % 60
                return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}".replace('.', ',')
            
            # Improved split_lines function for Thai text
            def split_lines(text, max_words_per_line):
                """Split text into lines with a maximum number of words per line."""
                if not max_words_per_line or max_words_per_line <= 0:
                    return [text]
                    
                # Check if text contains Thai characters
                def contains_thai(s):
                    thai_range = range(0x0E00, 0x0E7F)
                    return any(ord(c) in thai_range for c in s)
                
                if contains_thai(text):
                    # For Thai text, use PyThaiNLP if available
                    if PYTHAINLP_AVAILABLE:
                        try:
                            # Use PyThaiNLP with newmm engine (fastest and most accurate)
                            # Set timeout to prevent hanging on very long text
                            words = word_tokenize(text, engine="newmm", keep_whitespace=False)
                            
                            # If the text is short enough, return it as is
                            if len(words) <= max_words_per_line:
                                return [text]
                            
                            # Split into chunks of max_words_per_line
                            result = []
                            for i in range(0, len(words), max_words_per_line):
                                chunk = words[i:i+max_words_per_line]
                                # Join without spaces for Thai words
                                line = ""
                                for word in chunk:
                                    # Add space only for non-Thai characters
                                    if any(ord(c) < 0x0E00 or ord(c) > 0x0E7F for c in word):
                                        line += " " + word
                                    else:
                                        line += word
                                result.append(line.strip())
                            return result
                        except Exception as e:
                            logger.warning(f"PyThaiNLP tokenization failed: {str(e)}. Using fallback method.")
                            # Fall back to the rule-based method if PyThaiNLP fails
                    
                    # Fallback: Rule-based Thai word segmentation
                    # Thai punctuation and break characters
                    break_chars = [' ', '\n', ',', '.', '?', '!', ':', ';', ')', ']', '}', '"', "'", '।', '॥', '…', '–', '—', '|']
                    
                    # Common Thai word-ending characters that can be used as potential break points
                    thai_word_endings = ['ะ', 'า', 'ิ', 'ี', 'ึ', 'ื', 'ุ', 'ู', 'เ', 'แ', 'โ', 'ใ', 'ไ', '่', '้', '๊', '๋', '็', '์', 'ๆ']
                    
                    # If the text is short enough, return it as is
                    if len(text) <= max_words_per_line * 5:  # Estimate 5 chars per Thai word
                        return [text]
                        
                    # Try to split at natural break points
                    result = []
                    current_line = ""
                    char_count = 0
                    last_potential_break = 0
                    
                    for i, char in enumerate(text):
                        current_line += char
                        char_count += 1
                        
                        # Mark potential break points at word boundaries
                        if char in break_chars or char in thai_word_endings:
                            last_potential_break = i
                        
                        # If we've reached the target length, break at the last potential break point
                        if char_count >= max_words_per_line * 4:  # Slightly less than our estimate to be safe
                            if last_potential_break > 0 and last_potential_break > i - 10:
                                # Break at the last potential break point
                                result.append(current_line[:last_potential_break - i + len(current_line)])
                                current_line = current_line[last_potential_break - i + len(current_line):]
                                char_count = len(current_line)
                                last_potential_break = 0
                            else:
                                # If no good break point, just break here
                                result.append(current_line)
                                current_line = ""
                                char_count = 0
                                last_potential_break = 0
                    
                    # Add any remaining text
                    if current_line:
                        result.append(current_line)
                    
                    return result
                else:
                    # For non-Thai text, split by words
                    words = text.split()
                    if len(words) <= max_words_per_line:
                        return [text]
                    
                    # Split into chunks of max_words_per_line
                    return [' '.join(words[i:i+max_words_per_line]) for i in range(0, len(words), max_words_per_line)]
            
            # Reformat with max words per line and fix synchronization
            with open(limited_srt, 'w', encoding='utf-8') as f:
                for block in srt_data:
                    # Join all text lines
                    text = ' '.join(block["text"])
                    
                    # Use our improved split_lines function
                    new_lines = split_lines(text, max_words_per_line)
                    
                    # Limit to maximum 2 lines per subtitle for better readability
                    max_lines = 2
                    if len(new_lines) > max_lines:
                        # Create multiple subtitle blocks if we have more than max_lines
                        time_parts = block["time"].split('-->')
                        start_time = time_parts[0].strip()
                        end_time = time_parts[1].strip()
                        
                        # Calculate time per subtitle block
                        start_seconds = convert_time_to_seconds(start_time)
                        end_seconds = convert_time_to_seconds(end_time)
                        total_duration = end_seconds - start_seconds
                        
                        # Improve synchronization by adding a small offset
                        if is_thai:
                            # Add a small offset (0.3 seconds) to improve sync with Thai audio
                            start_seconds = max(0, start_seconds - 0.3)
                            # Extend duration slightly for better readability
                            end_seconds = end_seconds + 0.2
                            total_duration = end_seconds - start_seconds
                        
                        duration_per_block = total_duration / ((len(new_lines) + max_lines - 1) // max_lines)
                        
                        # Write multiple blocks
                        for i in range(0, len(new_lines), max_lines):
                            block_lines = new_lines[i:i+max_lines]
                            block_start = start_seconds + (i // max_lines) * duration_per_block
                            block_end = min(end_seconds, block_start + duration_per_block)
                            
                            # Ensure minimum display time (1.5 seconds) for Thai text
                            if is_thai and (block_end - block_start) < 1.5:
                                block_end = min(end_seconds, block_start + 1.5)
                            
                            f.write(f"{block['index']}.{i//max_lines+1}\n")
                            f.write(f"{convert_seconds_to_time(block_start)} --> {convert_seconds_to_time(block_end)}\n")
                            f.write('\n'.join(block_lines) + '\n\n')
                    else:
                        # Write the reformatted block
                        # Improve synchronization for Thai text
                        if is_thai:
                            time_parts = block["time"].split('-->')
                            start_time = time_parts[0].strip()
                            end_time = time_parts[1].strip()
                            
                            # Calculate time in seconds
                            start_seconds = convert_time_to_seconds(start_time)
                            end_seconds = convert_time_to_seconds(end_time)
                            
                            # Add a small offset (0.3 seconds) to improve sync with Thai audio
                            start_seconds = max(0, start_seconds - 0.3)
                            # Extend duration slightly for better readability
                            end_seconds = end_seconds + 0.2
                            
                            # Ensure minimum display time (1.5 seconds) for Thai text
                            if (end_seconds - start_seconds) < 1.5:
                                end_seconds = start_seconds + 1.5
                            
                            # Write with adjusted timing
                            f.write(f"{block['index']}\n")
                            f.write(f"{convert_seconds_to_time(start_seconds)} --> {convert_seconds_to_time(end_seconds)}\n")
                            f.write('\n'.join(new_lines) + '\n\n')
                        else:
                            # Non-Thai text - use original timing
                            f.write(block["index"] + '\n')
                            f.write(block["time"] + '\n')
                            f.write('\n'.join(new_lines) + '\n\n')
            
            subtitle_path = limited_srt
        
        # Determine subtitle position and alignment
        subtitle_position = position
        if x is not None and y is not None:
            # Custom position overrides predefined positions
            subtitle_position = "custom"
        
        # Base subtitle filter
        subtitle_filter = f"subtitles='{subtitle_path}'"
        
        # Add font settings
        subtitle_filter += f":force_style='FontName={font_name},FontSize={font_size}"
        
        # Add text formatting
        if bold:
            subtitle_filter += ",Bold=1"
        if italic:
            subtitle_filter += ",Italic=1"
        if underline:
            subtitle_filter += ",Underline=1"
        if strikeout:
            subtitle_filter += ",StrikeOut=1"
        
        # Add alignment
        alignment_value = "2"  # Default center
        if alignment == "left":
            alignment_value = "1"
        elif alignment == "right":
            alignment_value = "3"
        subtitle_filter += f",Alignment={alignment_value}"
        
        # Add colors if specified
        if line_color:
            # Remove # if present and ensure it's a valid hex color
            line_color = line_color.lstrip('#')
            if len(line_color) == 6:
                subtitle_filter += f",PrimaryColour=&H{line_color}&"
        else:
            # Default to white text for better visibility
            subtitle_filter += f",PrimaryColour=&HFFFFFF&"
        
        if outline_color:
            outline_color = outline_color.lstrip('#')
            if len(outline_color) == 6:
                subtitle_filter += f",OutlineColour=&H{outline_color}&"
        else:
            # Default to black outline for better visibility
            subtitle_filter += f",OutlineColour=&H000000&"
            
        # Add shadow and border style based on subtitle style
        if subtitle_style == "modern":
            subtitle_filter += ",Shadow=0,BorderStyle=4,Outline=0"  # Box style
            subtitle_filter += ",BackColour=&H80000000&"  # Semi-transparent black background
        elif subtitle_style == "cinematic":
            subtitle_filter += ",Shadow=1,BorderStyle=1,Outline=2"  # Thicker outline
        elif subtitle_style == "minimal":
            subtitle_filter += ",Shadow=0,BorderStyle=1,Outline=1"  # Minimal outline
        elif subtitle_style == "bold":
            subtitle_filter += ",Shadow=1,BorderStyle=1,Outline=3"  # Very thick outline
        elif subtitle_style == "premium":
            # Premium style optimized for Thai text
            subtitle_filter += ",Shadow=0,BorderStyle=1,Outline=1.5"  # Medium outline
            subtitle_filter += ",BackColour=&HC0000000&"  # More opaque background for better readability
            # Add special spacing for Thai text to fix tone marks
            subtitle_filter += ",Spacing=0.5"  # Increased spacing to prevent tone mark overlays
        else:  # classic and default
            subtitle_filter += ",Shadow=1,BorderStyle=1,Outline=1"  # Standard outline
            
        # Add background box for Thai text if needed
        if is_thai and subtitle_style not in ["minimal"]:
            if subtitle_style != "premium":  # Premium already has its own background
                subtitle_filter += ",BackColour=&H80000000&"  # Semi-transparent black background
            
            # Add special handling for Thai text if not already in premium style
            if subtitle_style != "premium":
                subtitle_filter += ",Spacing=0.3"  # Increased spacing to prevent tone mark overlays
            
        # Add word color if specified and in karaoke or highlight style
        if word_color and subtitle_style in ["karaoke", "highlight"]:
            word_color = word_color.lstrip('#')
            if len(word_color) == 6:
                subtitle_filter += f",SecondaryColour=&H{word_color}&"
        
        # Add margin based on position - ensure subtitles stay within video frame
        # Default margin is increased to ensure text is fully visible
        default_margin_v = max(margin_v, 60 if is_thai else 40)  # Ensure minimum margin of 60 pixels for Thai text
        
        if subtitle_position == "bottom":
            subtitle_filter += f",MarginV={default_margin_v}"
        elif subtitle_position == "top":
            subtitle_filter += f",MarginV={default_margin_v}"
        elif subtitle_position == "middle":
            subtitle_filter += f",MarginV=0"
        elif subtitle_position == "custom" and x is not None and y is not None:
            subtitle_filter += f",MarginL={x},MarginR=0,MarginV={y}"
        
        # Add max width if specified
        if max_width:
            # Convert percentage to ASS script units
            subtitle_filter += f",PlayResX=384,PlayResY=288,MarginL={int(384*(100-max_width)/200)},MarginR={int(384*(100-max_width)/200)}"
        
        # Close the force_style parameter
        subtitle_filter += "'"
        
        # Add the subtitle filter to the list
        subtitle_filters = [subtitle_filter]
        
        # Combine all filters
        filter_complex = ','.join(subtitle_filters)
        
        # Build the FFmpeg command
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-filter_complex", filter_complex,
            "-c:v", "libx264", "-crf", "18",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            output_path
        ]
        
        # Log the command
        logger.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
        
        # Execute the command
        subprocess.run(ffmpeg_cmd, check=True)
        
        # Upload to cloud storage
        file_url = None
        from services.cloud_storage import upload_file
        file_url = upload_file(output_path)
        logger.info(f"Uploaded output file to cloud storage: {file_url}")
        
        # Extract metadata using ffprobe
        video_info = {}
        try:
            # Run ffprobe to get video metadata
            ffprobe_cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                output_path
            ]
            
            ffprobe_output = subprocess.check_output(ffprobe_cmd, stderr=subprocess.STDOUT)
            video_info_raw = json.loads(ffprobe_output.decode('utf-8'))
            
            # Process the metadata to ensure it's all serializable
            video_info = {
                "format": {},
                "streams": []
            }
            
            # Process format information
            if "format" in video_info_raw and isinstance(video_info_raw["format"], dict):
                for key, value in video_info_raw["format"].items():
                    # Convert all values to basic Python types
                    if isinstance(value, (int, float, str, bool, type(None))):
                        video_info["format"][key] = value
                    else:
                        video_info["format"][key] = str(value)
            
            # Process stream information
            if "streams" in video_info_raw and isinstance(video_info_raw["streams"], list):
                for stream in video_info_raw["streams"]:
                    if isinstance(stream, dict):
                        stream_info = {}
                        for key, value in stream.items():
                            # Convert all values to basic Python types
                            if isinstance(value, (int, float, str, bool, type(None))):
                                stream_info[key] = value
                            else:
                                stream_info[key] = str(value)
                        video_info["streams"].append(stream_info)
            
            # Generate thumbnail
            thumbnail_path = os.path.join(tempfile.gettempdir(), f"thumbnail_{job_id}.jpg")
            thumbnail_cmd = [
                "ffmpeg",
                "-i", output_path,
                "-ss", "00:00:05",  # Take screenshot at 5 seconds
                "-vframes", "1",
                "-vf", "scale=320:-1",  # Scale to width 320px, maintain aspect ratio
                "-y",
                thumbnail_path
            ]
            
            subprocess.run(thumbnail_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Upload thumbnail
            from services.cloud_storage import upload_to_cloud_storage
            thumbnail_url = upload_to_cloud_storage(thumbnail_path, f"thumbnails/{os.path.basename(thumbnail_path)}")
            video_info["thumbnail_url"] = str(thumbnail_url)
            
        except Exception as e:
            logger.warning(f"Error getting video metadata: {str(e)}")
            video_info = {}
        
        # Calculate processing time
        end_time = time.time()
        # Ensure start_time is a float before subtraction
        if isinstance(start_time, str):
            try:
                start_time = float(start_time)
            except ValueError:
                # If conversion fails, just use the current time as start time
                # This means processing_time will be near zero
                start_time = end_time
        processing_time = end_time - start_time
        
        # Return the result
        result = {
            "file_url": file_url,
            "local_path": output_path,
            "processing_time": processing_time,
            "metadata": video_info
        }
        
        return result
    except Exception as e:
        logger.error(f"Error adding subtitles: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None
