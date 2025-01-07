import pytest
from PIL import Image
import io
import os
import asyncio
from lib.xiino_image_converter import EBDConverter, EBDImage

TEST_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="400" height="400" version="1.1" viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg">
    <rect x="50" y="50" width="300" height="300" fill="black"/>
    <circle cx="200" cy="200" r="100" fill="white"/>
</svg>'''

@pytest.fixture
def test_image():
    # Create a simple test image in memory
    image = Image.new('RGB', (100, 100), color='white')
    # Add some black pixels to test conversion
    for x in range(50):
        for y in range(50):
            image.putpixel((x, y), (0, 0, 0))
    return image

@pytest.fixture
def test_palette_image():
    # Create a palette image with transparency
    image = Image.new('P', (100, 100))
    # Set up a simple palette with white and black
    palette = [255, 255, 255] * 127 + [0, 0, 0] * 128  # 127 white + 128 black entries
    image.putpalette(palette)
    # Set transparency for index 0 (first white entry)
    image.info['transparency'] = 0
    # Fill with pattern - transparent (0) and black (255)
    for x in range(100):
        for y in range(100):
            image.putpixel((x, y), 0 if x < 50 else 255)
    return image

class TestEBDConverter:

    @pytest.mark.asyncio
    async def test_palette_transparency(self, test_palette_image):
        """Test that palette images with transparency are correctly matted to white"""
        converter = EBDConverter(test_palette_image)
        result = await converter.convert_colour(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 9  # Mode 9 is compressed color
        assert result.width == 50  # Should be half the original width
        assert result.height == 50  # Should be half the original height
        assert len(result.raw_data) > 0  # Should have some data

    @pytest.mark.asyncio
    async def test_svg_string_conversion(self, test_image):
        """Test that SVG strings are correctly converted"""
        converter = EBDConverter(TEST_SVG)
        result = await converter.convert_colour(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 9  # Mode 9 is compressed color
        # SVG is 400x400, should be scaled to 153x153 per Xiino spec
        assert result.width == 153
        assert result.height == 153
        assert len(result.raw_data) > 0

    @pytest.mark.asyncio
    async def test_svg_file_conversion(self, test_image):
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
        finally:
            # Clean up
            if os.path.exists('test.svg'):
                os.remove('test.svg')

    @pytest.mark.asyncio
    async def test_color_conversion(self, test_image):
        """Test that images are correctly converted to color mode"""
        converter = EBDConverter(test_image)
        result = await converter.convert_colour(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 9  # Mode 9 is compressed color
        assert result.width == 50  # Should be half the original width
        assert result.height == 50  # Should be half the original height
        assert len(result.raw_data) > 0  # Should have some data

    @pytest.mark.asyncio
    async def test_grayscale_conversion(self, test_image):
        """Test that images are correctly converted to grayscale"""
        converter = EBDConverter(test_image)
        result = await converter.convert_gs(depth=4, compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 4  # Mode 4 is compressed 4-bit grayscale
        assert result.width == 50
        assert result.height == 50
        assert len(result.raw_data) > 0

    @pytest.mark.asyncio
    async def test_bw_conversion(self, test_image):
        """Test that images are correctly converted to black and white"""
        converter = EBDConverter(test_image)
        result = await converter.convert_bw(compressed=True)
        
        assert isinstance(result, EBDImage)
        assert result.mode == 1  # Mode 1 is compressed black and white
        assert result.width == 50
        assert result.height == 50
        assert len(result.raw_data) > 0

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
        assert 'WIDTH="50"' in img_tag
        assert 'HEIGHT="50"' in img_tag
        assert 'EBD="#1"' in img_tag
