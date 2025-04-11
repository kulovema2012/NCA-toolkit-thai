# Video Padding

## Overview

The video padding feature allows you to add blank space around a video, similar to CSS padding in web development. This is useful for creating letterboxed videos, adding space for titles or captions, or creating consistent aspect ratios across different source videos.

## Comprehensive Benefits of Padding

### Visual Enhancement Benefits
1. **Improved Content Framing**: Padding creates visual breathing room around your content, making it more aesthetically pleasing and easier to focus on.
2. **Aspect Ratio Standardization**: Convert videos of varying dimensions to a standard aspect ratio without cropping or stretching the original content.
3. **Branding Space**: Create dedicated areas for logos, watermarks, or brand elements that don't interfere with the main content.
4. **Content Preservation**: Unlike cropping, padding ensures that no part of the original video is lost when adapting to different display formats.

### Technical Benefits
1. **Subtitle Optimization**: Create dedicated space for subtitles that doesn't overlap with important visual content.
2. **Mobile Optimization**: Easily convert landscape videos to portrait format (9:16) for stories and mobile-first platforms.
3. **Thumbnail Improvement**: Videos with padding often generate better thumbnails with proper framing.
4. **Consistent Player Experience**: Standardized dimensions ensure consistent playback across different devices and platforms.

### Accessibility Benefits
1. **Improved Readability**: Dedicated space for subtitles with appropriate backgrounds enhances readability for viewers with hearing impairments.
2. **Reduced Visual Clutter**: Padding creates separation between the video content and the surrounding interface elements.
3. **Better Focus Management**: Clear visual boundaries help viewers with cognitive disabilities maintain focus on the content.

### Platform-Specific Benefits
1. **Social Media Optimization**: Different platforms require different aspect ratios (Instagram: 1:1 or 4:5, TikTok/Stories: 9:16, YouTube: 16:9).
2. **Advertising Compliance**: Meet specific dimension requirements for video advertisements without distorting the original content.
3. **Multi-Platform Distribution**: Create a single master video that can be easily adapted to different platform requirements.

## API Endpoints

The padding feature is available in the following endpoints:

- `/v1/video/script_enhanced_auto_caption`: Add padding while also adding subtitles to a video
- `/v1/ffmpeg/compose`: Add padding using the flexible FFmpeg composition endpoint

## Parameters

When using the padding feature, you can specify the following parameters:

| Parameter | Type | Description | Default | Valid Values | Notes |
|-----------|------|-------------|---------|-------------|-------|
| `padding` | Integer | A single value (in pixels) to apply padding equally to all sides of the video | 0 | ≥ 0 | Overridden by individual padding values if specified |
| `padding_top` | Integer | Padding to add to the top of the video (in pixels) | 0 | ≥ 0 | Takes precedence over `padding` |
| `padding_bottom` | Integer | Padding to add to the bottom of the video (in pixels) | 0 | ≥ 0 | Takes precedence over `padding` |
| `padding_left` | Integer | Padding to add to the left side of the video (in pixels) | 0 | ≥ 0 | Takes precedence over `padding` |
| `padding_right` | Integer | Padding to add to the right side of the video (in pixels) | 0 | ≥ 0 | Takes precedence over `padding` |
| `padding_color` | String | Color of the padding | "white" | Color names or hex codes | Supports standard color names and hex codes (e.g., "0xFFFFFF") |
| `padding_style` | String | Style of padding to apply | "solid" | "solid", "gradient", "pattern", "image" | Determines the type of padding effect |
| `gradient_colors` | Array | List of colors for gradient padding | ["white", "skyblue"] | Array of color names or hex codes | Only used when padding_style is "gradient" |
| `gradient_direction` | String | Direction of the gradient | "vertical" | "vertical", "horizontal", "radial" | Only used when padding_style is "gradient" |
| `pattern_type` | String | Type of pattern to use | null | "checkerboard", "stripes" | Only used when padding_style is "pattern" |
| `pattern_size` | Integer | Size of pattern elements in pixels | 40 | > 0 | Controls the size of checkerboard squares or stripe width |
| `pattern_image` | String | URL or path to an image to use as pattern | null | Valid URL or file path | Only used when padding_style is "image" |

