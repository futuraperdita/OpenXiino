import unittest
from PIL import Image
import io
from lib.xiino_image_converter import EBDConverter, EBDImage

class TestEBDConverter(unittest.TestCase):
    def setUp(self):
        # Create a simple test image in memory
        self.test_image = Image.new('RGB', (100, 100), color='white')
        # Add some black pixels to test conversion
        for x in range(50):
            for y in range(50):
                self.test_image.putpixel((x, y), (0, 0, 0))

    def test_color_conversion(self):
        """Test that images are correctly converted to color mode"""
        converter = EBDConverter(self.test_image)
        result = converter.convert_colour(compressed=True)
        
        self.assertIsInstance(result, EBDImage)
        self.assertEqual(result.mode, 9)  # Mode 9 is compressed color
        self.assertEqual(result.width, 50)  # Should be half the original width
        self.assertEqual(result.height, 50)  # Should be half the original height
        self.assertGreater(len(result.raw_data), 0)  # Should have some data

    def test_grayscale_conversion(self):
        """Test that images are correctly converted to grayscale"""
        converter = EBDConverter(self.test_image)
        result = converter.convert_gs(depth=4, compressed=True)
        
        self.assertIsInstance(result, EBDImage)
        self.assertEqual(result.mode, 4)  # Mode 4 is compressed 4-bit grayscale
        self.assertEqual(result.width, 50)
        self.assertEqual(result.height, 50)
        self.assertGreater(len(result.raw_data), 0)

    def test_bw_conversion(self):
        """Test that images are correctly converted to black and white"""
        converter = EBDConverter(self.test_image)
        result = converter.convert_bw(compressed=True)
        
        self.assertIsInstance(result, EBDImage)
        self.assertEqual(result.mode, 1)  # Mode 1 is compressed black and white
        self.assertEqual(result.width, 50)
        self.assertEqual(result.height, 50)
        self.assertGreater(len(result.raw_data), 0)

    def test_tag_generation(self):
        """Test that EBDImage correctly generates HTML tags"""
        converter = EBDConverter(self.test_image)
        result = converter.convert_colour(compressed=True)
        
        # Test EBDIMAGE tag generation
        ebdimage_tag = result.generate_ebdimage_tag(name="1")
        self.assertIn("<EBDIMAGE", ebdimage_tag)
        self.assertIn('MODE="9"', ebdimage_tag)
        self.assertIn('NAME="1"', ebdimage_tag)
        
        # Test IMG tag generation
        img_tag = result.generate_img_tag(name="#1", alt_text="Test Image")
        self.assertIn("<IMG", img_tag)
        self.assertIn('ALT="Test Image"', img_tag)
        self.assertIn('WIDTH="50"', img_tag)
        self.assertIn('HEIGHT="50"', img_tag)
        self.assertIn('EBD="#1"', img_tag)

if __name__ == '__main__':
    unittest.main()
