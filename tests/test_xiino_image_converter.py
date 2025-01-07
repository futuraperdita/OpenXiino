import pytest
from PIL import Image
import io
import os
import asyncio
import numpy as np
from lib.xiino_image_converter import EBDConverter, EBDImage, MAX_SVG_SIZE
from lib.dithering import apply_floyd_steinberg_dithering, apply_ordered_dithering
from lib.color_matching import (
    find_closest_color,
    find_closest_gray,
    PALETTE_ARRAY
)

TEST_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="400" height="400" version="1.1" viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg">
    <rect x="50" y="50" width="300" height="300" fill="black"/>
    <circle cx="200" cy="200" r="100" fill="white"/>
</svg>'''

TEST_SVG_PERCENTAGE = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="100%" height="100%" viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg">
    <rect x="50" y="50" width="300" height="300" fill="black"/>
    <circle cx="200" cy="200" r="100" fill="white"/>
</svg>'''

@pytest.fixture
def test_image():
    # Create a simple test image in memory
    image = Image.new('RGB', (150, 150), color='white')
    # Add some black pixels to test conversion
    for x in range(75):
        for y in range(75):
            image.putpixel((x, y), (0, 0, 0))
    return image

@pytest.fixture
def gradient_image():
    # Create a gradient image to better test dithering
    image = Image.new('RGB', (100, 100))
    for y in range(100):
        for x in range(100):
            # Create a horizontal gradient from black to white
            value = int(255 * x / 100)
            image.putpixel((x, y), (value, value, value))
    return image

@pytest.fixture
def test_palette_image():
    # Create a palette image with transparency
    image = Image.new('P', (150, 150))
    # Set up a simple palette with white and black
    palette = [255, 255, 255] * 127 + [0, 0, 0] * 128  # 127 white + 128 black entries
    image.putpalette(palette)
    # Set transparency for index 0 (first white entry)
    image.info['transparency'] = 0
    # Fill with pattern - transparent (0) and black (255)
    for x in range(150):
        for y in range(150):
            image.putpixel((x, y), 0 if x < 75 else 255)
    return image

@pytest.fixture
def test_rgba_image():
    # Create an RGBA image with transparency
    image = Image.new('RGBA', (150, 150), (255, 255, 255, 0))  # Fully transparent
    # Add some semi-transparent pixels
    for x in range(75):
        for y in range(75):
            image.putpixel((x, y), (0, 0, 0, 128))  # Semi-transparent black
    return image

@pytest.fixture
def tiny_image():
    # Create a very small image (<=100px)
    return Image.new('RGB', (80, 80), color='white')

@pytest.fixture
def wide_image():
    # Create an image with unusual aspect ratio
    return Image.new('RGB', (400, 50), color='white')