### Parameter Details

#### Padding Values
- **Individual vs. Global Padding**: When both `padding` and individual padding values (e.g., `padding_top`) are specified, the individual values take precedence.
- **Zero Padding**: Setting a padding value to 0 means no padding will be added to that side.
- **Maximum Values**: While there's no hard limit on padding values, extremely large values (>10000px) may cause performance issues.
- **Odd-Numbered Padding**: Some codecs perform better with even-numbered dimensions, so consider using even values for padding.

#### Padding Colors
- **Named Colors**: Standard color names like "white", "black", "red", "blue", "green", "yellow", etc.
- **Hexadecimal Colors**: Hex color codes in the format "0xRRGGBB" (e.g., "0xFF0000" for red).
- **Transparency**: Currently, transparency in padding is not supported.

## Advanced Padding Styles

In addition to solid color padding, the system now supports several advanced padding styles:

### Gradient Padding

Gradient padding creates a smooth transition between two or more colors in the padded area. This can create visually appealing effects that complement your video content.

#### Gradient Parameters

- `padding_style`: Set to "gradient" to use gradient padding
- `gradient_colors`: Array of colors to use in the gradient (e.g., ["white", "skyblue"])
- `gradient_direction`: Direction of the gradient ("vertical", "horizontal", or "radial")

#### Gradient Example

```json
{
  "video_url": "https://example.com/video.mp4",
  "script_text": "Your script text here",
  "language": "th",
  "settings": {
    "padding_top": 200,
    "padding_style": "gradient",
    "gradient_colors": ["#FFFFFF", "#87CEEB"],
    "gradient_direction": "vertical",
    "font_size": 36,
    "position": "top"
  }
}
```

