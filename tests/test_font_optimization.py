"""
Tests for improved font sizing when text would wrap by just a few characters.
"""

from task_printer.printing.render import (
    find_optimal_font_size,
    wrap_text_improved,
    resolve_font,
    _would_wrap_by_few_chars,
    render_large_text_image
)


def test_would_wrap_by_few_chars_detection():
    """Test that we correctly identify text that would benefit from smaller font."""
    config = {
        "task_font_size": 72,
        "min_font_size": 32,
        "max_font_size": 96
    }
    
    font = resolve_font(config, 72)
    max_width = 480  # Realistic width after margins from 512px receipt
    
    # Two-word phrases that should be candidates for font reduction
    two_word_candidates = [
        "Mount Pegboard",
        "Measure Pegboard", 
        "Recycle Glass",
        "Clean House"
    ]
    
    for text in two_word_candidates:
        lines = wrap_text_improved(text, font, max_width)
        if len(lines) == 2:  # Only test if it actually wraps
            assert _would_wrap_by_few_chars(text, font, max_width, 3), \
                f"'{text}' should be detected as few-chars wrap candidate"
    
    # Text that should NOT be candidates (single line)
    single_line_text = ["Short", "OK"]
    for text in single_line_text:
        assert not _would_wrap_by_few_chars(text, font, max_width, 3), \
            f"'{text}' should not be detected as wrap candidate (fits on one line)"
    
    # Text that should NOT be candidates (genuinely long)
    long_text = ["This is a very long sentence that should wrap normally into multiple lines"]
    for text in long_text:
        assert not _would_wrap_by_few_chars(text, font, max_width, 3), \
            f"'{text}' should not be detected as wrap candidate (genuinely long)"


def test_find_optimal_font_size_improves_two_word_wrapping():
    """Test that optimal font sizing reduces wrapping for two-word phrases."""
    config = {
        "task_font_size": 72,
        "min_font_size": 32,
        "max_font_size": 96,
        "max_overflow_chars_for_dynamic_sizing": 3,
        "enable_dynamic_font_sizing": True
    }
    
    max_width = 480  # Realistic width
    
    test_cases = [
        "Mount Pegboard",
        "Measure Pegboard"
    ]
    
    for text in test_cases:
        # Check base font behavior
        base_font = resolve_font(config, config["task_font_size"])
        base_lines = wrap_text_improved(text, base_font, max_width)
        
        # Skip if base font already fits on one line
        if len(base_lines) <= 1:
            continue
            
        # Check optimized font behavior
        opt_font, opt_size = find_optimal_font_size(text, config, max_width)
        opt_lines = wrap_text_improved(text, opt_font, max_width)
        
        # Should either reduce lines or maintain same lines with larger font
        assert len(opt_lines) <= len(base_lines), \
            f"Optimization should not increase lines for '{text}'"
        
        # For two-word phrases that wrap with base font, should fit on one line with smaller font
        if len(base_lines) == 2 and len(text.split()) == 2:
            assert len(opt_lines) == 1, \
                f"Two-word phrase '{text}' should fit on one line after optimization"
            assert opt_size < config["task_font_size"], \
                f"Font size should be reduced for '{text}'"


def test_font_size_optimization_preserves_readability():
    """Test that font size optimization doesn't make fonts too small."""
    config = {
        "task_font_size": 72,
        "min_font_size": 40,  # Set a reasonable minimum
        "max_font_size": 96,
        "max_overflow_chars_for_dynamic_sizing": 3,
        "enable_dynamic_font_sizing": True
    }
    
    max_width = 200  # Very narrow to force optimization
    
    text = "Mount Pegboard"
    opt_font, opt_size = find_optimal_font_size(text, config, max_width)
    
    # Should not go below minimum font size
    assert opt_size >= config["min_font_size"], \
        f"Optimized font size {opt_size} should not be below minimum {config['min_font_size']}"


def test_render_large_text_image_with_optimization():
    """Test that the full rendering pipeline uses optimization correctly."""
    config = {
        "task_font_size": 72,
        "receipt_width": 512,
        "min_font_size": 32,
        "max_font_size": 96,
        "max_overflow_chars_for_dynamic_sizing": 3,
        "enable_dynamic_font_sizing": True,
        "print_left_margin": 16,
        "print_right_margin": 16,
        "print_top_margin": 12,
        "print_bottom_margin": 16
    }
    
    # Test case that should benefit from optimization
    text = "Mount Pegboard"
    
    # Render with optimization enabled
    img = render_large_text_image(text, config)
    
    # Basic sanity checks
    assert img.mode == "L"
    assert img.width == config["receipt_width"]
    assert img.height > 0
    
    # Test with optimization disabled for comparison
    config_no_opt = config.copy()
    config_no_opt["enable_dynamic_font_sizing"] = False
    
    img_no_opt = render_large_text_image(text, config_no_opt)
    
    # Both should render successfully
    assert img_no_opt.mode == "L"
    assert img_no_opt.width == config["receipt_width"]
    assert img_no_opt.height > 0


def test_optimization_does_not_affect_long_text():
    """Test that optimization doesn't interfere with genuinely long text."""
    config = {
        "task_font_size": 72,
        "min_font_size": 32,
        "max_font_size": 96,
        "max_overflow_chars_for_dynamic_sizing": 3,
        "enable_dynamic_font_sizing": True
    }
    
    max_width = 480
    
    long_text = "This is a genuinely long piece of text that should wrap into multiple lines normally"
    
    # Should not be detected as few-chars case
    base_font = resolve_font(config, config["task_font_size"])
    assert not _would_wrap_by_few_chars(long_text, base_font, max_width, 3)
    
    # Optimization should still work but not try to force onto fewer lines aggressively
    opt_font, opt_size = find_optimal_font_size(long_text, config, max_width)
    opt_lines = wrap_text_improved(long_text, opt_font, max_width)
    
    # Should have multiple lines (not trying to force into 1-2 lines)
    assert len(opt_lines) >= 3, "Long text should still wrap into multiple lines"
