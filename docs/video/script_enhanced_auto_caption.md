# Script-Enhanced Auto-Caption Feature

This document describes how to use the Script-Enhanced Auto-Caption feature, which combines OpenAI's Whisper API for transcription with your pre-written voice-over script to create highly accurate Thai subtitles.

## Overview

The Script-Enhanced Auto-Caption feature addresses the issue of transcription inaccuracies by aligning your voice-over script with the timing information from the Whisper API. This feature:

1. Uses OpenAI's Whisper API for initial transcription and timing information
2. Aligns your pre-written script with the transcription timing
3. Creates enhanced subtitles with accurate text from your script
4. Adds customizable subtitles to videos with proper Thai font rendering

## API Endpoint

```
POST /api/v1/video/script-enhanced-auto-caption
```

## Request Parameters

| Parameter         | Type    | Required | Description                                       | Default   |
|-------------------|---------|----------|---------------------------------------------------|-----------|
| video_url         | string  | Yes      | URL of the video to caption                       | -         |
| script_text       | string  | Yes      | The voice-over script text                        | -         |
| language          | string  | No       | Language code (e.g., 'th' for Thai)               | 'th'      |
| font_name         | string  | No       | Font name for subtitles (Sarabun, Garuda, Loma, Kinnari, etc.) | 'Sarabun' |
| font_size         | number  | No       | Font size for subtitles                           | 24        |
| position          | string  | No       | Subtitle position ('top', 'bottom', 'middle')     | 'bottom'  |
| subtitle_style    | string  | No       | Subtitle style ('classic', 'modern')              | 'classic' |
| margin_v          | number  | No       | Vertical margin from bottom/top of frame          | 30        |
| max_width         | number  | No       | Maximum width of subtitle text (% of video width) | null      |
| output_path       | string  | No       | Output path for the captioned video (optional)    | -         |
| webhook_url       | string  | No       | Webhook URL for async processing (optional)       | -         |

## Example Request

```json
{
  "video_url": "https://example.com/video.mp4",
  "script_text": "สวัสดีครับ นี่คือตัวอย่างคำบรรยายภาษาไทย ที่ถูกต้องและชัดเจน",
  "language": "th",
  "font_name": "Sarabun",
  "font_size": 28,
  "position": "bottom",
  "subtitle_style": "modern",
  "margin_v": 40,
  "max_width": 80,
  "webhook_url": "https://your-webhook-url.com/callback"
}
```

## Example Response

```json
{
  "status": "success",
  "file_url": "https://storage.googleapis.com/your-bucket/captioned-video.mp4",
  "local_path": "/tmp/captioned-video.mp4",
  "transcription": {
    "text": "สวัสดีครับ นี่คือตัวอย่างคำบรรยายภาษาไทย ที่ถูกต้องและชัดเจน",
    "segments": [
      {
        "id": 0,
        "start": 0.0,
        "end": 2.5,
        "text": "สวัสดีครับ"
      },
      {
        "id": 1,
        "start": 2.5,
        "end": 5.0,
        "text": "นี่คือตัวอย่างคำบรรยายภาษาไทย"
      },
      {
        "id": 2,
        "start": 5.0,
        "end": 7.5,
        "text": "ที่ถูกต้องและชัดเจน"
      }
    ],
    "language": "th"
  },
  "script_enhanced": true,
  "settings": {
    "font_name": "Sarabun",
    "font_size": 28,
    "position": "bottom",
    "subtitle_style": "modern",
    "margin_v": 40,
    "max_width": 80
  }
}
```

## Requirements

To use this feature, you need to:

1. Set the `OPENAI_API_KEY` environment variable with your OpenAI API key
2. Have FFmpeg installed on your server
3. Have Thai fonts installed (Sarabun is recommended)
4. Prepare a voice-over script that matches the audio content

## How It Works

1. The system uses OpenAI's Whisper API to get initial transcription with timing information
2. Your provided script is aligned with the transcription using advanced text alignment algorithms
3. The system creates enhanced subtitles that use your accurate script text with the timing from Whisper
4. The enhanced subtitles are added to the video using FFmpeg with proper Thai font rendering

## Best Practices for Voice-Over Scripts

For best results with script alignment:

1. Make sure your script closely matches what is actually said in the video
2. Use proper Thai spelling and grammar in your script
3. Include all spoken content in your script
4. Format your script with one sentence or phrase per line for better alignment

## Error Handling

The API will return appropriate error messages in the following cases:

- No JSON data provided (400)
- No video URL provided (400)
- No script text provided (400)
- OpenAI API key not set (500)
- Transcription failed (500)
- Script alignment failed (500)
- Failed to add subtitles to video (500)

## Notes

- This feature provides the most accurate Thai subtitles by combining your script with AI-generated timing
- The alignment algorithm works best when your script closely matches the actual spoken content
- The feature supports both synchronous and asynchronous processing via webhooks