class TestEBDConverter:

    @pytest.mark.asyncio
    async def test_palette_transparency(self, test_palette_image):
        """Test that palette images with transparency are correctly matted to white"""
        converter = EBDConverter(test_palette_image)
        result = await converter.convert_colour(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 9  # Mode 9 is compressed color
        # 150x150 image should be scaled to 75x75
        assert result.width == 75  # Should be half the original width
        assert result.height == 75  # Should be half the original height
        assert len(result.raw_data) > 0  # Should have some data
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_rgba_transparency(self, test_rgba_image):
        """Test that RGBA images are correctly matted to white"""
        converter = EBDConverter(test_rgba_image)
        result = await converter.convert_colour(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 9
        # 150x150 image should be scaled to 75x75
        assert result.width == 75
        assert result.height == 75
        assert len(result.raw_data) > 0
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_svg_string_conversion(self):
        """Test that SVG strings are correctly converted"""
        converter = EBDConverter(TEST_SVG)
        result = await converter.convert_colour(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 9  # Mode 9 is compressed color
        # SVG is 400x400, should be scaled to 153x153 per Xiino spec
        assert result.width == 153
        assert result.height == 153
        assert len(result.raw_data) > 0
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_svg_percentage_dimensions(self):
        """Test that SVG with percentage dimensions uses viewBox"""
        converter = EBDConverter(TEST_SVG_PERCENTAGE)
        result = await converter.convert_colour(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 9
        assert result.width == 153  # Should use viewBox dimensions and scale
        assert result.height == 153
        assert len(result.raw_data) > 0
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_svg_file_conversion(self):
        """Test that SVG files are correctly converted"""
        # Create a temporary SVG file
        with open('test.svg', 'w') as f:
            f.write(TEST_SVG)
        try:
            converter = EBDConverter('test.svg')
            result = await converter.convert_colour(compressed=True)
            
            assert isinstance(result, EBDImage)
            assert result.mode == 9
            assert result.width == 153
            assert result.height == 153
            assert len(result.raw_data) > 0
            await converter.cleanup()
        finally:
            # Clean up
            if os.path.exists('test.svg'):
                os.remove('test.svg')

    @pytest.mark.asyncio
    async def test_svg_size_limit(self):
        """Test that large SVG files are rejected"""
        # Create a large SVG string that exceeds MAX_SVG_SIZE
        svg_header = '''<?xml version="1.0"?>
        <svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
            <rect width="100" height="100" fill="black"/>
            <!-- Padding -->'''
        svg_footer = '</svg>'
        padding = 'X' * (MAX_SVG_SIZE - len(svg_header) - len(svg_footer) + 100)
        large_svg = svg_header + padding + svg_footer
        
        with pytest.raises(ValueError, match="SVG content exceeds maximum allowed size"):
            converter = EBDConverter(large_svg)
            await converter._initialize()  # We only need to test initialization

    @pytest.mark.asyncio
    async def test_svg_invalid_content(self):
        """Test that invalid SVG content is rejected"""
        invalid_svg = '''<?xml version="1.0"?>
        <svg width="100" height="100">
            <invalid>
        </svg>'''
        with pytest.raises(ValueError, match="Invalid SVG content"):
            converter = EBDConverter(invalid_svg)
            await converter.convert_colour()

    @pytest.mark.asyncio
    async def test_image_size_limit(self):
        """Test that images with dimensions too large are rejected"""
        large_image = Image.new('RGB', (1001, 1001), color='white')  # 1001*1001 > 1000000
        with pytest.raises(ValueError, match="Image dimensions too large"):
            converter = EBDConverter(large_image)
            await converter.convert_colour()

    @pytest.mark.asyncio
    async def test_tiny_image_scaling(self, tiny_image):
        """Test that very small images aren't scaled down"""
        converter = EBDConverter(tiny_image)
        result = await converter.convert_colour()
        
        # 80x80 image should not be scaled (<=100px)
        assert result.width == 80  # Should not be scaled
        assert result.height == 80
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_wide_image_scaling(self, wide_image):
        """Test scaling of images with unusual aspect ratios"""
        converter = EBDConverter(wide_image)
        result = await converter.convert_colour()
        
        # 400x50 image should be scaled to 153x19 (max width 153)
        assert result.width == 153  # Should be scaled to max width
        assert result.height == int((50/400) * 153)  # Should maintain aspect ratio
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_color_conversion(self, test_image):
        """Test that images are correctly converted to color mode"""
        converter = EBDConverter(test_image)
        result = await converter.convert_colour(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 9  # Mode 9 is compressed color
        assert result.width == 75  # Should be half the original width
        assert result.height == 75  # Should be half the original height
        assert len(result.raw_data) > 0  # Should have some data
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_dithering_priority(self, gradient_image, monkeypatch):
        """Test that dithering method changes based on IMAGE_DITHER_PRIORITY"""
        # Test with quality (Floyd-Steinberg) dithering
        monkeypatch.setenv('IMAGE_DITHER_PRIORITY', 'quality')
        converter_quality = EBDConverter(gradient_image)
        result_quality = await converter_quality.convert_colour(compressed=True)
        await converter_quality.cleanup()
        
        # Test with performance (ordered) dithering
        monkeypatch.setenv('IMAGE_DITHER_PRIORITY', 'performance')
        converter_perf = EBDConverter(gradient_image)
        result_perf = await converter_perf.convert_colour(compressed=True)
        await converter_perf.cleanup()
        
        # Results should be different due to different dithering methods
        assert result_quality.raw_data != result_perf.raw_data

    @pytest.mark.asyncio
    async def test_grayscale_conversion(self, test_image):
        """Test that images are correctly converted to grayscale"""
        converter = EBDConverter(test_image)
        result = await converter.convert_gs(depth=4, compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 4  # Mode 4 is compressed 4-bit grayscale
        assert result.width == 75
        assert result.height == 75
        assert len(result.raw_data) > 0
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_bw_conversion(self, test_image):
        """Test that images are correctly converted to black and white"""
        converter = EBDConverter(test_image)
        result = await converter.convert_bw(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 1  # Mode 1 is compressed black and white
        assert result.width == 75
        assert result.height == 75
        assert len(result.raw_data) > 0
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_multiple_conversions(self, test_image):
        """Test that multiple conversions with the same converter work"""
        converter = EBDConverter(test_image)
        
        # First conversion
        result1 = await converter.convert_colour(compressed=True)
        assert isinstance(result1, EBDImage)
        
        # Second conversion
        result2 = await converter.convert_bw(compressed=True)
        assert isinstance(result2, EBDImage)
        
        # Third conversion
        result3 = await converter.convert_gs(depth=4, compressed=True)
        assert isinstance(result3, EBDImage)
        
        await converter.cleanup()

    @pytest.mark.asyncio
    async def test_tag_generation(self, test_image):
        """Test that EBDImage correctly generates HTML tags"""
        converter = EBDConverter(test_image)
        result = await converter.convert_colour(compressed=True)
        
        # Test EBDIMAGE tag generation
        ebdimage_tag = result.generate_ebdimage_tag(name="1")
        assert "<EBDIMAGE" in ebdimage_tag
        assert 'MODE="9"' in ebdimage_tag
        assert 'NAME="1"' in ebdimage_tag
        
        # Test IMG tag generation
        img_tag = result.generate_img_tag(name="#1", alt_text="Test Image")
        assert "<IMG" in img_tag
        assert 'ALT="Test Image"' in img_tag
        assert 'WIDTH="75"' in img_tag
        assert 'HEIGHT="75"' in img_tag
        assert 'EBD="#1"' in img_tag
        
        await converter.cleanup()

class TestDithering:
    """Tests for dithering algorithms."""

    def test_floyd_steinberg_color(self, gradient_image):
        """Test Floyd-Steinberg dithering with color data."""
        # Convert PIL image to numpy array
        data = np.array(gradient_image, dtype=np.float32)
        
        # Apply dithering
        processed_data, indices = apply_floyd_steinberg_dithering(data, find_closest_color)
        
        # Verify output shapes
        assert processed_data.shape == data.shape
        assert indices.shape == (data.shape[0], data.shape[1])
        assert processed_data.dtype == np.float32
        assert indices.dtype == np.uint8
        
        # Verify values are in valid ranges
        assert np.all(processed_data >= 0)
        assert np.all(processed_data <= 255)
        assert np.all(indices < len(PALETTE_ARRAY))

    def test_floyd_steinberg_grayscale(self, gradient_image):
        """Test Floyd-Steinberg dithering with grayscale data."""
        # Convert to grayscale
        gray_image = gradient_image.convert('L')
        data = np.array(gray_image, dtype=np.float32)
        
        # Apply dithering with 16 levels (4-bit)
        processed_data, indices = apply_floyd_steinberg_dithering(
            data,
            lambda x: find_closest_gray(x, 16)
        )
        
        # Verify output shapes
        assert processed_data.shape == data.shape
        assert indices.shape == (data.shape[0], data.shape[1])
        assert processed_data.dtype == np.float32
        assert indices.dtype == np.uint8
        
        # Verify values are in valid ranges
        assert np.all(processed_data >= 0)
        assert np.all(processed_data <= 255)
        assert np.all(indices < 16)  # 4-bit grayscale has 16 levels

    def test_ordered_color(self, gradient_image):
        """Test ordered dithering with color data."""
        # Convert PIL image to numpy array
        data = np.array(gradient_image, dtype=np.float32)
        
        # Apply dithering
        processed_data, indices = apply_ordered_dithering(data, find_closest_color)
        
        # Verify output shapes
        assert processed_data.shape == data.shape
        assert indices.shape == (data.shape[0], data.shape[1])
        assert processed_data.dtype == np.float32
        assert indices.dtype == np.uint8
        
        # Verify values are in valid ranges
        assert np.all(processed_data >= 0)
        assert np.all(processed_data <= 255)
        assert np.all(indices < len(PALETTE_ARRAY))

    def test_ordered_grayscale(self, gradient_image):
        """Test ordered dithering with grayscale data."""
        # Convert to grayscale
        gray_image = gradient_image.convert('L')
        data = np.array(gray_image, dtype=np.float32)
        
        # Apply dithering with 16 levels (4-bit)
        processed_data, indices = apply_ordered_dithering(
            data,
            lambda x: find_closest_gray(x, 16)
        )
        
        # Verify output shapes
        assert processed_data.shape == data.shape
        assert indices.shape == (data.shape[0], data.shape[1])
        assert processed_data.dtype == np.float32
        assert indices.dtype == np.uint8
        
        # Verify values are in valid ranges
        assert np.all(processed_data >= 0)
        assert np.all(processed_data <= 255)
        assert np.all(indices < 16)  # 4-bit grayscale has 16 levels
