/**
 * Thai Text Utilities for Video Titles and Subtitles
 * 
 * This module provides improved text handling for Thai language,
 * including better line breaking at word boundaries.
 */

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
}

/**
 * Check if text is primarily Thai
 * @param {string} text - Text to check
 * @returns {boolean} True if text is primarily Thai
 */
function isThai(text) {
  const thaiChars = text.match(/[\u0E00-\u0E7F]/g) || [];
  return thaiChars.length > text.length * 0.5;
}

/**
 * Check if a line is too long for the given width
 * @param {string} line - Line to check
 * @param {number} maxWidth - Maximum width in pixels
 * @param {number} fontSize - Font size
 * @returns {boolean} True if line is too long
 */
function isLineTooLong(line, maxWidth, fontSize) {
  const charWidth = isThai(line) ? 0.6 : 0.55;
  return line.length * (fontSize * charWidth) > maxWidth * 0.8;
}

/**
 * Split a line if it's too long
 * @param {string} line - Line to split
 * @param {number} maxWidth - Maximum width in pixels
 * @param {number} fontSize - Font size
 * @returns {string[]} Array of lines
 */
function splitLineIfNeeded(line, maxWidth, fontSize) {
  const charWidth = isThai(line) ? 0.6 : 0.55;
  const estimatedCharsPerLine = Math.floor(maxWidth * 0.8 / (fontSize * charWidth));
  
  if (line.length <= estimatedCharsPerLine) {
    return [line];
  }
  
  return splitIntoLines(line, Math.ceil(line.length / estimatedCharsPerLine));
}

/**
 * Split text into a specific number of lines
 * @param {string} text - Text to split
 * @param {number} numLines - Number of lines to split into
 * @returns {string[]} Array of lines
 */
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

/**
 * Split Thai text into lines with better word boundaries
 * @param {string} text - Thai text to split
 * @param {number} numLines - Number of lines to split into
 * @returns {string[]} Array of lines
 */
function splitThaiText(text, numLines) {
  // These are common Thai prefixes/suffixes that shouldn't be separated
  const thaiPrefixes = ['การ', 'ความ', 'ใน', 'และ', 'ที่', 'ของ', 'จาก', 'โดย', 'แห่ง', 'เมื่อ'];
  const thaiSuffixes = ['ๆ', 'ไป', 'มา', 'แล้ว', 'ด้วย', 'อยู่', 'ได้', 'ให้'];
  
  // Try to find natural break points
  const potentialBreakPoints = [];
  
  // Check for common break points (after certain words)
  for (let i = 2; i < text.length - 2; i++) {
    // Check if this position follows a common suffix or precedes a common prefix
    for (const prefix of thaiPrefixes) {
      if (text.substring(i, i + prefix.length) === prefix) {
        potentialBreakPoints.push(i);
        break;
      }
    }
    
    for (const suffix of thaiSuffixes) {
      if (text.substring(i - suffix.length, i) === suffix) {
        potentialBreakPoints.push(i);
        break;
      }
    }
    
    // Also consider breaks after Thai punctuation
    if (',.!?;:'.includes(text[i-1])) {
      potentialBreakPoints.push(i);
    }
  }
  
  // If we found enough potential break points, use them
  if (potentialBreakPoints.length >= numLines - 1) {
    // Sort break points by position
    potentialBreakPoints.sort((a, b) => a - b);
    
    // Select evenly distributed break points
    const selectedBreakPoints = [];
    const step = potentialBreakPoints.length / (numLines - 1);
    
    for (let i = 0; i < numLines - 1; i++) {
      const index = Math.min(Math.floor(i * step), potentialBreakPoints.length - 1);
      selectedBreakPoints.push(potentialBreakPoints[index]);
    }
    
    // Sort the selected break points
    selectedBreakPoints.sort((a, b) => a - b);
    
    // Split text at the selected break points
    const lines = [];
    let startPos = 0;
    
    for (const breakPoint of selectedBreakPoints) {
      lines.push(text.substring(startPos, breakPoint));
      startPos = breakPoint;
    }
    
    // Add the last segment
    lines.push(text.substring(startPos));
    
    return lines;
  }
  
  // Fallback: if we couldn't find good break points, split by character count
  const charsPerLine = Math.ceil(text.length / numLines);
  const lines = [];
  
  for (let i = 0; i < text.length; i += charsPerLine) {
    // Try to avoid breaking in the middle of a word if possible
    let endPos = Math.min(i + charsPerLine, text.length);
    
    // Look ahead a bit to see if we can find a better break point
    const lookAheadRange = Math.min(10, text.length - endPos);
    for (let j = 0; j < lookAheadRange; j++) {
      if (thaiPrefixes.some(prefix => text.substring(endPos + j).startsWith(prefix))) {
        endPos = endPos + j;
        break;
      }
    }
    
    // Look behind a bit to see if we can find a better break point
    const lookBehindRange = Math.min(10, endPos - i);
    for (let j = 1; j <= lookBehindRange; j++) {
      if (thaiSuffixes.some(suffix => text.substring(endPos - j - suffix.length, endPos - j) === suffix)) {
        endPos = endPos - j;
        break;
      }
    }
    
    lines.push(text.substring(i, endPos));
    i = endPos - charsPerLine; // Adjust i since we modified endPos
  }
  
  return lines;
}

