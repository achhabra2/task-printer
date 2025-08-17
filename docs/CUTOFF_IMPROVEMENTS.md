# Text Cutoff Prevention Improvements

## Problem
The printed task labels with flair icons were experiencing text cutoff issues:
- Text getting cut off on the right side
- Text getting cut off on the bottom
- Icons sometimes positioned too close to edges

## Root Causes
1. **No Safety Margins**: The original code used `left_margin = 0` and `right_margin = 0`, meaning text could extend to the very edge of the defined receipt width
2. **Printer Limitations**: Real thermal printers often have unprintable margins that the software wasn't accounting for
3. **Pixel-Perfect Text Wrapping**: The text wrapping calculations assumed perfect pixel accuracy, but printers may have slight variations
4. **Bottom Cutoff**: Insufficient bottom padding could cause the last line to be partially cut off

## Solutions Implemented

### 1. Configurable Print Margins
Added new configuration options in `/setup`:

- **Left margin** (default: 16px): Safety margin to prevent left edge cutoff
- **Right margin** (default: 16px): Safety margin to prevent right edge cutoff  
- **Top margin** (default: 12px): Top spacing for better appearance
- **Bottom margin** (default: 16px): Bottom spacing to prevent last line cutoff
- **Text safety margin** (default: 8px): Additional text width reduction to handle edge cases

### 2. Improved Text Wrapping
- Text column width now accounts for safety margins
- Additional `text_safety_margin` provides extra buffer for wrapping calculations
- More conservative text width calculations prevent edge case cutoffs

### 3. Updated Layout Calculations
- Image height calculations now use separate top and bottom margins instead of `margin * 2`
- Separator and flair positioning updated to respect new margin system
- Better vertical centering of flair icons within available space

### 4. Live Preview Updates
- Setup page preview now shows the effect of margin changes in real-time
- JavaScript preview logic matches server-side calculations exactly
- Users can see how margin adjustments affect layout before saving

## Configuration Options

All new settings are available in the `/setup` page under the "Print Margins (anti-cutoff)" section:

```json
{
  "print_left_margin": 16,     // 0-50px, prevents left cutoff
  "print_right_margin": 16,    // 0-50px, prevents right cutoff  
  "print_top_margin": 12,      // 0-50px, top spacing
  "print_bottom_margin": 16,   // 0-50px, prevents bottom cutoff
  "text_safety_margin": 8      // 0-20px, extra text wrapping buffer
}
```

## Backward Compatibility
- Existing configurations without these settings will use the new defaults
- Default values are chosen to prevent cutoff while maintaining good layout
- Users can set margins to 0 to restore old behavior if needed

## Testing
- All existing tests continue to pass
- New test script demonstrates the improvements (`test_margin_improvements.py`)
- Setup page preview provides immediate visual feedback

## Benefits
1. **Significantly reduced text cutoff** on both horizontal and vertical edges
2. **Better printer compatibility** by accounting for hardware limitations  
3. **User control** over margins via the setup interface
4. **Improved reliability** across different printer models and paper sizes
5. **Visual feedback** through live preview to fine-tune settings

The improvements maintain the existing layout logic while adding safety margins that account for real-world printer limitations and edge cases in text rendering.
