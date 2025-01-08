"""Classes for converting HTML to Xiino format."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from PIL import Image, UnidentifiedImageError
from io import BytesIO
import base64
import re
import asyncio
import time
import os
from typing import Union, List, Optional, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv
from lib.httpclient import fetch_binary, ContentTooLargeError
from lib.logger import html_logger
from lib.xiino_image_converter import EBDConverter

# Load environment variables
load_dotenv()

# Image processing configuration from environment
MAX_IMAGE_SIZE = int(os.getenv('IMAGE_MAX_SIZE', '5')) * 1024 * 1024  # Convert MB to bytes
MAX_IMAGE_DIMENSION = int(os.getenv('IMAGE_MAX_DIMENSION', '2048'))
MAX_IMAGE_DIMENSIONS = (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION)  # Max width/height
MAX_IMAGES_PER_PAGE = int(os.getenv('IMAGE_MAX_PER_PAGE', '100'))
IMAGE_PROCESSING_TIMEOUT = int(os.getenv('IMAGE_PROCESSING_TIMEOUT', '30'))
MAX_DATA_URL_SIZE = int(os.getenv('IMAGE_MAX_DATA_URL_SIZE', '1')) * 1024 * 1024  # Convert MB to bytes
ALLOWED_IMAGE_MIME_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 
    'image/svg+xml', 'image/webp',
    'image/png;base64'  # Allow base64 encoded PNGs for tests
}

# Supported tags by the proxy
SUPPORTED_TAGS = [
    "A", "ADDRESS", "AREA", "B", "BASE", "BASEFONT", "BLINK", "BLOCKQUOTE",
    "BODY", "BGCOLOR", "BR", "CLEAR", "CENTER", "CAPTION", "CITE", "CODE",
    "DD", "DIR", "DIV", "DL", "DT", "FONT", "FORM", "FRAME", "FRAMESET",
    "H1", "H2", "H3", "H4", "H5", "H6", "HR", "I", "IMG", "INPUT",
    "ISINDEX", "KBD", "LI", "MAP", "META", "MULTICOL", "NOBR", "NOFRAMES",
    "OL", "OPTION", "P", "PLAINTEXT", "PRE", "S", "SELECT", "SMALL",
    "STRIKE", "STRONG", "STYLE", "SUB", "SUP", "TABLE", "TITLE",
    "TD", "TH", "TR", "TT", "U", "UL", "VAR", "XMP", "HEAD"
]

# Define allowed attributes and their values per tag based on Xiino spec
SUPPORTED_ATTRIBUTES = {
    "A": {"HREF", "NAME", "TARGET", "ONCLICK"},
    "AREA": {"COORDS", "HREF", "SHAPE", "TARGET", "NOHREF"},
    "BASE": {"HREF"},
    "BASEFONT": {"SIZE", "COLOR"},
    "BODY": {"BGCOLOR", "TEXT", "LINK", "VLINK", "ALINK", "ONLOAD", "ONUNLOAD", "EBDWIDTH", "EBDHEIGHT"},
    "BR": {"CLEAR"},  # Values: NONE, LEFT, RIGHT, ALL
    "DIV": {"ALIGN"},  # Values: LEFT, CENTER, RIGHT
    "DL": {"COMPACT"},
    "FORM": {"LOCAL", "METHOD", "ACTION", "ONRESET", "ONSUBMIT"},
    "FRAME": {"SRC", "NAME"},
    "FRAMESET": {"COLS", "ROWS"},
    "H1": {"ALIGN"},
    "H2": {"ALIGN"},
    "H3": {"ALIGN"},
    "H4": {"ALIGN"},
    "H5": {"ALIGN"},
    "H6": {"ALIGN"},
    "HR": {"SIZE", "WIDTH", "NOSHADE", "ALIGN"},  # ALIGN values: LEFT, CENTER, RIGHT
    "IMG": {"WIDTH", "HEIGHT", "BORDER", "HSPACE", "VSPACE", "ALIGN", "ISMAP", "USEMAP", "ALT", "SRC"},
    "INPUT": {"NAME", "VALUE", "TYPE", "MAXLENGTH", "SIZE", "DISABLED", "CHECKED", "ONBLUR", "ONCHANGE", "ONCLICK", "ONFOCUS", "ONSCAN", "ONSELECT"},
    "LI": {"TYPE", "VALUE"},
    "MAP": {"NAME"},
    "META": {"CONTENT", "HTTP-EQUIV", "NAME"},
    "OL": {"START", "TYPE"},
    "OPTION": {"VALUE", "SELECTED"},
    "P": {"ALIGN"},
    "SCRIPT": {"LANGUAGE"},
    "SELECT": {"MULTIPLE", "NAME", "ONCHANGE"},
    "TABLE": {"BORDER", "ALIGN", "BGCOLOR", "CELLPADDING", "CELLSPACING"},
    "TD": {"COLSPAN", "ROWSPAN", "WIDTH", "HEIGHT", "NOWRAP", "ALIGN", "VALIGN", "BGCOLOR", "TEXTAREA", "NAME", "DISABLED"},
    "TH": {"COLSPAN", "ROWSPAN", "WIDTH", "HEIGHT", "NOWRAP", "ALIGN", "VALIGN", "BGCOLOR", "TITLE"},
    "TR": {"ALIGN", "VALIGN", "BGCOLOR"},
    "UL": {"TYPE"},
}

# Define allowed values for specific attributes
ALLOWED_ATTRIBUTE_VALUES = {
    "BR.CLEAR": {"NONE", "LEFT", "RIGHT", "ALL"},
    "DIV.ALIGN": {"LEFT", "CENTER", "RIGHT"},
    "HR.ALIGN": {"LEFT", "CENTER", "RIGHT"},
    "IMG.ALIGN": {"LEFT", "RIGHT", "TOP", "ABSMIDDLE", "ABSBOTTOM", "TEXTTOP", "MIDDLE", "BASELINE", "BOTTOM"},
    "INPUT.TYPE": {"SUBMIT", "RESET", "IMAGE", "BUTTON", "RADIO", "CHECKBOX", "HIDDEN", "PASSWORD", "TEXT"},
    "LI.TYPE": {"1", "A", "a", "I", "i", "DISC", "CIRCLE", "SQUARE"},
    "OL.TYPE": {"1", "A", "a", "I", "i"},
    "TD.ALIGN": {"LEFT", "CENTER", "RIGHT"},
    "TD.VALIGN": {"TOP", "BOTTOM", "MIDDLE", "BASELINE"},
    "TH.ALIGN": {"LEFT", "CENTER", "RIGHT"},
    "TH.VALIGN": {"TOP", "BOTTOM", "MIDDLE", "BASELINE"},
    "TR.ALIGN": {"LEFT", "CENTER", "RIGHT"},
    "TR.VALIGN": {"TOP", "BOTTOM", "MIDDLE", "BASELINE"},
    "UL.TYPE": {"DISC", "CIRCLE", "SQUARE"},
    "FORM.METHOD": {"GET", "POST"},
    "AREA.SHAPE": {"CIRCLE", "POLY", "POLYGON", "RECT"},
}

# Minimum dimensions to allow test images
MIN_IMAGE_DIMENSIONS = (1, 1)

@dataclass
class ImageTask:
    """Represents an image processing task"""
    url: str
    buffer_index: int
    task: asyncio.Task

class XiinoHTMLParser(HTMLParser):
    """Parse HTML to Xiino spec with proper async support."""

    def __init__(
        self,
        *,
        base_url: str,
        convert_charrefs: bool = True,
        grayscale_depth: Optional[int] = None,
        cookies: Optional[Dict[str, str]] = None
    ) -> None:
        super().__init__(convert_charrefs=convert_charrefs)
        self.cookies = cookies or {}
        self.image_count = 0
        self.parsing_supported_tag = True
        self.__parsed_data_buffer: List[str] = []
        self.base_url = base_url
        self.grayscale_depth = grayscale_depth
        self.image_tasks: List[ImageTask] = []
        self.next_ebd_ref = 1
        self.total_size = 0
        self.max_size = int(os.getenv('HTTP_MAX_PAGE_SIZE', 512)) * 1024  # Convert KB to bytes
        self._cleanup_required = False

    async def cleanup(self) -> None:
        """Clean up resources"""
        if self._cleanup_required:
            # Cancel any pending image tasks
            for img_task in self.image_tasks:
                if not img_task.task.done():
                    img_task.task.cancel()
                    try:
                        await img_task.task
                    except asyncio.CancelledError:
                        pass
            
            # Clear buffers
            self.__parsed_data_buffer.clear()
            self.image_tasks.clear()
            self._cleanup_required = False

    def _filter_attributes(self, tag: str, attrs: List[tuple]) -> List[tuple]:
        """Filter attributes based on Xiino specifications."""
        if tag.upper() not in SUPPORTED_ATTRIBUTES:
            return []
        
        allowed_attrs = SUPPORTED_ATTRIBUTES[tag.upper()]
        filtered_attrs = []
        
        for attr_name, attr_value in attrs:
            attr_name = attr_name.upper()
            if attr_name in allowed_attrs:
                value_key = f"{tag.upper()}.{attr_name}"
                if value_key in ALLOWED_ATTRIBUTE_VALUES:
                    if attr_value.upper() in ALLOWED_ATTRIBUTE_VALUES[value_key]:
                        filtered_attrs.append((attr_name, attr_value))
                    else:
                        html_logger.warning(f"Invalid value '{attr_value}' for attribute {attr_name} in tag {tag}")
                else:
                    filtered_attrs.append((attr_name, attr_value))
                    
        return filtered_attrs

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        """Handle HTML start tags with proper error handling"""
        try:
            if tag.upper() in SUPPORTED_TAGS:
                if tag == "img":
                    self._handle_img_tag(attrs)
                else:
                    self._handle_regular_tag(tag, attrs)
            else:
                self.parsing_supported_tag = False
        except Exception as e:
            html_logger.error(f"Error handling start tag {tag}: {str(e)}")
            raise

    def _handle_img_tag(self, attrs: List[tuple]) -> None:
        """Handle IMG tag processing"""
        source_url = next((attr[1] for attr in attrs if attr[0].lower() == "src"), None)
        if source_url:
            if self.image_count >= MAX_IMAGES_PER_PAGE:
                html_logger.warning("Too many images on page")
                self.__parsed_data_buffer.append("<p>[Image limit exceeded]</p>\n")
                return

            placeholder_index = len(self.__parsed_data_buffer)
            self.__parsed_data_buffer.append("")
            
            # Create and track image processing task
            task = asyncio.create_task(self.parse_image(source_url, placeholder_index))
            self.image_tasks.append(ImageTask(source_url, placeholder_index, task))
            self._cleanup_required = True
            self.image_count += 1
        else:
            html_logger.warning(f"IMG with no SRC at {self.base_url}")
            self.__parsed_data_buffer.append("<p>[Missing image source]</p>\n")

    def _handle_regular_tag(self, tag: str, attrs: List[tuple]) -> None:
        """Handle non-IMG tag processing"""
        if tag == "a":
            attrs = self._fix_link_urls(attrs)

        self.parsing_supported_tag = True
        tag_str = self._build_tag_string(tag, attrs)
        
        new_size = len(tag_str.encode('utf-8'))
        if self.total_size + new_size > self.max_size:
            html_logger.warning("Total page size would exceed limit")
            raise ContentTooLargeError()
            
        self.total_size += new_size
        self.__parsed_data_buffer.append(tag_str)

    def _fix_link_urls(self, attrs: List[tuple]) -> List[tuple]:
        """Fix URLs in link tags"""
        new_attrs = []
        for attr_name, attr_value in attrs:
            if attr_name == "href":
                new_url = urljoin(self.base_url, attr_value)
                if new_url.startswith("https:"):
                    new_url = new_url.replace("https:", "http:", 1)
                new_attrs.append(("href", str(new_url)))
            else:
                new_attrs.append((attr_name, attr_value))
        return new_attrs

    def _build_tag_string(self, tag: str, attrs: List[tuple]) -> str:
        """Build HTML tag string with attributes"""
        tag_str = f"<{tag.upper()}"
        filtered_attrs = self._filter_attributes(tag, attrs)
        if filtered_attrs:
            tag_str += " " + " ".join(
                f'{x[0].upper()}="{x[1]}"' for x in filtered_attrs
            )
        return tag_str + ">\n"

    def handle_data(self, data: str) -> None:
        """Handle text content"""
        if self.parsing_supported_tag:
            content = data.strip()
            if content:
                content_with_newline = content + "\n"
                new_size = len(content_with_newline.encode('utf-8'))
                if self.total_size + new_size > self.max_size:
                    html_logger.warning("Total page size would exceed limit")
                    raise ContentTooLargeError()
                self.total_size += new_size
                self.__parsed_data_buffer.append(content_with_newline)

    def handle_endtag(self, tag: str) -> None:
        """Handle HTML end tags"""
        if tag.upper() in SUPPORTED_TAGS:
            end_tag = f"</{tag.upper()}>\n"
            new_size = len(end_tag.encode('utf-8'))
            if self.total_size + new_size > self.max_size:
                html_logger.warning("Total page size would exceed limit")
                raise ContentTooLargeError()
            self.total_size += new_size
            self.__parsed_data_buffer.append(end_tag)

    def validate_image_url(self, url: str) -> bool:
        """Validate image URL for security"""
        html_logger.debug(f"Validating image URL: {url[:100]}...")
        if url.startswith('data:'):
            try:
                header, b64data = url.split(',', 1)
                if not header.startswith('data:image/'):
                    html_logger.debug("Invalid data URL: not an image")
                    return False
                    
                mime_type = re.match(r'data:(image/[^;,]+)', header)
                if not mime_type or mime_type.group(1) not in ALLOWED_IMAGE_MIME_TYPES:
                    html_logger.debug(f"Invalid data URL: mime type {mime_type.group(1) if mime_type else 'unknown'} not allowed")
                    return False
                    
                if len(b64data) > MAX_DATA_URL_SIZE:
                    html_logger.debug(f"Data URL too large: {len(b64data)} bytes")
                    return False
                    
                html_logger.debug(f"Valid data URL with mime type: {mime_type.group(1) if mime_type else 'unknown'}")
                return True
            except Exception as e:
                html_logger.debug(f"Data URL parsing failed: {str(e)}")
                return False
        else:
            if url.startswith('/'):
                html_logger.debug("Relative URL (starts with /)")
                return True
            parsed = urlparse(url)
            is_valid = bool(parsed.scheme in ('http', 'https') and parsed.netloc)
            html_logger.debug(f"URL validation result: scheme={parsed.scheme}, netloc={parsed.netloc}, valid={is_valid}")
            return is_valid

    async def parse_image(self, url: str, buffer_index: int) -> None:
        """Process a single image asynchronously"""
        start_time = time.time()
        html_logger.debug(f"Starting image processing for: {url}")
        
        if not self.validate_image_url(url):
            html_logger.warning(f"Invalid image URL: {url}")
            self.__parsed_data_buffer[buffer_index] = "<p>[Invalid image URL]</p>\n"
            return

        try:
            async with asyncio.timeout(IMAGE_PROCESSING_TIMEOUT):
                await self._process_image(url, buffer_index, start_time)
                
        except asyncio.TimeoutError:
            html_logger.warning(f"Image processing timeout: {url}")
            self.__parsed_data_buffer[buffer_index] = "<p>[Image processing timeout]</p>\n"
        except ContentTooLargeError:
            html_logger.warning(f"Content too large: {url}")
            self.__parsed_data_buffer[buffer_index] = "<p>[Image too large]</p>\n"
        except Exception as e:
            html_logger.error(f"Error processing image {url}: {str(e)}")
            self.__parsed_data_buffer[buffer_index] = "<p>[Image processing error]</p>\n"

    async def _process_image(self, url: str, buffer_index: int, start_time: float) -> None:
        """Internal image processing logic"""
        try:
            image_buffer = await self._get_image_buffer(url)
            if isinstance(image_buffer, str):
                is_svg = True
                svg_content = image_buffer
            else:
                is_svg = await self._check_svg_content(image_buffer)
                
            converter = await self._create_converter(image_buffer, is_svg)
            ebd_data = await self._convert_image(converter)
            await self._handle_converted_image(ebd_data, url, buffer_index, start_time)
            
        except Exception as e:
            html_logger.error(f"Image processing failed: {str(e)}")
            raise

    async def _get_image_buffer(self, url: str) -> Union[str, BytesIO]:
        """Get image buffer from URL or data URL"""
        if url.startswith('data:'):
            return await self._handle_data_url(url)
        else:
            return await self._fetch_image(url)

    async def _handle_data_url(self, url: str) -> Union[str, BytesIO]:
        """Handle data URL image content"""
        header, base64_data = url.split(',', 1)
        html_logger.debug(f"Processing data URL with header: {header}")
        if 'svg+xml' in header.lower():
            html_logger.debug("Detected SVG data URL")
            return base64.b64decode(base64_data).decode('utf-8')
        else:
            html_logger.debug("Processing binary data URL")
            buffer = BytesIO(base64.b64decode(base64_data))
            size = buffer.getbuffer().nbytes
            html_logger.debug(f"Decoded data URL size: {size} bytes")
            if size > MAX_IMAGE_SIZE:
                html_logger.debug(f"Data URL content exceeds max size: {size} > {MAX_IMAGE_SIZE}")
                raise ContentTooLargeError()
            return buffer

    async def _fetch_image(self, url: str) -> BytesIO:
        """Fetch image from URL"""
        full_url = urljoin(self.base_url, url)
        html_logger.debug(f"Fetching image from: {full_url}")
        image_data, _ = await fetch_binary(full_url, cookies=self.cookies)
        
        size = len(image_data)
        html_logger.debug(f"Fetched image size: {size} bytes")
        if size > MAX_IMAGE_SIZE:
            html_logger.debug(f"Fetched image exceeds max size: {size} > {MAX_IMAGE_SIZE}")
            raise ContentTooLargeError()
            
        return BytesIO(image_data)

    async def _check_svg_content(self, buffer: BytesIO) -> bool:
        """Check if content is SVG"""
        peek = buffer.read(1000).decode('utf-8', errors='ignore')
        buffer.seek(0)
        return '<svg' in peek.lower()

    async def _create_converter(self, buffer: Union[str, BytesIO], is_svg: bool) -> EBDConverter:
        """Create appropriate converter for image type"""
        html_logger.debug(f"Creating converter for {'SVG' if is_svg else 'raster'} image")
        if is_svg:
            if isinstance(buffer, BytesIO):
                svg_content = buffer.read().decode('utf-8')
                buffer.seek(0)
            else:
                svg_content = buffer
            return EBDConverter(svg_content)
        else:
            image = Image.open(buffer)
            html_logger.debug(f"Opened image: format={image.format}, mode={image.mode}, size={image.width}x{image.height}")
            if not self._validate_image_dimensions(image):
                raise ValueError("Invalid image dimensions")
            return EBDConverter(image)

    def _validate_image_dimensions(self, image: Image.Image) -> bool:
        """Validate image dimensions"""
        if (image.width > MAX_IMAGE_DIMENSIONS[0] or 
            image.height > MAX_IMAGE_DIMENSIONS[1] or
            image.width / 2 < MIN_IMAGE_DIMENSIONS[0] or 
            image.height / 2 < MIN_IMAGE_DIMENSIONS[1]):
            return False
        return True

    async def _convert_image(self, converter: EBDConverter) -> Any:
        """Convert image to EBD format"""
        html_logger.debug(f"Converting image to {'grayscale' if self.grayscale_depth else 'color'} format")
        if self.grayscale_depth:
            html_logger.debug(f"Using {self.grayscale_depth}-bit grayscale depth")
            return await converter.convert_gs(depth=self.grayscale_depth, compressed=True)
        else:
            return await converter.convert_colour(compressed=True)

    async def _handle_converted_image(self, ebd_data: Any, url: str, buffer_index: int, start_time: float) -> None:
        """Handle converted image data"""
        ebd_ref = self.next_ebd_ref
        self.next_ebd_ref += 1
        
        html_logger.debug(f"Generating tags for converted image: mode={ebd_data.mode}, size={ebd_data.width}x{ebd_data.height}")
        img_tag = ebd_data.generate_img_tag(name=f"#{ebd_ref}") + "\n"
        ebd_tag = ebd_data.generate_ebdimage_tag(name=ebd_ref) + "\n"
        
        new_size = len(img_tag.encode('utf-8')) + len(ebd_tag.encode('utf-8')) + len(ebd_data.raw_data)
        if self.total_size + new_size > self.max_size:
            raise ContentTooLargeError()
        
        self.total_size += new_size
        self.__parsed_data_buffer[buffer_index] = img_tag + ebd_tag
        
        html_logger.debug(
            f"Image processing completed in {time.time() - start_time:.2f}s"
        )

    async def feed_async(self, data: str) -> None:
        """Asynchronously feed data to the parser."""
        start_time = time.time()
        html_logger.debug("Starting HTML parsing")
        
        try:
            self.feed(data)
            parse_duration = time.time() - start_time
            html_logger.debug(f"HTML parsing completed in {parse_duration:.2f}s")
            
            if self.image_tasks:
                html_logger.debug(f"Processing {len(self.image_tasks)} images")
                try:
                    await asyncio.gather(*(task.task for task in self.image_tasks))
                except ContentTooLargeError:
                    await self.cleanup()
                    raise
            
            total_duration = time.time() - start_time
            html_logger.debug(f"Total processing completed in {total_duration:.2f}s")
        except Exception:
            await self.cleanup()
            raise

    def get_parsed_data(self) -> str:
        """Get the parsed data and clean up."""
        try:
            return "".join(self.__parsed_data_buffer)
        finally:
            self._cleanup_required = True