This creates a video with a 200-pixel gradient padding at the top that transitions from white (#FFFFFF) to sky blue (#87CEEB) vertically.

### Pattern Padding

Pattern padding applies repeating patterns to the padded area, which can add visual interest and texture to your videos.

#### Pattern Types

1. **Checkerboard Pattern**:
   - `padding_style`: Set to "pattern"
   - `pattern_type`: Set to "checkerboard"
   - `pattern_size`: Size of each checker square in pixels (default: 40)
   - `padding_color`: Primary color of the checkerboard (the secondary color will be automatically chosen for contrast)

2. **Stripes Pattern**:
   - `padding_style`: Set to "pattern"
   - `pattern_type`: Set to "stripes"
   - `pattern_size`: Width of each stripe in pixels (default: 20)
   - `padding_color`: Primary color of the stripes (the secondary color will be automatically chosen for contrast)

#### Pattern Example

```json
{
  "video_url": "https://example.com/video.mp4",
  "script_text": "Your script text here",
  "language": "en",
  "settings": {
    "padding_top": 100,
    "padding_bottom": 100,
    "padding_style": "pattern",
    "pattern_type": "checkerboard",
    "pattern_size": 20,
    "padding_color": "white"
  }
}
```

This creates a video with 100-pixel checkerboard padding (white and black squares, 20x20 pixels each) at the top and bottom.

### Image-Based Padding

You can also use an image as the background for padded areas, which is useful for adding textures, branding elements, or complex visual designs.

#### Image Padding Parameters

- `padding_style`: Set to "image"
- `pattern_image`: URL or file path to the image to use as the pattern

#### Image Padding Example

```json
{
  "video_url": "https://example.com/video.mp4",
  "script_text": "Your script text here",
  "language": "en",
  "settings": {
    "padding_top": 200,
    "padding_style": "image",
    "pattern_image": "https://example.com/pattern.jpg"
  }
}
```

This creates a video with 200-pixel padding at the top filled with the specified image.

## Usage Examples

### 1. Adding Equal Padding to All Sides

```json
{
  "video_url": "https://example.com/video.mp4",
  "script_text": "Your script text here",
  "language": "en",
  "settings": {
    "padding": 50,
    "padding_color": "black"
  }
}
```

This will add 50 pixels of black padding to all sides of the video.

### 2. Adding Custom Padding to Different Sides

```json
{
  "video_url": "https://example.com/video.mp4",
  "script_text": "Your script text here",
  "language": "en",
  "settings": {
    "padding_top": 200,
    "padding_bottom": 50,
    "padding_left": 30,
    "padding_right": 30,
    "padding_color": "white"
  }
}
```

This will add 200 pixels of padding to the top, 50 pixels to the bottom, and 30 pixels to both the left and right sides of the video, all in white color.

### 3. Adding Padding with Subtitles

```json
{
  "video_url": "https://example.com/video.mp4",
  "script_text": "Your script text here",
  "language": "th",
  "settings": {
    "padding_top": 200,
    "padding_color": "white",
    "font_size": 36,
    "position": "top",
    "margin_v": 220
  }
}
```

This will add 200 pixels of white padding to the top of the video and position Thai subtitles in the padded area.

## Using with FFmpeg Compose

When using the `/v1/ffmpeg/compose` endpoint, you can add padding using the flexible FFmpeg composition endpoint:

```json
{
  "inputs": [
    {
      "url": "https://example.com/video.mp4"
    }
  ],
  "filters": [
    {
      "filter": "pad=1080:1920:0:200:color=white"
    }
  ],
  "outputs": [
    {
      "filename": "padded_video.mp4"
    }
  ]
}
```

This adds 200 pixels of white padding to the top of the video, resulting in a 1080x1920 output video.

### Advanced FFmpeg Compose Example with Dynamic Title in Padding

Here's a more advanced example using JavaScript to create dynamic titles in the padded area:

```javascript
// Optimized JavaScript code for dynamic video titles in padded area
function createPaddedTitleFilter(title, options = {}) {
  // Default options
  const defaults = {
    paddingTop: 200,
    videoWidth: 1080,
    videoHeight: 1920,
    baseFontSize: 50,
    fontPath: "/usr/share/fonts/truetype/thai-tlwg/Sarabun.ttf",
    fontColor: "black",
    borderColor: "#ffc8dd",
    paddingColor: "white"
  };
  
  // Merge defaults with provided options
  const config = {...defaults, ...options};
  
  // Process the title - escape problematic characters for FFmpeg
  const processedTitle = title.replace(/[\\]/g, '\\\\').replace(/[']/g, "'\\''");
  
  // Determine if text contains Thai characters
  const isThai = /[\u0E00-\u0E7F]/.test(processedTitle);
  
  // Adjust font size based on text length and language
  let fontSize = config.baseFontSize;
  if (isThai) {
    if (processedTitle.length > 40) fontSize = 45;
    if (processedTitle.length > 60) fontSize = 40;
    if (processedTitle.length > 80) fontSize = 35;
    if (processedTitle.length > 100) fontSize = 30;
  } else {
    if (processedTitle.length > 60) fontSize = 45;
    if (processedTitle.length > 80) fontSize = 40;
    if (processedTitle.length > 100) fontSize = 35;
    if (processedTitle.length > 120) fontSize = 30;
  }
  
  // Split text into lines
  const lines = getSmartLines(processedTitle, config.videoWidth, config.paddingTop, fontSize);
  
  // Calculate line height and border width
  const lineHeight = Math.min(fontSize * 1.3, config.paddingTop / (lines.length + 1));
  const borderWidth = Math.max(1, Math.floor(fontSize / 25));
  
  // Calculate starting Y position
  const titleHeight = lines.length * lineHeight;
  let yStart = Math.max(10, (config.paddingTop - titleHeight) / 2);
  
  // Safety check - ensure text fits in padded area
  if (yStart + titleHeight > config.paddingTop - 10) {
    baseFontSize = Math.floor(baseFontSize * 0.9);
    const newBorderw = Math.max(1, Math.floor(baseFontSize / 25));
    const newLineHeight = Math.min(baseFontSize * 1.3, config.paddingTop / (lines.length + 1));
    yStart = Math.max(10, (config.paddingTop - lines.length * newLineHeight) / 2);
  }
  
  // Construct the FFmpeg drawtext filters
  const drawtextFilters = lines.map((line, index) => {
    // Escape single quotes for FFmpeg
    const escapedLine = line.replace(/'/g, "'\\''");
    
    return `drawtext=text='${escapedLine}'` +
      `:fontfile=${config.fontPath}` +
      `:fontsize=${fontSize}` +
      `:fontcolor=${config.fontColor}` +
      `:bordercolor=${config.borderColor}` +
      `:borderw=${borderWidth}` +
      `:x=(w-text_w)/2` +
      `:y=${Math.round(yStart + index * lineHeight)}`;
  });
  
  // Create the final filter string
  const filterString = `scale=1080:1720,pad=1080:1920:0:${config.paddingTop}:color=${config.paddingColor}` +
    drawtextFilters.map(filter => `,${filter}`).join('');
  
  return filterString;
}

// Example usage:
const title = "ประวัติศาสตร์ไทยสมัยอยุธยา";
const filter = createPaddedTitleFilter(title, {
  paddingTop: 200,
  paddingColor: "white",
  fontColor: "black",
  borderColor: "#ffc8dd"
});

// The resulting filter can be used in an FFmpeg compose request
const composeRequest = {
  "inputs": [{ "url": "https://example.com/video.mp4" }],
  "filters": [{ "filter": filter }],
  "outputs": [{ "filename": "padded_video_with_title.mp4" }]
};
```

This JavaScript function generates an FFmpeg filter string that:
1. Scales the video to the desired dimensions
2. Adds padding to the top with the specified color
3. Adds multiple lines of text to the padded area with proper formatting
4. Handles Thai text with appropriate font and sizing

## Technical Implementation

The padding feature uses FFmpeg's `pad` filter with the following syntax:

```
pad=width:height:x:y:color
```

Where:
- `width`: The width of the output video (original width + left padding + right padding)
- `height`: The height of the output video (original height + top padding + bottom padding)
- `x`: The x-coordinate of the original video in the padded frame (usually the left padding value)
- `y`: The y-coordinate of the original video in the padded frame (usually the top padding value)
- `color`: The color of the padding

### Performance Considerations

- **File Size Impact**: Adding padding increases the output file size proportionally to the increase in pixel count.
- **Encoding Time**: Larger dimensions due to padding will increase encoding time.
- **Memory Usage**: Very large padding values may increase memory usage during processing.
- **Color Choice**: Solid colors with simple values (like white, black) encode more efficiently than complex colors.

## Subtitle Positioning with Padding

When adding padding to videos with subtitles, the subtitle positioning is automatically adjusted based on the padding values:

1. **Top Padding**: If you add top padding and use custom y-coordinates for subtitles, the y-coordinate is automatically adjusted to account for the padding.

2. **Custom Positioning**: When using custom x,y coordinates with padding, specify the coordinates relative to the original video frame, not the padded frame.

3. **Standard Positions**: When using standard positions ("top", "middle", "bottom"), the subtitles will be positioned relative to the entire padded video frame.

### Thai Subtitle Considerations

When working with Thai subtitles in padded videos:

1. **Font Selection**: The system automatically selects an appropriate Thai font if available.
2. **Line Breaking**: Thai text requires special handling for line breaks since it doesn't use spaces between words.
3. **Font Size**: Thai characters may require slightly smaller font sizes for equivalent readability.
4. **Background**: A semi-transparent background is recommended for Thai subtitles to improve readability.

## Common Use Cases

1. **Title Space**: Add padding to the top of a video to create space for titles or headers.

2. **Letterboxing**: Add padding to the top and bottom (or left and right) to create letterboxed videos with a specific aspect ratio.

3. **Branding**: Add padding to create space for logos, watermarks, or other branding elements.

4. **Mobile Optimization**: Add padding to convert videos to mobile-friendly aspect ratios (e.g., 9:16 for stories).

5. **Subtitle Placement**: Create dedicated space for subtitles outside the main video content area.

6. **Social Media Optimization**: Different platforms have different aspect ratio requirements:
   - Instagram: 1:1 (square) or 4:5 (portrait)
   - TikTok/Stories: 9:16 (vertical)
   - YouTube: 16:9 (landscape)
   - Facebook: 16:9 or 1:1
   - Twitter: 16:9 or 1:1

7. **Multi-Platform Distribution**: Create a single master video that can be easily adapted to different platform requirements by adding appropriate padding.

## Limitations and Considerations

- **File Size**: Adding large amounts of padding increases the output file size proportionally to the increase in pixel count.
- **Re-encoding**: The padding process requires re-encoding the video, which may slightly reduce quality compared to the original.
- **Performance**: Very large padding values may cause performance issues during processing.
- **Font Availability**: When adding text to padded areas, ensure that the specified fonts are available on the server.
- **Color Limitations**: Currently, only solid colors are supported for padding; gradients or patterns are not supported.
- **Subtitle Adjustments**: When using padding with subtitles, ensure that font sizes and margins are adjusted appropriately for the new dimensions.

## Complete JavaScript Example for Thai Titles in Padded Area

Below is a complete JavaScript example that handles Thai text intelligently and creates a padded area with properly formatted titles:

```javascript
// Optimized JavaScript code for dynamic video titles

// Access the formatted title from the input data
let formattedTitle = items[0].json.formattedTitle;

// Process the title - only remove problematic characters for FFmpeg
formattedTitle = formattedTitle.replace(/[\\]/g, '\\\\').replace(/[']/g, "'\\''");

/**
 * Smart line breaking function with improved Thai language support
 * @param {string} text - The text to format
 * @param {number} maxWidth - Maximum width in pixels
 * @param {number} maxHeight - Maximum height in pixels
 * @param {number} baseFontSize - Base font size
 * @returns {string[]} Array of lines
 */
function getSmartLines(text, maxWidth = 1080, maxHeight = 200, baseFontSize = 50) {
  // Handle existing line breaks
  if (text.includes('\n')) {
    return text.split('\n').flatMap(line => 
      isLineTooLong(line, maxWidth, baseFontSize) 
        ? splitLineIfNeeded(line, maxWidth, baseFontSize)
        : [line]
    );
  }
  
  // Calculate optimal parameters
  const charWidth = isThai(text) ? 0.6 : 0.55; // Thai characters need slightly more width
  const estimatedCharsPerLine = Math.floor(maxWidth * 0.8 / (baseFontSize * charWidth));
  const maxPossibleLines = Math.floor(maxHeight / (baseFontSize * 1.2));
  const estimatedLinesNeeded = Math.ceil(text.length / estimatedCharsPerLine);
  const targetLines = Math.min(Math.max(2, estimatedLinesNeeded), maxPossibleLines);
  
  // Check for title:subtitle format
  if (text.includes(':') && targetLines >= 2) {
    const [title, ...subtitleParts] = text.split(':');
    const subtitle = subtitleParts.join(':').trim();
    
    if (!subtitle) return [title];
    
    const result = [title];
    
    if (isLineTooLong(subtitle, maxWidth, baseFontSize)) {
      result.push(...splitLineIfNeeded(subtitle, maxWidth, baseFontSize));
    } else {
      result.push(subtitle);
    }
    
    return result;
  }
  
  // For normal text, split intelligently
  return splitIntoLines(text, targetLines);
  
  // Helper function to check if text is primarily Thai
  function isThai(text) {
    const thaiChars = text.match(/[\u0E00-\u0E7F]/g) || [];
    return thaiChars.length > text.length * 0.5;
  }
  
  // Helper function to check if a line is too long
  function isLineTooLong(line, maxWidth, fontSize) {
    const charWidth = isThai(line) ? 0.6 : 0.55;
    return line.length * (fontSize * charWidth) > maxWidth * 0.8;
  }
  
  // Helper function to split a line if needed
  function splitLineIfNeeded(line, maxWidth, fontSize) {
    const charWidth = isThai(line) ? 0.6 : 0.55;
    const estimatedCharsPerLine = Math.floor(maxWidth * 0.8 / (fontSize * charWidth));
    
    if (line.length <= estimatedCharsPerLine) {
      return [line];
    }
    
    return splitIntoLines(line, Math.ceil(line.length / estimatedCharsPerLine));
  }
  
  // Helper function to split text into a specific number of lines
  function splitIntoLines(text, numLines) {
    // For Thai text, we need special handling since we can't split on spaces
    if (isThai(text)) {
      return splitThaiText(text, numLines);
    }
    
    const words = text.split(' ');
    const totalWords = words.length;
    
    // If too few words for requested lines, reduce lines
    const actualLines = Math.min(numLines, Math.ceil(totalWords / 2));
    
    // Try to find natural break points for 2-line splits
    if (actualLines === 2) {
      const breakWords = ['of', 'and', 'or', 'but', 'for', 'nor', 'so', 'yet', 'with', 'by', 'to', 'in'];
      const startSearch = Math.floor(totalWords / 3);
      const endSearch = Math.ceil(2 * totalWords / 3);
      
      for (let i = startSearch; i < endSearch; i++) {
        if (breakWords.includes(words[i].toLowerCase())) {
          return [
            words.slice(0, i + 1).join(' '),
            words.slice(i + 1).join(' ')
          ];
        }
      }
    }
    
    // If no natural breaks found or more than 2 lines needed, split evenly
    const wordsPerLine = Math.ceil(totalWords / actualLines);
    const lines = [];
    
    for (let i = 0; i < totalWords; i += wordsPerLine) {
      lines.push(words.slice(i, Math.min(i + wordsPerLine, totalWords)).join(' '));
    }
    
    return lines;
  }
  
  // Helper function to split Thai text into lines
  function splitThaiText(text, numLines) {
    // For Thai, we need to split by character count since there are no spaces
    const charsPerLine = Math.ceil(text.length / numLines);
    const lines = [];
    
    for (let i = 0; i < text.length; i += charsPerLine) {
      lines.push(text.substring(i, Math.min(i + charsPerLine, text.length)));
    }
    
    return lines;
  }
}

// Determine font size based on text length and language
let baseFontSize = 50;
const isThai = /[\u0E00-\u0E7F]/.test(formattedTitle);

// Thai text needs slightly smaller font sizes
if (isThai) {
  if (formattedTitle.length > 40) baseFontSize = 45;
  if (formattedTitle.length > 60) baseFontSize = 40;
  if (formattedTitle.length > 80) baseFontSize = 35;
  if (formattedTitle.length > 100) baseFontSize = 30;
} else {
  if (formattedTitle.length > 60) baseFontSize = 45;
  if (formattedTitle.length > 80) baseFontSize = 40;
  if (formattedTitle.length > 100) baseFontSize = 35;
  if (formattedTitle.length > 120) baseFontSize = 30;
}

// Define padding and video dimensions
const paddingTop = 200; // Height of the white padding area at the top
const videoWidth = 1080; // Width of the video
const videoHeight = 1920; // Total height of the video

// Get smart line breaks
const lines = getSmartLines(formattedTitle, videoWidth, paddingTop, baseFontSize);

// Calculate line height and border width
const lineHeight = Math.min(baseFontSize * 1.3, paddingTop / (lines.length + 1));
const borderw = Math.max(1, Math.floor(baseFontSize / 25)); // Scale border width with font size

// Calculate total height and starting Y position
const titleHeight = lines.length * lineHeight;
let yStart = Math.max(10, (paddingTop - titleHeight) / 2);

// Safety check - ensure text fits in padded area
if (yStart + titleHeight > paddingTop - 10) {
  baseFontSize = Math.floor(baseFontSize * 0.9);
  const newBorderw = Math.max(1, Math.floor(baseFontSize / 25));
  const newLineHeight = Math.min(baseFontSize * 1.3, paddingTop / (lines.length + 1));
  yStart = Math.max(10, (paddingTop - lines.length * newLineHeight) / 2);
}

// Construct the FFmpeg drawtext filters
const drawtextFilters = lines.map((line, index) => {
  // Escape single quotes for FFmpeg
  const escapedLine = line.replace(/'/g, "'\\''");
  
  return `drawtext=text='${escapedLine}'` +
    `:fontfile=/usr/share/fonts/truetype/thai-tlwg/Sarabun.ttf` +
    `:fontsize=${baseFontSize}` +
    `:fontcolor=black` +
    `:bordercolor=#ffc8dd` +
    `:borderw=${borderw}` +
    `:x=(w-text_w)/2` +
    `:y=${Math.round(yStart + index * lineHeight)}`;
});

