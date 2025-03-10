from PIL import Image, ImageDraw, ImageFont
import numpy as np
import logging

logger = logging.getLogger(__name__)

def render_text_with_background(frame, text, position, font_family, font_size, text_color, bg_color):
    """
    Render text with a background box on a video frame.
    
    Args:
        frame: numpy array of the video frame
        text: text to render
        position: tuple (x, y) or strings like "center", "bottom"
        font_family: font family name
        font_size: font size
        text_color: text color (e.g., "white")
        bg_color: background color (e.g., "black")
        
    Returns:
        numpy array of the frame with rendered text
    """
    # 1. Increase padding around text to prevent cutting off
    padding_x = 20  # Horizontal padding
    padding_y = 10  # Vertical padding
    
    # 2. Use a font that fully supports Thai characters
    try:
        font = ImageFont.truetype(f"fonts/{font_family}.ttf", font_size)
    except Exception as e:
        logger.error(f"Error loading font: {str(e)}")
        # Fallback to a default font
        font = ImageFont.load_default()
    
    # 3. Create a temporary image to measure text dimensions
    img_pil = Image.fromarray(frame)
    draw = ImageDraw.Draw(img_pil)
    
    # 4. Get text size with extra padding for Thai diacritics
    text_width, text_height = draw.textsize(text, font=font)
    text_width += padding_x * 2  # Add padding to width
    text_height += padding_y * 2  # Add padding to height
    
    # 5. Calculate text position (assuming bottom center)
    x, y = position
    if x == "center":
        x = (frame.shape[1] - text_width) // 2
    if y == "bottom":
        y = frame.shape[0] - text_height - 30  # 30px from bottom
    
    # 6. Draw black background rectangle
    draw.rectangle(
        [(x, y), (x + text_width, y + text_height)],
        fill=bg_color  # Background color
    )
    
    # 7. Draw text with proper positioning to account for Thai characters
    draw.text(
        (x + padding_x, y + padding_y),  # Add padding to text position
        text,
        font=font,
        fill=text_color
    )
    
    # 8. Convert back to numpy array for OpenCV
    return np.array(img_pil)
