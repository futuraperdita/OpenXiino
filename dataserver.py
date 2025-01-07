import os
import re
import asyncio
import mimetypes
from aiohttp import web
from dotenv import load_dotenv
from urllib.parse import urlparse
import time
from lib.xiino_html_converter import XiinoHTMLParser
from lib.controllers.page_controller import PageController
from lib.logger import setup_logging, server_logger
from lib.cookie_manager import CookieManager
from lib.httpclient import fetch, fetch_binary, ContentTooLargeError
from lib.xiino_image_converter import EBDConverter

# Load environment variables and setup logging
load_dotenv()
setup_logging()

# Security constants
MAX_REQUEST_SIZE = 1024 * 1024 * 10  # 10MB max request size
MAX_REQUESTS_PER_MIN = 60  # Rate limit per IP
REQUEST_TRACKING = {}  # Track requests per IP

def iso8859(string: str) -> bytes:
    "Shorthand to convert a string to iso-8859"
    return bytes(string, encoding="iso-8859-1")

class XiinoServer:
    """Main server class handling Xiino browser requests"""
    
    COLOUR_DEPTH_REGEX = re.compile(r"\/c([0-9]*)\/")
    GSCALE_DEPTH_REGEX = re.compile(r"\/g([0-9]*)\/")
    SCREEN_WIDTH_REGEX = re.compile(r"\/w([0-9]*)\/")
    TXT_ENCODING_REGEX = re.compile(r"\/[de]{1,2}([a-zA-Z0-9-]*)\/")
    
    def __init__(self):
        self.page_controller = PageController()
        self.next_ebd_ref = 1  # Counter for EBD references
        
    def check_rate_limit(self, ip: str) -> bool:
        """Check if request exceeds rate limit"""
        current_time = time.time()
        
        # Clean old entries
        REQUEST_TRACKING[ip] = [t for t in REQUEST_TRACKING.get(ip, [])
                              if current_time - t < 60]
        
        # Check rate limit
        if len(REQUEST_TRACKING.get(ip, [])) >= MAX_REQUESTS_PER_MIN:
            return True
            
        # Add new request
        if ip not in REQUEST_TRACKING:
            REQUEST_TRACKING[ip] = []
        REQUEST_TRACKING[ip].append(current_time)
        return False

    def validate_url(self, url: str) -> bool:
        """Validate URL for security"""
        parsed = urlparse(url)
        if not parsed.scheme == 'http':
            return False
        if not parsed.netloc:
            return False
        return True

    async def handle_xiino_request(self, request: web.Request) -> web.Response:
        """Main request handler for Xiino browser requests"""
        request_start = time.time()
        server_logger.debug(f"Starting request handling for {request.path_qs}")
        
        # Check rate limit
        if self.check_rate_limit(request.remote):
            raise web.HTTPTooManyRequests(text="Too many requests")
            
        # Get URL from query string
        url = request.query.get('url')
        if not url:
            return await self.render_page("not-found")

        # Handle xiino URLs and validate
        if not self.validate_url(url):
            return await self.render_page("not-found")

        parsed_url = urlparse(url)
        if parsed_url.netloc.endswith('.xiino'):
            # Handle internal pages
            return await self.handle_internal_page(parsed_url, request)
        else:
            # Handle external URLs
            return await self.handle_external_url(url, request)

    async def handle_internal_page(self, parsed_url: urlparse, request: web.Request) -> web.Response:
        """Handle internal .xiino pages"""
        page = parsed_url.netloc.split('.')[0]
        
        if page == 'about':
            page = 'home'
            return await self.render_page(page)
        elif page == 'device':
            # Get device info
            request_info = self.get_device_info(request)
            return await self.render_page(page, request_info)
        else:
            return await self.render_page(page)

    def get_device_info(self, request: web.Request) -> dict:
        """Extract device info from request path"""
        path = request.path_qs
        return {
            "color_depth": self._get_regex_group(self.COLOUR_DEPTH_REGEX, path),
            "grayscale_depth": self._get_regex_group(self.GSCALE_DEPTH_REGEX, path),
            "screen_width": self._get_regex_group(self.SCREEN_WIDTH_REGEX, path),
            "encoding": self._get_regex_group(self.TXT_ENCODING_REGEX, path),
            "headers": str(request.headers)
        }

    def _get_regex_group(self, regex: re.Pattern, text: str) -> str:
        """Helper to safely get regex group"""
        match = regex.search(text)
        return match.group(1) if match else None

    async def handle_external_url(self, url: str, request: web.Request) -> web.Response:
        """Handle external URL requests"""
        try:
            # Check if this is a direct image request
            parsed_url = urlparse(url)
            mime_type, _ = mimetypes.guess_type(parsed_url.path)
            is_image = mime_type and mime_type.startswith('image/')
            is_svg = (mime_type == 'image/svg+xml' or parsed_url.path.lower().endswith('.svg'))

            # Get cookies for request
            request_cookies = CookieManager.prepare_request_cookies(
                request.headers.get('Cookie'),
                url
            )

            if is_image:
                return await self.handle_image_request(url, request_cookies, is_svg, request)
            else:
                return await self.handle_html_request(url, request_cookies, request)

        except ContentTooLargeError:
            return await self.render_page("page_too_large")
        except Exception as e:
            server_logger.error(f"Error processing URL {url}: {str(e)}")
            return await self.render_page("not-found")

    async def handle_image_request(self, url: str, request_cookies: dict, is_svg: bool, request: web.Request) -> web.Response:
        """Handle image URL requests"""
        fetch_start = time.time()
        server_logger.info(f"Fetching image URL: {url}")
        
        # Fetch and convert image
        image_data, response_cookies = await fetch_binary(url, cookies=request_cookies)
        
        if is_svg:
            svg_content = image_data.decode('utf-8')
            converter = EBDConverter(svg_content)
        else:
            from PIL import Image
            from io import BytesIO
            image = Image.open(BytesIO(image_data))
            converter = EBDConverter(image)
            
        await converter._ensure_initialized()
        
        # Convert to EBD format
        gscale_depth = self._get_regex_group(self.GSCALE_DEPTH_REGEX, request.path_qs)
        if gscale_depth:
            ebd_data = await converter.convert_gs(depth=int(gscale_depth), compressed=True)
        else:
            ebd_data = await converter.convert_colour(compressed=True)
        
        # Generate HTML
        img_tag = ebd_data.generate_img_tag(name=f"#{self.next_ebd_ref}")
        ebd_tag = ebd_data.generate_ebdimage_tag(name=self.next_ebd_ref)
        self.next_ebd_ref += 1
        
        # Create response with cookies
        response = await self.render_page('image', {
            'image_url': url,
            'image_html': img_tag + "\n" + ebd_tag
        })
        
        # Add cookies to response
        for cookie_header in CookieManager.prepare_response_cookies(response_cookies, url):
            response.headers.add('Set-Cookie', cookie_header)
            
        return response

    async def handle_html_request(self, url: str, request_cookies: dict, request: web.Request) -> web.Response:
        """Handle HTML URL requests"""
        fetch_start = time.time()
        server_logger.info(f"Fetching HTML URL: {url}")
        
        # Fetch and parse HTML
        content, response_url, response_cookies = await fetch(url, cookies=request_cookies)
        fetch_duration = time.time() - fetch_start
        server_logger.debug(f"URL fetch completed in {fetch_duration:.2f}s")
        
        # Parse HTML
        gscale_depth = self._get_regex_group(self.GSCALE_DEPTH_REGEX, request.path_qs)
        grayscale_depth = int(gscale_depth) if gscale_depth else None
        
        parser = XiinoHTMLParser(
            base_url=response_url,
            grayscale_depth=grayscale_depth,
            cookies=request_cookies
        )
        
        parse_start = time.time()
        await parser.feed_async(content)
        clean_html = parser.get_parsed_data()
        parse_duration = time.time() - parse_start
        server_logger.debug(f"HTML parsing completed in {parse_duration:.2f}s")
        
        # Create response with cookies
        response = web.Response(
            body=self._create_response_body(clean_html),
            content_type='text/html'
        )
        
        # Add cookies to response
        for cookie_header in CookieManager.prepare_response_cookies(response_cookies, response_url):
            response.headers.add('Set-Cookie', cookie_header)
            
        return response

    async def render_page(self, page: str, context: dict = None) -> web.Response:
        """Render a page template"""
        content = self.page_controller.handle_page(page, context)
        return web.Response(
            body=self._create_response_body(content),
            content_type='text/html'
        )

    def _create_response_body(self, content: str) -> bytes:
        """Create response body with proper headers"""
        header = bytes([0x00] * 12) + bytes([0x0D, 0x0A] * 2)
        return header + content.encode("latin-1", errors="replace")

async def init_app() -> web.Application:
    """Initialize the aiohttp application"""
    app = web.Application()
    server = XiinoServer()
    
    # Add routes
    app.router.add_get('/', server.handle_xiino_request)
    
    return app

def main():
    """Main entry point"""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "4040"))
    
    server_logger.info(f"Starting server on {host}:{port}")
    
    app = asyncio.run(init_app())
    web.run_app(app, host=host, port=port)

if __name__ == "__main__":
    main()