// Create the final filter string
const filterString = `scale=1080:1720,pad=1080:1920:0:${paddingTop}:color=white` +
  drawtextFilters.map(filter => `,${filter}`).join('');

// Return the constructed filter
return [
  {
    json: {
      filter: filterString
    }
  }
];
```

This code:
1. Takes a title (including Thai text) and formats it for display in a padded area
2. Intelligently breaks the text into multiple lines based on content length and language
3. Adjusts font size based on text length and language
4. Positions the text properly within the padded area
5. Generates an FFmpeg filter string that can be used with the FFmpeg compose endpoint

## Using Advanced Padding with FFmpeg Compose

When using the `/v1/ffmpeg/compose` endpoint, you can implement advanced padding using more complex filter chains:

### Gradient Padding with FFmpeg Compose

```json
{
  "inputs": [
    {
      "url": "https://example.com/video.mp4"
    }
  ],
  "filters": [
    {
      "filter": "color=s=1080x1920:c=black,format=rgba,geq=r='Y/1920*255':g='(1-Y/1920)*255':b='128':a='255'[bg];[bg][0:v]overlay=0:200[v]"
    }
  ],
  "outputs": [
    {
      "filename": "gradient_padded_video.mp4"
    }
  ]
}
```

This creates a vertical gradient background and overlays the video with 200 pixels of top padding.

### Checkerboard Pattern with FFmpeg Compose

```json
{
  "inputs": [
    {
      "url": "https://example.com/video.mp4"
    }
  ],
  "filters": [
    {
      "filter": "color=s=1080x1920:c=white[bg1];color=s=1080x1920:c=black[bg2];nullsrc=s=1080x1920,geq=lum='if(mod(floor(X/40)+floor(Y/40),2),255,0)':cb=128:cr=128[checkerboard];[bg1][bg2]blend=all_expr='if(eq(A,0),B,A)'[bg_blend];[bg_blend][checkerboard]alphamerge[bg];[bg][0:v]overlay=0:200[v]"
    }
  ],
  "outputs": [
    {
      "filename": "checkerboard_padded_video.mp4"
    }
  ]
}
```

This creates a checkerboard pattern background and overlays the video with 200 pixels of top padding.
