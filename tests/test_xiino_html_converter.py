import unittest
import responses
from lib.xiino_html_converter import XiinoHTMLParser

class TestXiinoHTMLParser(unittest.TestCase):
    def setUp(self):
        self.base_url = "http://test.example.com"
        self.parser = XiinoHTMLParser(base_url=self.base_url)

    @responses.activate
    def test_html_parsing(self):
        """Test that HTML is correctly parsed and converted to Xiino format"""
        # Mock the response for any image requests
        responses.add(
            responses.GET,
            "http://test.example.com/test.jpg",
            body=b"fake_image_data",
            status=200,
            content_type="image/jpeg"
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
        self.assertIn("<H1 >", result)
        self.assertIn("Test Page", result)
        self.assertIn("<P >", result)
        self.assertIn("This is a test paragraph", result)
        
        # Verify link conversion (relative to absolute)
        self.assertIn('HREF="http://test.example.com/relative/link"', result)

if __name__ == '__main__':
    unittest.main()
