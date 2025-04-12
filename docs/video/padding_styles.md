# Video Padding Styles API

This API allows you to apply advanced padding styles to videos, including gradients, patterns, and custom title text. It features intelligent Thai text handling that automatically splits text at appropriate word boundaries.

## Endpoint

```
POST /api/v1/video/padding-styles
```

## Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| video_url | string | Yes | - | URL of the video to process |
| padding_style | string | No | "solid" | Padding style: "solid", "gradient", "radial", "checkerboard", "stripes" |
| padding_top | integer | No | 200 | Height of top padding in pixels |
| padding_bottom | integer | No | 0 | Height of bottom padding in pixels |
| padding_left | integer | No | 0 | Width of left padding in pixels |
| padding_right | integer | No | 0 | Width of right padding in pixels |
| padding_color | string | No | "white" | Color for solid padding (CSS color or hex) |
| gradient_start_color | string | No | "white" | Start color for gradient padding |
| gradient_end_color | string | No | "skyblue" | End color for gradient padding |
| gradient_direction | string | No | "vertical" | Direction for gradient: "vertical" or "horizontal" |
| pattern_size | integer | No | 40 | Size of pattern elements in pixels |
| pattern_color1 | string | No | "white" | First color for pattern |
| pattern_color2 | string | No | "black" | Second color for pattern |
| title_text | string | No | "" | Text to display in the padding area (supports Thai text with automatic line breaking) |
| font_name | string | No | "Sarabun" | Font name for title text |
| font_size | integer | No | 50 | Font size for title text |
| font_color | string | No | "black" | Font color for title text |
| border_color | string | No | "#ffc8dd" | Border/shadow color for title text |
| text_style | string | No | "outline" | Text style: "simple", "outline", "shadow", "glow", "3d" |
| text_position | string | No | "center" | Text position: "center", "left", "right", "top", "bottom" |

## Thai Text Handling

This API features intelligent Thai text handling that automatically splits text at appropriate word boundaries. When you provide Thai text in the `title_text` parameter, the system will:

1. Detect that the text is Thai
2. Use PyThaiNLP (if available) for accurate word segmentation
3. Split the text into appropriate lines based on word boundaries
4. Position the lines properly in the padding area

This ensures that Thai words are not broken incorrectly across lines. For example, text like "การปฏิวัติของสตรีในสงครามโลกครั้งที่สอง" will be properly split into lines like:

```
การปฏิวัติของสตรีในสง
ครามโลกครั้งที่สอง
```

You can also manually control line breaks by including newline characters (`\n`) in your title text.

## Example Request

```json
{
  "video_url": "https://storage.googleapis.com/nca-toolkit-buckettt/example.mp4",
  "padding_style": "radial",
  "padding_top": 200,
  "title_text": "เส้นทางสายไทย\nพลังเชื่อมโยงวัฒนธรรม",
  "font_name": "Sarabun",
  "font_size": 45,
  "font_color": "white",
  "border_color": "black",
  "text_style": "shadow",
  "text_position": "center"
}
```

## Example Response

```json
{
  "status": "success",
  "output_url": "https://storage.googleapis.com/nca-toolkit-buckettt/output_123456.mp4",
  "metadata": {
    "duration": 120.5,
    "filesize": 24500000,
    "bitrate": 1500000,
    "encoder": "libx264",
    "thumbnail_url": "https://storage.googleapis.com/nca-toolkit-buckettt/thumbnail_123456.jpg"
  }
}
```

## Available Padding Styles

### Solid Color Padding
A simple solid color background for the padding area. Good for clean, minimalist designs.

### Gradient Padding
Creates a smooth transition between two colors. Available in vertical and horizontal directions.

### Radial Gradient Padding
Creates a circular gradient that radiates outward from a center point. Good for creating a spotlight effect or drawing attention to the title.

### Checkerboard Pattern Padding
Creates an alternating pattern of two colors in a checkerboard layout. Good for creating a playful, retro aesthetic.

### Stripes Pattern Padding
Creates vertical stripes of alternating colors. Good for creating a dynamic, energetic look.

## Text Styles

### Simple
Basic text with no effects.

### Outline
Text with a colored outline for better visibility.

### Shadow
Text with a drop shadow effect for depth.

### Glow
Text with a glowing effect around it.

### 3D
Text with a 3D effect using multiple layers.
