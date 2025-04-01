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

## Settings Object

The settings object can contain the following properties:

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

## Example Request

```json
{
  "video_url": "https://storage.googleapis.com/your-bucket-name/your-video-file.mp4",
  "script_text": "สวัสดีครับ วันนี้เรามาพูดคุยเกี่ยวกับการพัฒนาแอปพลิเคชันด้วยภาษาไทย",
  "language": "th",
  "settings": {
    "font": {
      "name": "Sarabun",
      "size": 32
    },
    "style": {
      "subtitle_style": "modern",
      "position": "bottom",
      "alignment": "center",
      "margin_v": 60,
      "back_color": "&HFF000000",
      "line_color": "&HFFFFFF",
      "outline_color": "&H000000",
      "max_words_per_line": 18,
      "bold": true,
      "outline": 2,
      "shadow": 0
    },
    "transcription_tool": "replicate_whisper",
    "audio_url": "https://storage.googleapis.com/your-bucket-name/your-audio-file.mp3",
    "start_time": 2.0,
    "output": {
      "format": "mp4",
      "quality": "high"
    }
  },
  "job_id": "thai-subtitle-job-12345"
}
```

## Example Response

```json
{
  "status": "success",
  "data": {
    "captioned_video_url": "https://storage.googleapis.com/your-bucket-name/captioned_video.mp4",
    "job_id": "thai-subtitle-job-12345",
    "processing_time": 15.5
  }
}
```

## Notes

- The API uses AI transcription to align the script with the audio timing.
- The script text should match the audio content as closely as possible for best results.
- For Thai language, use language="th" and a Thai font like "Sarabun".
- The back_color parameter uses ASS format (&HAABBGGRR) where AA is alpha (00-FF), BB is blue, GG is green, and RR is red.
- For solid black background, use "&HFF000000".
- For semi-transparent black background, use "&H80000000".
- The start_time parameter can be used to delay the appearance of subtitles (e.g., 2.0 for 2 seconds).
- When using replicate_whisper, you can optionally provide a separate audio_url if you have a higher quality audio file.
- The replicate_whisper transcription tool generally provides more accurate results for Thai language than OpenAI Whisper.
