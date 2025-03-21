# Thai Subtitle Processing Documentation

## Overview

The Thai subtitle processing system provides enhanced support for rendering Thai subtitles in videos. It addresses specific challenges related to Thai text rendering, including proper character display, word segmentation, and synchronization with video content.

## Features

- **Thai Language Detection**: Automatically detects Thai text and applies appropriate settings
- **Word Segmentation**: Uses PyThaiNLP for intelligent word segmentation to improve readability
- **Font Support**: Compatible with Thai fonts including Sarabun, Garuda, Loma, and others
- **Styling Options**: Multiple styling presets and customization options
- **Performance Optimization**: Caching mechanism to avoid redundant processing
- **Queue Processing**: Support for high-volume batch processing

## API Reference

### `process_captioning_v1`

Main entry point for video captioning requests.

```python
def process_captioning_v1(request_data):
    """
    Process a video captioning request.
    
    Parameters:
    -----------
    request_data : dict
        Dictionary containing request parameters:
        - video_url: URL of the video to process
        - subtitle_file: SRT subtitle file content or URL
        - font_name: Font to use (default: "Sarabun" for Thai)
        - font_size: Font size (default: 28 for Thai)
        - subtitle_style: Style preset (default: "classic")
        - other styling parameters
    
    Returns:
    --------
    dict
        Dictionary with processing results:
        - file_url: URL to access the processed video
        - local_path: Local path to the processed video
        - processing_time: Time taken to process
    """
```

### `add_subtitles_to_video`

Core function for adding subtitles to videos.

```python
def add_subtitles_to_video(video_path, subtitle_path, output_path=None, job_id=None, 
                          font_name="Arial", font_size=24, margin_v=40, subtitle_style="classic",
                          max_words_per_line=7, line_color="white", word_color=None, outline_color="black",
                          all_caps=False, x=None, y=None, alignment="center", bold=False, italic=False,
                          underline=False, strikeout=False):
    """
    Add subtitles to a video with enhanced support for Thai language.
    """
```

## Styling Options

### Subtitle Styles

- **classic**: White text with black outline
- **modern**: White text with semi-transparent background
- **premium**: Enhanced styling with better readability
- **minimal**: Simple styling with minimal visual elements

### Font Recommendations for Thai

- **Sarabun**: Modern Thai font with excellent readability
- **Garuda**: Clean, professional Thai font
- **Loma**: Good for technical content
- **Kinnari**: Traditional Thai style
- **Norasi**: Formal Thai font
- **Sawasdee**: Contemporary Thai font
- **Waree**: Clean and minimal

## Performance Considerations

### Caching

The system implements a caching mechanism that:
- Stores processed videos based on input parameters and file contents
- Automatically expires cache entries after 24 hours
- Periodically cleans expired entries
- Verifies cache validity before reusing

### Queue Processing

For high-volume processing, the system provides:
- Asynchronous job processing
- Job status tracking
- Priority-based queue management
- Automatic retry for failed jobs

## Best Practices

1. **Font Selection**: Use "Sarabun" for best Thai text rendering
2. **Font Size**: Use at least 28px for Thai text
3. **Words Per Line**: Limit to 4 words per line for Thai text
4. **Vertical Margin**: Use at least 60px for Thai text
5. **Testing**: Test with various Thai text complexities

## Troubleshooting

### Common Issues

1. **Missing Characters**: Ensure proper Thai font is installed and specified
2. **Overlapping Tone Marks**: Increase line spacing or font size
3. **Word Breaking Issues**: Ensure PyThaiNLP is installed
4. **Performance Issues**: Check cache configuration and queue settings

### Logging

The system provides comprehensive logging:
- Processing parameters
- FFmpeg commands
- Error details
- Performance metrics

## Examples

### Basic Usage

```python
result = add_subtitles_to_video(
    video_path="input.mp4",
    subtitle_path="subtitles.srt",
    font_name="Sarabun",
    font_size=28,
    subtitle_style="premium"
)
```

### Custom Styling

```python
result = add_subtitles_to_video(
    video_path="input.mp4",
    subtitle_path="subtitles.srt",
    font_name="Sarabun",
    font_size=32,
    line_color="yellow",
    outline_color="black",
    bold=True,
    max_words_per_line=3
)
```
