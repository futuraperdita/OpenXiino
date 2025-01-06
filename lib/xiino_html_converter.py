import os
import random
import asyncio
from html.parser import HTMLParser
from urllib.parse import urljoin
from PIL import Image, UnidentifiedImageError
from io import BytesIO
import base64

from lib.xiino_image_converter import EBDConverter
from lib.httpclient import fetch_binary
from lib.logger import html_logger

supported_tags = [
    "A", "ADDRESS", "AREA", "B", "BASE", "BASEFONT", "BLINK", "BLOCKQUOTE",
    "BODY", "BGCOLOR", "BR", "CLEAR", "CENTER", "CAPTION", "CITE", "CODE",
    "DD", "DIR", "DIV", "DL", "DT", "FONT", "FORM", "FRAME", "FRAMESET",
    "H1", "H2", "H3", "H4", "H5", "H6", "HR", "I", "IMG", "INPUT",
    "ISINDEX", "KBD", "LI", "MAP", "META", "MULTICOL", "NOBR", "NOFRAMES",
    "OL", "OPTION", "P", "PLAINTEXT", "PRE", "S", "SELECT", "SMALL",
    "STRIKE", "STRONG", "STYLE", "SUB", "SUP", "TABLE", "TITLE",
    "TD", "TH", "TR", "TT", "U", "UL", "VAR", "XMP",
]

class XiinoHTMLParser(HTMLParser):
    "Parse HTML to Xiino spec."

    def __init__(
        self,
        *,
        base_url,
        convert_charrefs: bool = True,
        grayscale_depth: int | None = None
    ) -> None:
        self.parsing_supported_tag = True
        self.__parsed_data_buffer = ""
        self.ebd_image_tags = []
        self.base_url = base_url
        self.grayscale_depth = grayscale_depth
        self.pending_images = []
        super().__init__(convert_charrefs=convert_charrefs)

    def handle_starttag(self, tag, attrs):
        if tag.upper() in supported_tags:
            if tag == "img":
                # Put EBD logic here
                source_url = [attr[1] for attr in attrs if attr[0].lower() == "src"]
                if source_url:
                    true_url = source_url[0]
                    self.pending_images.append(true_url)
                else:
                    html_logger.warning(f"IMG with no SRC at {self.base_url}")
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
                self.__parsed_data_buffer += f"<{tag.upper()}"
                if attrs:
                    self.__parsed_data_buffer += " " + " ".join(
                        f'{x[0].upper()}="{x[1]}"' for x in attrs
                    )
                self.__parsed_data_buffer += ">\n"
        else:
            self.parsing_supported_tag = False

    def handle_data(self, data):
        if self.parsing_supported_tag:
            self.__parsed_data_buffer += data.strip()
            if len(data) > 0:
                self.__parsed_data_buffer += "\n"

    def handle_endtag(self, tag):
        if tag.upper() in supported_tags:
            self.__parsed_data_buffer += f"</{tag.upper()}>\n"

    async def parse_image(self, url: str):
        if url.startswith('data:'):
            # Handle data: URLs
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
            except Exception as e:
                html_logger.warning(f"Failed to decode data: URL - {str(e)}")
                self.__parsed_data_buffer += "<p>[Invalid data: URL image]</p>"
                return
        else:
            # Handle regular URLs
            full_url = urljoin(self.base_url, url)
            # Fetch image data asynchronously
            image_data = await fetch_binary(full_url)
            image_buffer = BytesIO(image_data)

        try:
            image = Image.open(image_buffer)
        except UnidentifiedImageError as exception_info:
            html_logger.warning(f"Unsupported image format at {url}: {exception_info.args[0]}")
            self.__parsed_data_buffer += "<p>[Unsupported image]</p>"
            image_buffer.close()
            return

        # pre-filter images
        if image.width / 2 <= 1 or image.width / 2 <= 1:
            html_logger.warning(f"Image too small at {url}")
            self.__parsed_data_buffer += "<p>[Unsupported image]</p>"
            return

        ebd_converter = EBDConverter(image)

        if self.grayscale_depth:
            image_data = ebd_converter.convert_gs(depth=self.grayscale_depth, compressed=True)
        else:
            image_data = ebd_converter.convert_colour(compressed=True)

        ebd_ref = len(self.ebd_image_tags) + 1  # get next "slot"
        self.__parsed_data_buffer += (
            image_data.generate_img_tag(name=f"#{ebd_ref}") + "\n"
        )
        self.ebd_image_tags.append(image_data.generate_ebdimage_tag(name=ebd_ref))
        image_buffer.close()

    async def feed_async(self, data: str):
        """Asynchronously feed data to the parser."""
        self.feed(data)
        # Process any pending images
        for url in self.pending_images:
            await self.parse_image(url)
        self.pending_images = []

    def get_parsed_data(self):
        """Get the parsed data from the buffer, then clear it."""
        for tag in self.ebd_image_tags:
            self.__parsed_data_buffer += tag + "\n"
        data = self.__parsed_data_buffer
        self.__parsed_data_buffer = ""
        self.ebd_image_tags = []
        return data
