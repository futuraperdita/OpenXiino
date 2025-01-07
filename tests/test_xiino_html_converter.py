import pytest
from aioresponses import aioresponses, CallbackResult
from lib.xiino_html_converter import XiinoHTMLParser, ContentTooLargeError
from PIL import Image
import asyncio
from io import BytesIO
import os

@pytest.fixture
def base_url():
    return "http://test.example.com"

@pytest.fixture
def parser(base_url):
    return XiinoHTMLParser(base_url=base_url)

@pytest.fixture
def grayscale_parser(base_url):
    return XiinoHTMLParser(base_url=base_url, grayscale_depth=4)

@pytest.fixture
def mock_aiohttp():
    with aioresponses() as m:
        yield m

@pytest.mark.asyncio
async def test_svg_from_url(parser, mock_aiohttp, base_url):
    """Test that SVG content in BytesIO is correctly handled"""
    # Create a simple test SVG
    svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
    <svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
        <rect width="100" height="100" fill="black"/>
        <circle cx="50" cy="50" r="40" fill="white"/>
    </svg>'''
    
    # Mock the response for SVG request
    mock_aiohttp.get(
        f"{base_url}/test.svg",
        body=svg_content.encode('utf-8'),
        status=200,
        content_type="image/svg+xml"
    )

    test_html = f"""
    <html>
        <body>
            <img src="/test.svg" alt="Test SVG">
        </body>
    </html>
    """
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    # Verify SVG conversion
    assert "<IMG" in result  # IMG tag exists
    assert "EBD=" in result  # Has EBD reference
    assert "<EBDIMAGE" in result  # EBDIMAGE tag exists
    assert "MODE=" in result  # Has mode specified

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

@pytest.mark.asyncio
async def test_allowed_attributes(parser):
    """Test that allowed attributes are preserved while disallowed ones are filtered"""
    test_html = """
    <div align="center" nonexistent="value">Centered Text</div>
    <tr align="left" valign="top" style="color: red;">
        <td width="100" height="50" nonexistent="value">Cell Content</td>
    </tr>
    """
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    # Verify allowed attributes are preserved
    assert 'ALIGN="center"' in result
    assert 'ALIGN="left"' in result
    assert 'VALIGN="top"' in result
    assert 'WIDTH="100"' in result
    assert 'HEIGHT="50"' in result
    
    # Verify disallowed attributes are filtered out
    assert 'nonexistent=' not in result
    assert 'style=' not in result

@pytest.mark.asyncio
async def test_attribute_values(parser):
    """Test that allowed attribute values are preserved while disallowed ones are filtered"""
    test_html = """
    <div align="invalid">Invalid Align</div>
    <div align="center">Valid Center</div>
    <tr align="left" valign="invalid">
        <td align="right" valign="top">Valid Values</td>
    </tr>
    <ul type="disc">Valid List</ul>
    <ul type="invalid">Invalid List</ul>
    """
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    # Verify allowed values are preserved
    assert 'ALIGN="center"' in result
    assert 'ALIGN="left"' in result
    assert 'ALIGN="right"' in result
    assert 'VALIGN="top"' in result
    assert 'TYPE="disc"' in result
    
    # Verify disallowed values are filtered out
    assert 'ALIGN="invalid"' not in result
    assert 'VALIGN="invalid"' not in result
    assert 'TYPE="invalid"' not in result

@pytest.mark.asyncio
async def test_form_attributes(parser):
    """Test form-specific attributes and values"""
    test_html = """
    <form method="post" action="/submit" invalid="attr">
        <input type="text" name="username" maxlength="50">
        <input type="invalid" name="test">
        <input type="submit" value="Submit">
    </form>
    """
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    # Verify allowed form attributes and values
    assert 'METHOD="post"' in result
    assert 'ACTION="/submit"' in result
    assert 'TYPE="text"' in result
    assert 'NAME="username"' in result
    assert 'MAXLENGTH="50"' in result
    assert 'TYPE="submit"' in result
    
    # Verify disallowed attributes and values are filtered
    assert 'invalid=' not in result

@pytest.mark.asyncio
async def test_oversized_image(parser, mock_aiohttp, base_url):
    """Test handling of oversized images"""
    # Create an oversized image (6MB)
    large_data = b'0' * (6 * 1024 * 1024)
    
    mock_aiohttp.get(
        f"{base_url}/large.jpg",
        body=large_data,
        status=200,
        content_type="image/jpeg"
    )

    test_html = f"""
    <html><body><img src="/large.jpg" alt="Large Image"></body></html>
    """
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    assert "[Image too large]" in result

@pytest.mark.asyncio
async def test_image_limit_per_page(parser, mock_aiohttp, base_url):
    """Test maximum images per page limit"""
    # Create a small test image
    test_image = Image.new('RGB', (10, 10), color='black')
    image_buffer = BytesIO()
    test_image.save(image_buffer, format='PNG')
    image_data = image_buffer.getvalue()
    
    # Mock image response
    mock_aiohttp.get(
        f"{base_url}/test.jpg",
        body=image_data,
        status=200,
        content_type="image/jpeg"
    )

    # Create HTML with more than MAX_IMAGES_PER_PAGE images
    images_html = "".join([
        f'<img src="/test.jpg" alt="Test {i}">'
        for i in range(105)  # More than MAX_IMAGES_PER_PAGE (100)
    ])
    test_html = f"<html><body>{images_html}</body></html>"
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    assert "[Image limit exceeded]" in result

@pytest.mark.asyncio
async def test_grayscale_conversion(grayscale_parser, mock_aiohttp, base_url):
    """Test grayscale image conversion"""
    test_image = Image.new('RGB', (10, 10), color='black')
    image_buffer = BytesIO()
    test_image.save(image_buffer, format='PNG')
    image_data = image_buffer.getvalue()
    
    mock_aiohttp.get(
        f"{base_url}/test.jpg",
        body=image_data,
        status=200,
        content_type="image/jpeg"
    )

    test_html = """
    <html><body><img src="/test.jpg" alt="Test Image"></body></html>
    """
    
    await grayscale_parser.feed_async(test_html)
    result = grayscale_parser.get_parsed_data()
    
    assert "MODE=\"4\"" in result  # Mode 4 is compressed 4-bit grayscale

@pytest.mark.asyncio
async def test_invalid_image(parser, mock_aiohttp, base_url):
    """Test handling of invalid image data"""
    mock_aiohttp.get(
        f"{base_url}/invalid.jpg",
        body=b'not an image',
        status=200,
        content_type="image/jpeg"
    )

    test_html = """
    <html><body><img src="/invalid.jpg" alt="Invalid Image"></body></html>
    """
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    assert "[Image processing error]" in result

@pytest.mark.asyncio
async def test_concurrent_image_processing(parser, mock_aiohttp, base_url):
    """Test concurrent processing of multiple images"""
    test_image = Image.new('RGB', (10, 10), color='black')
    image_buffer = BytesIO()
    test_image.save(image_buffer, format='PNG')
    image_data = image_buffer.getvalue()
    
    # Mock multiple different image URLs
    for i in range(5):
        mock_aiohttp.get(
            f"{base_url}/test{i}.jpg",
            body=image_data,
            status=200,
            content_type="image/jpeg"
        )

    # Create HTML with multiple images
    images_html = "".join([
        f'<img src="/test{i}.jpg" alt="Test {i}">'
        for i in range(5)
    ])
    test_html = f"<html><body>{images_html}</body></html>"
    
    start_time = asyncio.get_event_loop().time()
    await parser.feed_async(test_html)
    end_time = asyncio.get_event_loop().time()
    
    result = parser.get_parsed_data()
    
    # Verify all images were processed
    assert result.count("<IMG") == 5
    assert result.count("<EBDIMAGE") == 5
    
    # Verify concurrent processing (should take less time than sequential)
    assert end_time - start_time < 1.0  # Should be much faster than 5 * single image time

@pytest.mark.asyncio
async def test_timeout_handling(parser, mock_aiohttp, base_url):
    """Test handling of image processing timeouts"""
    async def delayed_response(*args, **kwargs):
        # Create a valid test image
        test_image = Image.new('RGB', (10, 10), color='black')
        image_buffer = BytesIO()
        test_image.save(image_buffer, format='PNG')
        image_data = image_buffer.getvalue()
        
        await asyncio.sleep(2)  # Long enough to trigger timeout
        return CallbackResult(
            status=200,
            body=image_data,
            content_type='image/png'
        )

    mock_aiohttp.get(
        f"{base_url}/slow.jpg",
        callback=delayed_response
    )

    test_html = """
    <html><body><img src="/slow.jpg" alt="Slow Image"></body></html>
    """
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    assert "[Image processing timeout]" in result

@pytest.mark.asyncio
async def test_cleanup_behavior(parser, mock_aiohttp, base_url):
    """Test proper cleanup of resources"""
    test_image = Image.new('RGB', (10, 10), color='black')
    image_buffer = BytesIO()
    test_image.save(image_buffer, format='PNG')
    image_data = image_buffer.getvalue()
    
    mock_aiohttp.get(
        f"{base_url}/test.jpg",
        body=image_data,
        status=200,
        content_type="image/jpeg"
    )

    test_html = """
    <html><body><img src="/test.jpg" alt="Test Image"></body></html>
    """
    
    await parser.feed_async(test_html)
    _ = parser.get_parsed_data()  # This should mark cleanup as required
    
    assert parser._cleanup_required == True
    await parser.cleanup()
    assert parser._cleanup_required == False
    assert len(parser.image_tasks) == 0
    assert len(parser._XiinoHTMLParser__parsed_data_buffer) == 0

@pytest.mark.asyncio
async def test_page_size_limit(parser, mock_aiohttp, base_url):
    """Test handling of total page size limits"""
    # Set a very small page size limit for testing
    os.environ['MAX_PAGE_SIZE'] = '1'  # 1KB limit
    parser.max_size = 1024  # 1KB
    
    # Create content that will exceed the limit
    large_content = "x" * 2000  # 2KB of content
    test_html = f"""
    <html><body><p>{large_content}</p></body></html>
    """
    
    with pytest.raises(ContentTooLargeError):
        await parser.feed_async(test_html)
