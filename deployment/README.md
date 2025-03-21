# Thai Subtitle Processing System - Deployment Guide

This guide provides instructions for deploying the Thai subtitle processing system to production environments.

## Prerequisites

- Linux server (Ubuntu/Debian or CentOS/RHEL recommended)
- Python 3.8 or higher
- Sufficient disk space (at least 5GB recommended)
- Network access for downloading dependencies

## Deployment Steps

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd <repository-directory>
```

### 2. Check Dependencies

Run the dependency checker script to verify system requirements:

```bash
python deployment/check_dependencies.py
```

This script will check for:
- FFmpeg installation
- Thai fonts availability
- Environment configuration
- Temporary directory permissions
- Python package dependencies

### 3. Set Up Environment

For Linux environments, use the provided setup script:

```bash
sudo bash deployment/setup_environment.sh
```

For Windows environments, manually:
1. Install FFmpeg from [ffmpeg.org](https://ffmpeg.org/download.html)
2. Install Thai fonts from [Google Noto Thai](https://fonts.google.com/noto/specimen/Noto+Sans+Thai)
3. Create and configure a `.env` file based on the template

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

Edit the `.env` file created by the setup script to set:
- Cloud storage credentials (if using)
- Custom temporary directory (if needed)
- Logging level
- Queue processing parameters

### 6. Test the Installation

Run the test scripts to verify everything is working:

```bash
python test_thai_captioning.py
python test_queue_processor.py --jobs 2
```

### 7. Production Deployment

#### Using Gunicorn (Recommended)

```bash
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

#### Using Docker

A Dockerfile is provided for containerized deployment:

```bash
docker build -t thai-subtitle-processor .
docker run -p 8000:8000 thai-subtitle-processor
```

## Monitoring and Maintenance

### Logs

Logs are stored in the `logs` directory. Monitor these for errors and performance issues.

### Queue Monitoring

Use the queue monitoring endpoint to check queue status:

```
GET /api/v1/queue/stats
```

### Cache Management

The system automatically manages its cache, but you can manually clear it if needed:

```bash
python -c "from services.v1.video.caption_video import clear_cache; clear_cache()"
```

## Troubleshooting

### Common Issues

1. **Missing Thai characters in subtitles**
   - Verify Thai fonts are installed: `fc-list | grep -i thai`
   - Check font name in API requests matches installed fonts

2. **FFmpeg errors**
   - Verify FFmpeg installation: `ffmpeg -version`
   - Check logs for specific error messages

3. **Performance issues**
   - Increase worker threads in queue processor
   - Ensure sufficient disk space for temporary files
   - Monitor CPU and memory usage

4. **Cloud storage issues**
   - Verify credentials are correctly set
   - Check network connectivity to cloud provider

## Support

For additional support, refer to the documentation in the `docs` directory or contact the development team.

---

© 2025 Thai Subtitle Processing System
