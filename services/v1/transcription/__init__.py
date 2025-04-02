# Import transcription modules
try:
    from .replicate_whisper import transcribe_with_replicate
except ImportError:
    pass  # Handle gracefully if the module is not available
