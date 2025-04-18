# Function Parameter Guide for NCA Toolkit Thai

This document provides guidelines for working with function parameters in the NCA Toolkit Thai project, with a special focus on Thai text processing functions.

## Table of Contents
- [Parameter Validation Best Practices](#parameter-validation-best-practices)
- [Common Function Signatures](#common-function-signatures)
- [Thai Text Processing Parameters](#thai-text-processing-parameters)
- [Subtitle Styling Parameters](#subtitle-styling-parameters)
- [Troubleshooting Parameter Errors](#troubleshooting-parameter-errors)

## Parameter Validation Best Practices

To prevent errors related to function parameters, follow these best practices:

### 1. Use Parameter Dictionaries

When passing multiple parameters to functions, consider using a dictionary and unpacking it:

```python
# Define valid parameters
valid_params = {
    "video_path": video_path,
    "subtitle_path": srt_path,
    # Other parameters...
}

# Call function with validated parameters
result = add_subtitles_to_video(**valid_params)
```

### 2. Check Function Signatures Before Calling

Always verify the function signature before passing parameters:

```python
# Import the function
from services.v1.video.caption_video import add_subtitles_to_video

# Check signature (in IDE or via help)
help(add_subtitles_to_video)
```

### 3. Add Parameter Validation in Functions

Add validation at the beginning of functions:

```python
def my_function(required_param, optional_param=None, **kwargs):
    """Function documentation."""
    # Validate required parameters
    if required_param is None:
        raise ValueError("required_param cannot be None")
        
    # Check for unexpected parameters
    valid_kwargs = ['param1', 'param2', 'param3']
    for key in kwargs:
        if key not in valid_kwargs:
            raise ValueError(f"Unexpected parameter: {key}")
```

## Common Function Signatures

### add_subtitles_to_video

```python
def add_subtitles_to_video(
    video_path, 
    subtitle_path, 
    output_path, 
    font_size=24, 
    font_name="Arial", 
    position="bottom", 
    alignment=2, 
    margin_v=30, 
    subtitle_style="classic", 
    line_color="white", 
    outline_color="black", 
    back_color=None, 
    word_color=None, 
    all_caps=False, 
    outline=True, 
    shadow=True, 
    border_style=1,
    x=None,
    y=None,
    italic=False,
    underline=False,
    strikeout=False,
    margin_l=None,
    margin_r=None,
    encoding=None,
    job_id=None
)
```

### process_script_enhanced_auto_caption

```python
def process_script_enhanced_auto_caption(
    video_url, 
    script_text, 
    language="en", 
    settings=None, 
    output_path=None, 
    webhook_url=None, 
    job_id=None, 
    response_type="cloud", 
    include_srt=False, 
    min_start_time=0.0, 
    subtitle_delay=0.0, 
    max_chars_per_line=30, 
    transcription_tool="openai_whisper", 
    audio_url=""
)
```

## Thai Text Processing Parameters

When working with Thai text, these parameters are particularly important:

| Parameter | Description | Default Value |
|-----------|-------------|---------------|
| `language` | Language code, set to "th" for Thai | "en" |
| `font_name` | Font name, should be a Thai-compatible font | "Sarabun" for Thai |
| `max_chars_per_line` | Maximum characters per line | 30 |
| `max_words_per_line` | Maximum words per line | 7 for Thai |

### Thai Font Selection

The system automatically selects "Sarabun" font for Thai text. This is determined by:

```python
is_thai = language.lower() == "th" or is_thai_text(script_text)
font_name = settings.get("font_name", "Sarabun" if is_thai else "Arial")
```

## Subtitle Styling Parameters

These parameters control the appearance of subtitles:

| Parameter | Description | Default Value |
|-----------|-------------|---------------|
| `font_size` | Font size in pixels | 24 |
| `position` | Position on screen (top, middle, bottom) | "bottom" |
| `margin_v` | Vertical margin in pixels | 30 |
| `subtitle_style` | Style preset (classic, modern) | "modern" |
| `line_color` | Text color | "white" |
| `outline_color` | Outline color | "black" |
| `back_color` | Background color | "&H80000000" |
| `word_color` | Color for highlighted words | None |
| `all_caps` | Convert text to uppercase | False |
| `bold` | Bold text | False |
| `italic` | Italic text | False |
| `underline` | Underlined text | False |
| `strikeout` | Strikeout text | False |
| `shadow` | Add shadow to text | True |
| `outline` | Add outline to text | True |
| `alignment` | Text alignment (1=left, 2=center, 3=right) | 2 |

## Troubleshooting Parameter Errors

If you encounter parameter-related errors:

1. **Check the function signature** in the source code
2. **Verify parameter names** match exactly
3. **Check parameter types** are correct
4. **Look for duplicate function definitions** with different signatures
5. **Use parameter validation** to catch errors early

### Common Error: Unexpected Keyword Argument

```
TypeError: add_subtitles_to_video() got an unexpected keyword argument 'max_width'
```

This means you're passing a parameter that the function doesn't accept. Check the function signature and remove the invalid parameter.

### Common Error: Missing Required Argument

```
TypeError: add_subtitles_to_video() missing 1 required positional argument: 'output_path'
```

This means you're not providing a required parameter. Make sure all required parameters are included in your function call.

### `add_subtitles_to_video` (as called from `script_enhanced_auto_caption.py`)

**Note:** Due to runtime errors (`TypeError: unexpected keyword argument`), the call to `add_subtitles_to_video` from `script_enhanced_auto_caption.py` currently uses a subset of parameters, excluding `max_width` and `max_words_per_line`. This suggests a simpler version of the function might be executing in the deployed environment. The parameters passed are:

```python
{
    "video_path": video_path,
    "subtitle_path": srt_path, 
    "output_path": output_path,
    "font_size": font_size, # Default 24
    "font_name": font_name, # Default "Sarabun"/"Arial"
    "position": position, # Default "bottom"
    "alignment": alignment, # Default "center" 
    "margin_v": margin_v, # Default 30
    "subtitle_style": subtitle_style, # Default "modern"
    "line_color": line_color, # Default "white"
    "outline_color": outline_color, # Default "black"
    "back_color": back_color, # Default "&H80000000"
    "word_color": word_color, # Default None
    "all_caps": all_caps, # Default False
    "outline": outline, # Default True
    "shadow": shadow, # Default True
    # "border_style": border_style, # Not explicitly passed, likely uses function default (1)
    "x": x, # Default None
    "y": custom_y, # Calculated or from settings
    "bold": bold, # Default False
    "italic": italic, # Default False
    "underline": underline, # Default False
    "strikeout": strikeout, # Default False
    "margin_l": margin_l, # Default None
    "margin_r": margin_r, # Default None
    "encoding": encoding, # Default None
    "job_id": job_id # Passed through
}
```

### `process_script_enhanced_auto_caption`
```python
def add_subtitles_to_video(
    video_path, 
    subtitle_path, 
    output_path, 
    font_size=24, 
    font_name="Arial", 
    position="bottom", 
    alignment=2, 
    margin_v=30, 
    subtitle_style="classic", 
    line_color="white", 
    outline_color="black", 
    back_color=None, 
    word_color=None, 
    all_caps=False, 
    outline=True, 
    shadow=True, 
    border_style=1,
    x=None,
    y=None,
    italic=False,
    underline=False,
    strikeout=False,
    margin_l=None,
    margin_r=None,
    encoding=None,
    job_id=None
)
```
