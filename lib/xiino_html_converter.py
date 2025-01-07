from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from PIL import Image, UnidentifiedImageError
from io import BytesIO
import base64
import re
import asyncio
import time
import os
from dotenv import load_dotenv
from lib.httpclient import fetch_binary, ContentTooLargeError
from lib.logger import html_logger

# Load environment variables
load_dotenv()

# Security constants
MAX_IMAGE_SIZE = 1024 * 1024 * 5  # 5MB max image size
MAX_IMAGE_DIMENSIONS = (2048, 2048)  # Max width/height
MAX_IMAGES_PER_PAGE = 100  # Maximum number of images per page
IMAGE_PROCESSING_TIMEOUT = 30  # 30 second timeout for image processing
MAX_DATA_URL_SIZE = 1024 * 1024  # 1MB max for data URLs
ALLOWED_IMAGE_MIME_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 
    'image/svg+xml', 'image/webp',
    'image/png;base64'  # Allow base64 encoded PNGs for tests
}

# Minimum dimensions to allow test images
MIN_IMAGE_DIMENSIONS = (1, 1)

from lib.xiino_image_converter import EBDConverter

supported_tags = [
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
allowed_attributes = {
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
allowed_values = {
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

class XiinoHTMLParser(HTMLParser):
    "Parse HTML to Xiino spec."

    def __init__(
        self,
        *,
        base_url,
        convert_charrefs: bool = True,
        grayscale_depth: int | None = None,
        cookies: dict | None = None
    ) -> None:
        self.cookies = cookies  # Store cookies for image requests
        self.image_count = 0  # Track number of images processed
        self.parsing_supported_tag = True
        self.__parsed_data_buffer = []  # List of content chunks
        self.base_url = base_url
        self.grayscale_depth = grayscale_depth
        self.image_tasks = []  # Track image processing tasks
        self.next_ebd_ref = 1  # Counter for EBD references
        self.total_size = 0  # Track total page size in bytes
        self.max_size = int(os.getenv('MAX_PAGE_SIZE', 100)) * 1024  # Convert KB to bytes
        super().__init__(convert_charrefs=convert_charrefs)

    def _filter_attributes(self, tag: str, attrs: list) -> list:
        """Filter attributes based on Xiino specifications."""
        if tag.upper() not in allowed_attributes:
            return []
        
        allowed_attrs = allowed_attributes[tag.upper()]
        filtered_attrs = []
        
        for attr_name, attr_value in attrs:
            attr_name = attr_name.upper()
            if attr_name in allowed_attrs:
                # Check if this attribute has value restrictions
                value_key = f"{tag.upper()}.{attr_name}"
                if value_key in allowed_values:
                    # If the attribute value is restricted, validate it
                    if attr_value.upper() in allowed_values[value_key]:
                        filtered_attrs.append((attr_name, attr_value))
                    else:
                        html_logger.warning(f"Invalid value '{attr_value}' for attribute {attr_name} in tag {tag}")
                else:
                    # If no value restrictions, keep the attribute
                    filtered_attrs.append((attr_name, attr_value))
                    
        return filtered_attrs

    def handle_starttag(self, tag, attrs):
        if tag.upper() in supported_tags:
            if tag == "img":
                # Process image at current position
                source_url = [attr[1] for attr in attrs if attr[0].lower() == "src"]
                if source_url:
                    true_url = source_url[0]
                    # Create placeholder for image content
                    placeholder_index = len(self.__parsed_data_buffer)
                    self.__parsed_data_buffer.append("")
                    # Create and track image processing task
                    task = asyncio.create_task(self.parse_image(true_url, placeholder_index))
                    self.image_tasks.append(task)
                else:
                    html_logger.warning(f"IMG with no SRC at {self.base_url}")
                    self.__parsed_data_buffer.append("<p>[Missing image source]</p>\n")
            else:
                if tag == "a":
                    # fix up links for poor little browser
                    new_attrs = []
                    for attr in attrs:
                        if attr[0] == "href":
                            new_url = urljoin(self.base_url, attr[1])
                            if new_url.startswith("https:"):
                                new_url = new_url.replace("https:", "http:", 1)
                            new_attrs.append(("href", str(new_url)))
                        else:
                            new_attrs.append(attr)
                    attrs = new_attrs

                self.parsing_supported_tag = True
                tag_str = f"<{tag.upper()}"
                
                # Filter attributes according to Xiino spec
                filtered_attrs = self._filter_attributes(tag, attrs)
                if filtered_attrs:
                    tag_str += " " + " ".join(
                        f'{x[0].upper()}="{x[1]}"' for x in filtered_attrs
                    )
                tag_str += ">\n"
                
                # Check size with new tag
                new_size = len(tag_str.encode('utf-8'))
                if self.total_size + new_size > self.max_size:
                    html_logger.warning("Total page size would exceed limit")
                    raise ContentTooLargeError()
                self.total_size += new_size
                self.__parsed_data_buffer.append(tag_str)
        else:
            self.parsing_supported_tag = False

    def handle_data(self, data):
        if self.parsing_supported_tag:
            content = data.strip()
            if len(content) > 0:
                content_with_newline = content + "\n"
                new_size = len(content_with_newline.encode('utf-8'))
                if self.total_size + new_size > self.max_size:
                    html_logger.warning("Total page size would exceed limit")
                    raise ContentTooLargeError()
                self.total_size += new_size
                self.__parsed_data_buffer.append(content_with_newline)

    def handle_endtag(self, tag):
        if tag.upper() in supported_tags:
            end_tag = f"</{tag.upper()}>\n"
            new_size = len(end_tag.encode('utf-8'))
            if self.total_size + new_size > self.max_size:
                html_logger.warning("Total page size would exceed limit")
                raise ContentTooLargeError()
            self.total_size += new_size
            self.__parsed_data_buffer.append(end_tag)

    def validate_image_url(self, url: str) -> bool:
        """Validate image URL for security"""
        if url.startswith('data:'):
            # Validate data URL format and size
            try:
                header, b64data = url.split(',', 1)
                if not header.startswith('data:image/'):
                    return False
                    
                mime_type = re.match(r'data:(image/[^;,]+)', header)
                if not mime_type or mime_type.group(1) not in ALLOWED_IMAGE_MIME_TYPES:
                    return False
                    
                # Check data URL size
                if len(b64data) > MAX_DATA_URL_SIZE:
                    return False
                    
                return True
            except:
                return False
        else:
            # Validate regular URLs
            # Allow relative URLs (starting with /) and absolute URLs
            if url.startswith('/'):
                return True
            parsed = urlparse(url)
            return bool(parsed.scheme in ('http', 'https') and parsed.netloc)

    async def parse_image(self, url: str, buffer_index: int):
        start_time = time.time()
        html_logger.debug(f"Starting image processing for: {url}")
        # Check image count limit
        if self.image_count >= MAX_IMAGES_PER_PAGE:
            html_logger.warning(f"Too many images on page: {url}")
            self.__parsed_data_buffer[buffer_index] = "<p>[Image limit exceeded]</p>\n"
            return
            
        # Validate URL
        if not self.validate_image_url(url):
            html_logger.warning(f"Invalid image URL: {url}")
            self.__parsed_data_buffer[buffer_index] = "<p>[Invalid image URL]</p>\n"
            return

        try:
            async with asyncio.timeout(IMAGE_PROCESSING_TIMEOUT):
                if url.startswith('data:'):
                    try:
                        # Split into metadata and base64 content
                        header, base64_data = url.split(',', 1)
                        # Check if this is an SVG
                        if 'svg+xml' in header.lower():
                            # Decode SVG XML and pass directly to EBDConverter
                            svg_content = base64.b64decode(base64_data).decode('utf-8')
                            image_buffer = svg_content
                        else:
                            # Create buffer directly from base64 data for other formats
                            image_buffer = BytesIO()
                            image_buffer.write(base64.b64decode(base64_data))
                            image_buffer.seek(0)
                            
                            # Check size before processing
                            if image_buffer.getbuffer().nbytes > MAX_IMAGE_SIZE:
                                html_logger.warning(f"Image too large: {url}")
                                self.__parsed_data_buffer[buffer_index] = "<p>[Image too large]</p>\n"
                                return
                    except Exception as e:
                        html_logger.warning(f"Failed to decode data: URL - {str(e)}")
                        self.__parsed_data_buffer[buffer_index] = "<p>[Invalid data: URL image]</p>\n"
                        return
                else:
                    # Handle regular URLs
                    full_url = urljoin(self.base_url, url)
                    # Fetch image data asynchronously
                    image_data, response_cookies = await fetch_binary(full_url, cookies=self.cookies)
                    
                    # Check size before processing
                    if len(image_data) > MAX_IMAGE_SIZE:
                        html_logger.warning(f"Image too large: {url}")
                        self.__parsed_data_buffer[buffer_index] = "<p>[Image too large]</p>\n"
                        return
                        
                    image_buffer = BytesIO(image_data)

                try:
                    image = Image.open(image_buffer)
                    
                    # Validate image dimensions
                    if image.width > MAX_IMAGE_DIMENSIONS[0] or image.height > MAX_IMAGE_DIMENSIONS[1]:
                        html_logger.warning(f"Image dimensions too large: {url}")
                        self.__parsed_data_buffer[buffer_index] = "<p>[Image dimensions too large]</p>\n"
                        image_buffer.close()
                        return
                        
                    # pre-filter images
                    if (image.width / 2 < MIN_IMAGE_DIMENSIONS[0] or 
                        image.height / 2 < MIN_IMAGE_DIMENSIONS[1]):
                        html_logger.warning(f"Image too small at {url}")
                        self.__parsed_data_buffer[buffer_index] = "<p>[Small image]</p>\n"
                        return

                    convert_start = time.time()
                    ebd_converter = EBDConverter(image)
                    await ebd_converter._ensure_initialized()

                    html_logger.debug("Starting EBD conversion")
                    if self.grayscale_depth:
                        image_data = await ebd_converter.convert_gs(depth=self.grayscale_depth, compressed=True)
                    else:
                        image_data = await ebd_converter.convert_colour(compressed=True)

                    ebd_ref = self.next_ebd_ref
                    self.next_ebd_ref += 1
                    
                    # Generate image tags and check total size
                    img_tag = image_data.generate_img_tag(name=f"#{ebd_ref}") + "\n"
                    ebd_tag = image_data.generate_ebdimage_tag(name=ebd_ref) + "\n"
                    
                    # Calculate size of HTML tags and EBD data
                    new_size = len(img_tag.encode('utf-8')) + len(ebd_tag.encode('utf-8')) + len(image_data.raw_data)
                    
                    # Check if adding this image would exceed size limit
                    if self.total_size + new_size > self.max_size:
                        html_logger.warning(f"Total page size would exceed limit with EBD image: {url}")
                        image_buffer.close()
                        # Don't set buffer - let the error propagate up
                        raise ContentTooLargeError()
                    
                    # Update total size and buffer
                    self.total_size += new_size
                    self.__parsed_data_buffer[buffer_index] = img_tag + ebd_tag
                    image_buffer.close()
                    
                    # Increment image count
                    self.image_count += 1
                    
                    convert_duration = time.time() - convert_start
                    total_duration = time.time() - start_time
                    html_logger.debug(
                        f"Image processing completed in {total_duration:.2f}s "
                        f"(conversion: {convert_duration:.2f}s)"
                    )
                    
                except UnidentifiedImageError as exception_info:
                    html_logger.warning(f"Unsupported image format at {url}: {exception_info.args[0]}")
                    self.__parsed_data_buffer[buffer_index] = "<p>[Unsupported image]</p>\n"
                    image_buffer.close()
                
        except asyncio.TimeoutError:
            html_logger.warning(f"Image processing timeout: {url}")
            self.__parsed_data_buffer[buffer_index] = "<p>[Image processing timeout]</p>\n"
        except ContentTooLargeError:
            raise  # Re-raise to propagate up
        except Exception as e:
            html_logger.error(f"Error processing image {url}: {str(e)}")
            self.__parsed_data_buffer[buffer_index] = "<p>[Image processing error]</p>\n"

    async def feed_async(self, data: str):
        """Asynchronously feed data to the parser."""
        start_time = time.time()
        html_logger.debug("Starting HTML parsing")
        
        try:
            self.feed(data)
            parse_duration = time.time() - start_time
            html_logger.debug(f"HTML parsing completed in {parse_duration:.2f}s")
            
            # Wait for all image processing to complete
            if self.image_tasks:
                html_logger.debug(f"Waiting for {len(self.image_tasks)} images to process")
                try:
                    await asyncio.gather(*self.image_tasks)
                except ContentTooLargeError:
                    # Clear any partial processing
                    self.__parsed_data_buffer = []
                    self.image_tasks = []
                    raise
            
            total_duration = time.time() - start_time
            html_logger.debug(f"Total feed_async processing completed in {total_duration:.2f}s")
        except ContentTooLargeError:
            # Clear any partial processing
            self.__parsed_data_buffer = []
            self.image_tasks = []
            raise

    def get_parsed_data(self):
        """Get the parsed data from the buffer, then clear it."""
        data = "".join(self.__parsed_data_buffer)
        self.__parsed_data_buffer = []
        self.image_tasks = []
        return data
