# Script-Enhanced Auto-Caption API

This API endpoint processes a video and adds subtitles based on a provided script. It uses AI transcription to align the script with the audio timing.

## Endpoint

```
POST /api/v1/video/script-enhanced-auto-caption
```

## Parameters

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| video_url | string | URL of the video to process | Yes |
| script_text | string | Text of the script to use for captioning | Yes |
| language | string | Language of the script (default: "en") | No |
| settings | object | Settings for captioning (see below) | No |
| webhook_url | string | URL to send webhook notification when processing is complete | No |
| job_id | string | Job ID for tracking | No |
| response_type | string | Type of response to return (cloud or local, default: cloud) | No |
| include_srt | boolean | Whether to include SRT file in response (default: false) | No |
| min_start_time | number | Minimum start time for subtitles in seconds (default: 0) | No |

## Request Format

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| video_url | string | Yes | URL to the video file to be captioned. Must be publicly accessible. |
| script_text | string | Yes | The script text to be aligned with the video. |
| language | string | No | Language code (default: "en"). Use "th" for Thai. |
| settings | object | No | Additional settings for the captioning process. |

### Settings Object

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| transcription_tool | string | No | Tool to use for transcription. Options: "openai_whisper" (default) or "replicate_whisper". |
| allow_fallback | boolean | No | Whether to allow fallback to the other transcription tool if the selected one fails (default: false). |
| audio_url | string | No | URL to an audio file to use instead of extracting audio from the video. Must be publicly accessible. |
| start_time | number | No | Time in seconds when subtitles should start appearing (default: 0). |
| batch_size | number | No | Batch size for Replicate Whisper processing (default: 64). |
| font_size | number | No | Font size for subtitles (default: 24). |
| max_width | number | No | Maximum width for subtitle lines (default: 40). |

### Font Settings

| Property | Type | Description | Default |
|----------|------|-------------|---------|
| font.name | string | Font name to use | "Arial" |
| font.size | number | Font size | 24 |

### Style Settings

| Property | Type | Description | Default |
|----------|------|-------------|---------|
| style.subtitle_style | string | Subtitle style (classic or modern) | "classic" |
| style.position | string | Position of subtitles (bottom, top, middle) | "bottom" |
| style.alignment | string | Alignment of subtitles (left, center, right) | "center" |
| style.margin_v | number | Vertical margin | 30 |
| style.back_color | string | Background color of subtitle box (ASS format: &HAABBGGRR or named color) | "&H80000000" |
| style.line_color | string | Text color | "&HFFFFFF" |
| style.outline_color | string | Outline color | "&H000000" |
| style.max_words_per_line | number | Maximum words per line | 7 |
| style.bold | boolean | Whether to use bold text | false |
| style.italic | boolean | Whether to use italic text | false |
| style.underline | boolean | Whether to use underlined text | false |
| style.strikeout | boolean | Whether to use strikeout text | false |
| style.shadow | number | Shadow size | 0 |
| style.outline | number | Outline size | 1 |

### Transcription Settings

| Property | Type | Description | Default |
|----------|------|-------------|---------|
| transcription_tool | string | Transcription tool to use (openai_whisper or replicate_whisper) | "openai_whisper" |
| audio_url | string | URL of the audio file to transcribe (only used with replicate_whisper) | Same as video_url |
| batch_size | number | Batch size for processing (only used with replicate_whisper) | 64 |
| start_time | number | Start time for subtitles in seconds | 0 |

### Output Settings

| Property | Type | Description | Default |
|----------|------|-------------|---------|
| output.format | string | Output format (mp4) | "mp4" |
| output.quality | string | Output quality (low, medium, high) | "medium" |

### Example Request

```json
{
  "video_url": "https://example.com/video.mp4",
  "script_text": "สวัสดีครับ นี่คือตัวอย่างสคริปต์ภาษาไทย",
  "language": "th",
  "settings": {
    "transcription_tool": "replicate_whisper",
    "allow_fallback": false,
    "start_time": 2,
    "font_size": 28,
    "max_width": 36
  }
}
```

## Response Format

### Success Response

```json
{
  "status": "success",
  "message": "Script-enhanced auto-caption completed successfully",
  "output_video_url": "https://storage.googleapis.com/your-bucket/output-video.mp4",
  "transcription_tool": "replicate_whisper",
  "job_id": "script_enhanced_auto_caption_20250402123456"
}
```

### Error Response

```json
{
  "status": "error",
  "message": "Error processing video",
  "error_details": "Specific error message"
}
```

## Notes

- The API uses AI transcription to align the script with the audio timing.
- The `video_url` and `audio_url` (if provided) must be publicly accessible URLs.
- For Replicate Whisper, the system will extract audio from video files and upload it to cloud storage to create a publicly accessible URL.
- The `script_text` will be aligned with the transcription timing to create accurate subtitles.
- Thai language is supported with specialized word segmentation for better readability.
- Supported languages for Replicate Whisper include: english, spanish, french, german, italian, portuguese, dutch, russian, chinese, japanese, korean, arabic, hebrew, thai.
- When using "th" as the language code, the system will use "thai" for Replicate or "th" for OpenAI Whisper.
- Set `allow_fallback` to false if you want to ensure only your selected transcription tool is used.
