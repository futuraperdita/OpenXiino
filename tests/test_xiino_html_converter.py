import unittest
import responses
from lib.xiino_html_converter import XiinoHTMLParser

class TestXiinoHTMLParser(unittest.TestCase):
    def setUp(self):
        self.base_url = "http://test.example.com"
        self.parser = XiinoHTMLParser(base_url=self.base_url)

    @responses.activate
    def test_data_url_image(self):
        """Test that data: URL images are correctly handled"""
        # A 10x10 black pixel PNG in base64
        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFElEQVR42mP8z8BQz0AEYBxVSF+FABJYApqNYm2lAAAAAElFTkSuQmCC"
        
        test_html = f"""
        <html>
            <body>
                <img src="{data_url}" alt="Test Data URL Image">
            </body>
        </html>
        """
        
        self.parser.feed(test_html)
        result = self.parser.get_parsed_data()
        
        # Verify image conversion
        self.assertIn("<IMG", result)  # IMG tag exists
        self.assertIn("EBD=", result)  # Has EBD reference
        self.assertIn("<EBDIMAGE", result)  # EBDIMAGE tag exists
        self.assertIn("MODE=", result)  # Has mode specified
        
    @responses.activate
    def test_html_parsing(self):
        """Test that HTML is correctly parsed and converted to Xiino format"""
        # Create a test image
        from PIL import Image
        from io import BytesIO
        test_image = Image.new('RGB', (10, 10), color='black')
        image_buffer = BytesIO()
        test_image.save(image_buffer, format='PNG')
        image_data = image_buffer.getvalue()
        image_buffer.close()

        # Mock the response for any image requests
        responses.add(
            responses.GET,
            "http://test.example.com/test.jpg",
            body=image_data,
            status=200,
            content_type="image/png"
        )

        test_html = """
        <html>
            <body>
                <h1>Test Page</h1>
                <p>This is a test paragraph</p>
                <a href="/relative/link">Relative Link</a>
                <img src="/test.jpg" alt="Test Image">
            </body>
        </html>
        """
        
        self.parser.feed(test_html)
        result = self.parser.get_parsed_data()
        
        # Verify basic HTML conversion
        self.assertIn("<H1>", result)
        self.assertIn("Test Page", result)
        self.assertIn("<P>", result)
        self.assertIn("This is a test paragraph", result)
        
        # Verify link conversion (relative to absolute)
        self.assertIn('HREF="http://test.example.com/relative/link"', result)
        
        # Verify image conversion
        self.assertIn("<IMG", result)  # IMG tag exists
        self.assertIn("EBD=", result)  # Has EBD reference
        self.assertIn("<EBDIMAGE", result)  # EBDIMAGE tag exists
        self.assertIn("MODE=", result)  # Has mode specified

if __name__ == '__main__':
    unittest.main()
