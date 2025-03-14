import os
import whisper
import srt
import json
import unicodedata
from datetime import timedelta
from whisper.utils import WriteSRT, WriteVTT
from services.file_management import download_file
import logging

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Set the default local storage directory
STORAGE_PATH = "/tmp/"

def clean_thai_text(text):
    """
    Clean and normalize Thai text to ensure proper encoding.
    """
    if not text:
        return text
        
    # Normalize Unicode characters (important for Thai)
    normalized_text = unicodedata.normalize('NFC', text)
    
    # Check if text contains Thai characters
    def contains_thai(s):
        thai_range = range(0x0E00, 0x0E7F)
        return any(ord(c) in thai_range for c in s)
    
    # If text contains Thai, ensure it's properly encoded
    if contains_thai(normalized_text):
        # Keep Thai characters, spaces, and basic punctuation
        thai_range = range(0x0E00, 0x0E7F)
        cleaned_text = ''.join(c for c in normalized_text if ord(c) in thai_range or c.isspace() or c in '.!?,;:')
        
        # Only return cleaned text if we have something left
        if cleaned_text:
            return cleaned_text
    
    # Return normalized text if no Thai characters or cleaning removed everything
    return normalized_text

def process_transcribe_media(media_url, task, include_text, include_srt, include_segments, word_timestamps, response_type, language, job_id):
    """Transcribe or translate media and return the transcript/translation, SRT or VTT file path."""
    logger.info(f"Starting {task} for media URL: {media_url}")
    input_filename = download_file(media_url, os.path.join(STORAGE_PATH, 'input_media'))
    logger.info(f"Downloaded media to local file: {input_filename}")

    try:
        # Determine the appropriate model size based on language
        # Use medium model for Thai language to improve accuracy
        if language and language.lower() in ['th', 'thai']:
            model_size = "medium"
            language = "th"  # Explicitly set language to Thai
            logger.info(f"Using medium model for Thai language transcription")
        else:
            # Load a larger model for better translation quality
            model_size = "large" if task == "translate" else "base"
            
        model = whisper.load_model(model_size)
        logger.info(f"Loaded Whisper {model_size} model")

        # Configure transcription/translation options
        options = {
            "task": task,
            "word_timestamps": word_timestamps,
            "verbose": False
        }

        # Add language specification if provided
        if language:
            options["language"] = language
            logger.info(f"Setting language to {language} for {task}")

        result = model.transcribe(input_filename, **options)
        
        # Process Thai text if needed
        is_thai = language and language.lower() in ['th', 'thai']
        if is_thai:
            logger.info("Processing Thai text to ensure proper encoding")
            # Clean the main text
            result['text'] = clean_thai_text(result['text'])
            
            # Clean each segment's text
            for segment in result['segments']:
                segment['text'] = clean_thai_text(segment['text'])
                
                # Also clean word-level timestamps if present
                if 'words' in segment:
                    for word in segment['words']:
                        if 'word' in word:
                            word['word'] = clean_thai_text(word['word'])
        
        # For translation task, the result['text'] will be in English
        text = None
        srt_text = None
        segments_json = None

        logger.info(f"Generated {task} output")

        if include_text is True:
            text = result['text']

        if include_srt is True:
            srt_subtitles = []
            for i, segment in enumerate(result['segments'], start=1):
                start = timedelta(seconds=segment['start'])
                end = timedelta(seconds=segment['end'])
                # Use translated text if available, otherwise use transcribed text
                segment_text = segment['text'].strip()
                srt_subtitles.append(srt.Subtitle(i, start, end, segment_text))
            
            srt_text = srt.compose(srt_subtitles)

        if include_segments is True:
            segments_json = result['segments']

        os.remove(input_filename)
        logger.info(f"Removed local file: {input_filename}")
        logger.info(f"{task.capitalize()} successful, output type: {response_type}")

        if response_type == "direct":
            return text, srt_text, segments_json
        else:
            
            if include_text is True:
                text_filename = os.path.join(STORAGE_PATH, f"{job_id}.txt")
                with open(text_filename, 'w', encoding='utf-8') as f:
                    f.write(text)
            else:
                text_file = None
            
            if include_srt is True:
                srt_filename = os.path.join(STORAGE_PATH, f"{job_id}.srt")
                with open(srt_filename, 'w', encoding='utf-8') as f:
                    f.write(srt_text)
            else:
                srt_filename = None

            if include_segments is True:
                segments_filename = os.path.join(STORAGE_PATH, f"{job_id}.json")
                with open(segments_filename, 'w', encoding='utf-8') as f:
                    json.dump(segments_json, f, ensure_ascii=False, indent=2)
            else:
                segments_filename = None

            return text_filename, srt_filename, segments_filename 

    except Exception as e:
        logger.error(f"{task.capitalize()} failed: {str(e)}")
        raise