// Example usage for video title padding
function createTitleWithPadding(options = {}) {
  // Default options
  const defaults = {
    title: "",
    videoWidth: 1080,
    videoHeight: 1920,
    paddingTop: 200,
    paddingColor: "white",
    fontName: "Sarabun",
    fontColor: "black",
    borderColor: "#ffc8dd",
    baseFontSize: 50
  };
  
  // Merge defaults with provided options
  const config = {...defaults, ...options};
  
  // Get the title from input data if not provided in options
  let formattedTitle = config.title;
  if (!formattedTitle && items && items[0] && items[0].json && items[0].json.formattedTitle) {
    formattedTitle = items[0].json.formattedTitle;
  }
  
  // Process the title - escape problematic characters for FFmpeg
  formattedTitle = formattedTitle.replace(/[\\]/g, '\\\\').replace(/[']/g, "'\\''");
  
  // Determine if text contains Thai characters
  const isThai = /[\u0E00-\u0E7F]/.test(formattedTitle);
  
  // Adjust font size based on text length and language
  let baseFontSize = config.baseFontSize;
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
  
  // Get smart line breaks
  const lines = getSmartLines(formattedTitle, config.videoWidth, config.paddingTop, baseFontSize);
  
  // Calculate line height and border width
  const lineHeight = Math.min(baseFontSize * 1.3, config.paddingTop / (lines.length + 1));
  const borderw = Math.max(1, Math.floor(baseFontSize / 25)); // Scale border width with font size
  
  // Calculate total height and starting Y position
  const titleHeight = lines.length * lineHeight;
  let yStart = Math.max(10, (config.paddingTop - titleHeight) / 2);
  
  // Safety check - ensure text fits in padded area
  if (yStart + titleHeight > config.paddingTop - 10) {
    baseFontSize = Math.floor(baseFontSize * 0.9);
    const newLineHeight = Math.min(baseFontSize * 1.3, config.paddingTop / (lines.length + 1));
    yStart = Math.max(10, (config.paddingTop - lines.length * newLineHeight) / 2);
  }
  
  // Construct the FFmpeg drawtext filters
  const drawtextFilters = lines.map((line, index) => {
    // Escape single quotes for FFmpeg
    const escapedLine = line.replace(/'/g, "'\\''");
    
    return `drawtext=text='${escapedLine}'` +
      `:fontfile=/usr/share/fonts/truetype/thai-tlwg/${config.fontName}.ttf` +
      `:fontsize=${baseFontSize}` +
      `:fontcolor=${config.fontColor}` +
      `:bordercolor=${config.borderColor}` +
      `:borderw=${borderw}` +
      `:x=(w-text_w)/2` +
      `:y=${Math.round(yStart + index * lineHeight)}`;
  });
  
  // Create the final filter string
  const filterString = `scale=${config.videoWidth}:${config.videoHeight-config.paddingTop},` +
    `pad=${config.videoWidth}:${config.videoHeight}:0:${config.paddingTop}:color=${config.paddingColor}` +
    drawtextFilters.map(filter => `,${filter}`).join('');
  
  // Return the constructed filter
  return [
    {
      json: {
        filter: filterString
      }
    }
  ];
}

// Export functions for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    getSmartLines,
    isThai,
    splitThaiText,
    createTitleWithPadding
  };
}
