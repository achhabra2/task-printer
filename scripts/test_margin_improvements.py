#!/usr/bin/env python3
"""
Test script to demonstrate the margin improvements for preventing text cutoff.
"""

from task_printer.printing.render import render_task_with_flair_image, render_large_text_image
from PIL import Image, ImageDraw

def create_test_icon():
    """Create a simple test icon."""
    icon = Image.new("L", (100, 100), 255)
    draw = ImageDraw.Draw(icon)
    # Draw a simple shape
    draw.rectangle([10, 10, 90, 90], fill=0)
    draw.rectangle([30, 30, 70, 70], fill=255)
    return icon

def test_margins():
    """Test rendering with and without margin improvements."""
    test_text = "This is a longer task description that should wrap properly and not get cut off at the edges or bottom of the receipt"
    icon = create_test_icon()
    
    # Test with old settings (no margins, no dynamic sizing)
    old_config = {
        "receipt_width": 512,
        "task_font_size": 72,
        "print_left_margin": 0,
        "print_right_margin": 0,
        "print_top_margin": 10,
        "print_bottom_margin": 10,
        "text_safety_margin": 0,
        "enable_dynamic_font_sizing": False,
    }
    
    # Test with new improved settings (with margins and dynamic sizing)
    new_config = {
        "receipt_width": 512,
        "task_font_size": 72,
        "print_left_margin": 16,
        "print_right_margin": 16,
        "print_top_margin": 12,
        "print_bottom_margin": 16,
        "text_safety_margin": 8,
        "enable_dynamic_font_sizing": True,
        "min_font_size": 32,
        "max_font_size": 96,
    }
    
    print("Generating test images...")
    
    # Generate both versions
    old_image = render_task_with_flair_image(test_text, icon, old_config)
    new_image = render_task_with_flair_image(test_text, icon, new_config)
    
    # Save for comparison
    old_image.save("/tmp/old_margins.png")
    new_image.save("/tmp/new_margins.png")
    
    print(f"Old version size: {old_image.size}")
    print(f"New version size: {new_image.size}")
    print("Saved comparison images to /tmp/old_margins.png and /tmp/new_margins.png")
    
    # Test text-only rendering too
    old_text_only = render_large_text_image(test_text, old_config)
    new_text_only = render_large_text_image(test_text, new_config)
    
    old_text_only.save("/tmp/old_text_only.png")
    new_text_only.save("/tmp/new_text_only.png")
    
    print(f"Old text-only size: {old_text_only.size}")
    print(f"New text-only size: {new_text_only.size}")
    print("Saved text-only comparison images to /tmp/old_text_only.png and /tmp/new_text_only.png")
    
    # The new version should have better text positioning and less chance of cutoff
    assert new_image.width == old_image.width, "Width should remain the same"
    print("✓ Test completed successfully")

if __name__ == "__main__":
    test_margins()
