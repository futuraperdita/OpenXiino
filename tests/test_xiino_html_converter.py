import pytest
from aioresponses import aioresponses
from lib.xiino_html_converter import XiinoHTMLParser
from PIL import Image
from io import BytesIO

@pytest.fixture
def base_url():
    return "http://test.example.com"

@pytest.fixture
def parser(base_url):
    return XiinoHTMLParser(base_url=base_url)

@pytest.fixture
def mock_aiohttp():
    with aioresponses() as m:
        yield m

@pytest.mark.asyncio
async def test_data_url_image(parser):
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
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    # Verify image conversion
    assert "<IMG" in result  # IMG tag exists
    assert "EBD=" in result  # Has EBD reference
    assert "<EBDIMAGE" in result  # EBDIMAGE tag exists
    assert "MODE=" in result  # Has mode specified

@pytest.mark.asyncio
async def test_html_parsing(parser, mock_aiohttp, base_url):
    """Test that HTML is correctly parsed and converted to Xiino format"""
    # Create a test image
    test_image = Image.new('RGB', (10, 10), color='black')
    image_buffer = BytesIO()
    test_image.save(image_buffer, format='PNG')
    image_data = image_buffer.getvalue()
    image_buffer.close()

    # Mock the response for any image requests
    mock_aiohttp.get(
        f"{base_url}/test.jpg",
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
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    # Verify basic HTML conversion
    assert "<H1>" in result
    assert "Test Page" in result
    assert "<P>" in result
    assert "This is a test paragraph" in result
    
    # Verify link conversion (relative to absolute)
    assert f'HREF="{base_url}/relative/link"' in result
    
    # Verify image conversion
    assert "<IMG" in result  # IMG tag exists
    assert "EBD=" in result  # Has EBD reference
    assert "<EBDIMAGE" in result  # EBDIMAGE tag exists
    assert "MODE=" in result  # Has mode specified
