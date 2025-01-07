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
    assert 'TYPE="invalid"' not in result

@pytest.mark.asyncio
async def test_table_attributes(parser):
    """Test table-specific attributes and values"""
    test_html = """
    <table border="1" cellpadding="5" invalid="attr">
        <tr align="center" valign="middle">
            <th align="left" valign="top">Header</th>
            <td align="right" valign="bottom">Cell</td>
        </tr>
    </table>
    """
    
    await parser.feed_async(test_html)
    result = parser.get_parsed_data()
    
    # Verify allowed table attributes and values
    assert 'BORDER="1"' in result
    assert 'CELLPADDING="5"' in result
    assert 'ALIGN="center"' in result
    assert 'VALIGN="middle"' in result
    assert 'ALIGN="left"' in result
    assert 'VALIGN="top"' in result
    assert 'ALIGN="right"' in result
    assert 'VALIGN="bottom"' in result
    
    # Verify disallowed attributes are filtered
    assert 'invalid=' not in result
