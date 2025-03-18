# OpenAI Auto-Caption Feature

This document describes how to use the OpenAI Auto-Caption feature, which uses OpenAI's Whisper API for transcription and then adds subtitles to videos.

## Overview

The OpenAI Auto-Caption feature is designed to provide high-quality Thai language transcription without the memory constraints of running the large Whisper model locally. This feature:

1. Uses OpenAI's Whisper API for transcription
2. Supports Thai language with proper font rendering
3. Adds customizable subtitles to videos
4. Handles both local and remote video files

## API Endpoint

```
POST /api/v1/video/openai-auto-caption
```

## Request Parameters

| Parameter   | Type   | Required | Description                                       | Default   |
|-------------|--------|----------|---------------------------------------------------|-----------|
| video_url   | string | Yes      | URL of the video to caption                       | -         |
| language    | string | No       | Language code (e.g., 'th' for Thai)               | 'th'      |
| font_name   | string | No       | Font name for subtitles                           | 'Sarabun' |
| font_size   | number | No       | Font size for subtitles                           | 24        |
| position    | string | No       | Subtitle position ('top', 'bottom', 'middle')     | 'bottom'  |
| style       | string | No       | Subtitle style ('classic', 'modern')              | 'classic' |
| output_path | string | No       | Output path for the captioned video (optional)    | -         |

## Example Request

```json
{
  "video_url": "https://example.com/video.mp4",
  "language": "th",
  "font_name": "Sarabun",
  "position": "top",
  "style": "modern",
  "webhook_url": "https://your-webhook-url.com/callback"
}
```

## Example Response

```json
{
  "status": "success",
  "file_url": "https://storage.googleapis.com/your-bucket/captioned-video.mp4",
  "transcription": {
    "text": "สวัสดีครับ นี่คือตัวอย่างคำบรรยายภาษาไทย",
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
      }
    ],
    "language": "th"
  }
}
```

## Requirements

To use this feature, you need to:

1. Set the `OPENAI_API_KEY` environment variable with your OpenAI API key
2. Have FFmpeg installed on your server
3. Have Thai fonts installed (Sarabun is recommended)

## Error Handling

The API will return appropriate error messages in the following cases:

- No JSON data provided (400)
- No video URL provided (400)
- OpenAI API key not set (500)
- Transcription failed (500)
- Empty SRT file (500)
- Failed to add subtitles to video (500)

## Notes

- This feature uses the OpenAI Whisper API which provides better accuracy for Thai language transcription than the local model.
- The API key is charged based on OpenAI's pricing model, so be aware of usage costs.
- Processing time is generally faster than using the local Whisper model, especially for longer videos.
- The feature supports both synchronous and asynchronous processing via webhooks.
