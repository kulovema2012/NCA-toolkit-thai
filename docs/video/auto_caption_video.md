# Auto-Caption Video Documentation

The Auto-Caption Video endpoint automatically transcribes and adds subtitles to videos in a single API call. It combines the transcription and captioning processes, eliminating the need to provide a separate subtitle file.

## Endpoint

```
POST /api/v1/video/auto-caption
```

## Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| video_url | string | Yes | URL or path to the video file to be captioned |
| language | string | No | Language code for transcription (e.g., "th" for Thai, "en" for English). Default is "th" |
| multi_language | boolean | No | If true, automatically detect and transcribe multiple languages. Default is false |
| font | string | No | Font to use for subtitles. Default is "Sarabun" which is optimized for Thai text |
| position | string | No | Position of subtitles: "bottom", "top", or "middle". Default is "bottom" |
| style | string | No | Subtitle style: "classic" (with outline) or "modern" (with background). Default is "classic" |
| margin | integer | No | Vertical margin in pixels. Default is 50 |
| max_width | integer | No | Maximum width as percentage of video width. Default is 80 |
| output_path | string | No | Custom output path for the captioned video |

## Example Request

```json
{
  "video_url": "https://storage.googleapis.com/kulovema2012-nca-toolkit/sample_video.mp4",
  "language": "th",
  "multi_language": false,
  "font": "Sarabun",
  "position": "top",
  "style": "modern",
  "margin": 50,
  "max_width": 80
}
```

## Response

| Field | Type | Description |
|-------|------|-------------|
| file_url | string | URL to the captioned video file |
| transcription | object | Object containing transcription details |
| transcription.text | string | Full transcription text |
| transcription.segments | array | Array of transcription segments with timestamps |
| transcription.language | string | Detected language code |
| job_id | string | Unique identifier for the job |
| status | string | Status of the operation ("success" or "error") |
| message | string | Additional information about the operation |

## Example Response

```json
{
  "file_url": "https://storage.googleapis.com/kulovema2012-nca-toolkit/output_videos/captioned_video_12345.mp4",
  "transcription": {
    "text": "สวัสดีครับ นี่คือวิดีโอตัวอย่าง",
    "language": "th",
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
        "text": "นี่คือวิดีโอตัวอย่าง"
      }
    ]
  },
  "job_id": "auto-caption-12345",
  "status": "success",
  "message": "Video successfully captioned"
}
```

## Thai Language Support

This endpoint is optimized for Thai language support with the following features:

1. **Thai Font Support**: Uses Sarabun font by default, which is optimized for Thai text rendering
2. **Proper Thai Character Rendering**: Ensures correct display of Thai characters and diacritical marks
3. **Thai Text Normalization**: Applies Thai-specific text normalization for improved subtitle readability

Other available Thai fonts include:
- Garuda
- Loma
- Kinnari
- Norasi
- Sawasdee
- Tlwg Typist
- Tlwg Typo
- Waree
- Umpush

## Multi-language Support

When `multi_language` is set to `true`, the system will:

1. Automatically detect language changes throughout the video
2. Transcribe each segment in its detected language
3. Generate subtitles that reflect the language transitions

This is particularly useful for videos that contain multiple languages, such as Thai and English.

## Error Handling

| Status Code | Description |
|-------------|-------------|
| 400 | Bad Request - Invalid parameters |
| 404 | Not Found - Video file not found |
| 500 | Internal Server Error - Processing error |

## Usage Examples

### Using cURL

```bash
curl -X POST "http://localhost:5000/api/v1/video/auto-caption" \
  -H "Content-Type: application/json" \
  -d "{\"video_url\":\"https://storage.googleapis.com/kulovema2012-nca-toolkit/sample_video.mp4\",\"font\":\"Sarabun\",\"position\":\"top\",\"style\":\"modern\"}"
```

### Using Python

```python
import requests
import json

url = "http://localhost:5000/api/v1/video/auto-caption"
payload = {
    "video_url": "https://storage.googleapis.com/kulovema2012-nca-toolkit/sample_video.mp4",
    "language": "th",
    "multi_language": False,
    "font": "Sarabun",
    "position": "top",
    "style": "modern"
}

response = requests.post(url, json=payload)
result = response.json()
print(json.dumps(result, indent=2))
```

### Using the Test Script

```bash
python test_auto_caption.py --video "https://storage.googleapis.com/kulovema2012-nca-toolkit/sample_video.mp4" --multi-language --style modern --position top
```
