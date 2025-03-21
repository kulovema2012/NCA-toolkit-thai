# Thai Subtitle Processing System

Enhanced video captioning system with specialized support for Thai language subtitles.

![Thai Subtitle Example](docs/images/thai_subtitle_example.png)

## Features

- **Thai Language Support**: Optimized rendering of Thai characters and tone marks
- **AI-Powered Word Segmentation**: Uses PyThaiNLP for intelligent Thai word segmentation
- **Multiple Thai Fonts**: Compatible with Sarabun, Garuda, Loma, and other Thai fonts
- **Advanced Styling Options**: Customizable subtitle appearance with various presets
- **Performance Optimization**: Caching system for faster processing
- **High-Volume Processing**: Queue system for batch processing
- **Cloud Storage Integration**: Support for Google Cloud Storage and AWS S3

## Getting Started

### Prerequisites

- Python 3.8+
- FFmpeg
- Thai fonts (Sarabun recommended)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/thai-subtitle-processor.git
   cd thai-subtitle-processor
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Check system dependencies:
   ```bash
   python deployment/check_dependencies.py
   ```

4. Set up environment (Linux):
   ```bash
   sudo bash deployment/setup_environment.sh
   ```

### Quick Start

```python
from services.v1.video.caption_video import add_subtitles_to_video

result = add_subtitles_to_video(
    video_path="input.mp4",
    subtitle_path="subtitles.srt",
    font_name="Sarabun",
    font_size=28,
    subtitle_style="premium"
)

print(f"Output video: {result['file_url']}")
```

## Documentation

Detailed documentation is available in the [docs](docs/) directory:

- [Thai Subtitle Processing](docs/thai_subtitle_processing.md)
- [API Reference](docs/api_reference.md)
- [Deployment Guide](deployment/README.md)

## Testing

Run the test scripts to verify functionality:

```bash
python test_thai_captioning.py
python test_queue_processor.py
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [PyThaiNLP](https://github.com/PyThaiNLP/pythainlp) for Thai language processing
- [FFmpeg](https://ffmpeg.org/) for video processing
- Thai font developers for their excellent work
