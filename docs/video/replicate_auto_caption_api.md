# Replicate Auto Caption API

This API endpoint specifically uses Replicate's Incredibly Fast Whisper model for transcription, with no fallback to OpenAI Whisper.

## Endpoint

```
POST /api/v1/video/replicate-auto-caption
```

## Request Parameters

| Parameter   | Type   | Required | Description                                   |
|-------------|--------|----------|-----------------------------------------------|
| video_url   | string | Yes      | URL to the video file                         |
| script_text | string | Yes      | Script text to align with the video           |
| language    | string | No       | Language code (default: "en")                 |
| settings    | object | No       | Additional settings for the captioning process |

### Settings Object

| Parameter   | Type    | Required | Description                                                |
|-------------|---------|----------|------------------------------------------------------------|
| start_time  | number  | No       | Time in seconds when subtitles should start (default: 0)   |
| font_size   | number  | No       | Size of the subtitle text (default: 24)                    |
| font_name   | string  | No       | Font to use for subtitles (default: "Arial")               |
| max_width   | number  | No       | Maximum width for subtitle lines in characters (default: 40)|
| batch_size  | number  | No       | Batch size for Replicate Whisper processing (default: 64)  |
| include_srt | boolean | No       | Whether to include SRT file URL in response (default: false)|
| audio_url   | string  | No       | URL to audio file (if different from video)                |

## Example Request

```json
{
  "video_url": "https://example.com/your-video.mp4",
  "script_text": "สวัสดีครับ นี่คือตัวอย่างสคริปต์ภาษาไทยที่จะใช้สำหรับการทำคำบรรยาย",
  "language": "th",
  "settings": {
    "start_time": 2,
    "font_size": 28,
    "font_name": "Sarabun",
    "max_width": 36,
    "batch_size": 64,
    "include_srt": true
  }
}
```

## Response

```json
{
  "status": "success",
  "message": "Replicate auto-caption completed successfully",
  "output_video_url": "https://storage.googleapis.com/your-bucket/videos/captioned/uuid_captioned_video.mp4",
  "transcription_tool": "replicate_whisper",
  "job_id": "replicate_auto_caption_1712153845",
  "processing_time": 25.321,
  "srt_url": "https://storage.googleapis.com/your-bucket/subtitles/uuid_subtitles.srt"
}
```

## Notes

1. This endpoint specifically uses Replicate's Incredibly Fast Whisper model with no fallback to OpenAI Whisper.
2. The audio/video file must be accessible via a public URL for Replicate to process it.
3. For Thai language transcription, it's recommended to use "Sarabun" as the font_name.
4. The batch_size parameter can be adjusted for performance tuning (higher values may process faster but use more memory).
5. If you need to use OpenAI Whisper instead, use the `/api/v1/video/script-enhanced-auto-caption` endpoint with `"transcription_tool": "openai_whisper"` in the settings.
