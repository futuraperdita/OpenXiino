import os
import re
import asyncio
import socket
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
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

def iso8859(string: str) -> bytes:
    "Shorthand to convert a string to iso-8859"
    return bytes(string, encoding="iso-8859-1")

# Security constants
MAX_REQUEST_SIZE = 1024 * 1024 * 10  # 10MB max request size
REQUEST_TIMEOUT = 30  # 30 second timeout for requests
MAX_REQUESTS_PER_MIN = 60  # Rate limit per IP
REQUEST_TRACKING = {}  # Track requests per IP

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    daemon_threads = True
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_counts = {}

class XiinoDataServer(BaseHTTPRequestHandler):
    DATASERVER_VERSION = "Pre-Alpha Development Release"

    COLOUR_DEPTH_REGEX = re.compile(r"\/c([0-9]*)\/")
    GSCALE_DEPTH_REGEX = re.compile(r"\/g([0-9]*)\/")
    SCREEN_WIDTH_REGEX = re.compile(r"\/w([0-9]*)\/")
    TXT_ENCODING_REGEX = re.compile(r"\/[de]{1,2}([a-zA-Z0-9-]*)\/")
    URL_REGEX = re.compile(r"\/\?(.*)\s")

    def setup(self):
        """Called by the server after __init__ to setup the handler"""
        super().setup()
        self.page_controller = PageController()
        self.request_start_time = None
        self.headers_sent = False
        self.next_ebd_ref = 1  # Counter for EBD references
        
    def check_rate_limit(self):
        """Check if request exceeds rate limit"""
        client_ip = self.client_address[0]
        current_time = time.time()
        
        # Clean old entries
        REQUEST_TRACKING[client_ip] = [t for t in REQUEST_TRACKING.get(client_ip, [])
                                     if current_time - t < 60]
        
        # Check rate limit
        if len(REQUEST_TRACKING.get(client_ip, [])) >= MAX_REQUESTS_PER_MIN:
            return True
            
        # Add new request
        if client_ip not in REQUEST_TRACKING:
            REQUEST_TRACKING[client_ip] = []
        REQUEST_TRACKING[client_ip].append(current_time)
        return False

    def validate_url(self, url: str) -> bool:
        """Validate URL for security"""
        parsed = urlparse(url)
        if not parsed.scheme == 'http':
            return False
        if not parsed.netloc:
            return False
        return True
        
    async def fetch_url(self, url: str) -> tuple[str, str, dict]:
        """Asynchronously fetch URL content"""
        # Process cookies from Palm client request
        cookies = CookieManager.prepare_request_cookies(
            self.headers.get('Cookie'),
            url
        )
        
        return await fetch(url, cookies=cookies)

    def send_headers_if_needed(self, content_type="text/html"):
        """Send headers if they haven't been sent yet"""
        if not self.headers_sent:
            self.send_header("Content-type", content_type)
            self.end_headers()
            self.headers_sent = True

    async def handle_request(self):
        """Async request handler"""
        request_start = time.time()
        server_logger.debug(f"Starting request handling for {self.requestline}")
        
        # Check request size
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > MAX_REQUEST_SIZE:
            self.send_error(413, "Request entity too large")
            return
            
        # Check rate limit
        if self.check_rate_limit():
            self.send_error(429, "Too many requests")
            return
            
        # Set request timeout
        self.request_start_time = time.time()
        try:
            # Set timeout for async operations
            url = await asyncio.wait_for(
                asyncio.create_task(asyncio.to_thread(self.URL_REGEX.search, self.requestline)),
                timeout=REQUEST_TIMEOUT
            )
            server_logger.info("Request received: %s" % self.requestline)

            if not url:
                # Handle invalid requests with 404 page
                self.send_headers_if_needed()
                page_content = self.page_controller.handle_page("not-found")
                self.wfile.write(bytes([0x00] * 12))
                self.wfile.write(bytes([0x0D, 0x0A] * 2))
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
                return

            url = url.group(1)
            
            # Handle xiino URLs and validate
            if not url or not self.validate_url(url):
                self.send_headers_if_needed()
                page_content = self.page_controller.handle_page("not-found")
                self.wfile.write(bytes([0x00] * 12))
                self.wfile.write(bytes([0x0D, 0x0A] * 2))
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
                return

            parsed_url = urlparse(url)
            if parsed_url.netloc.endswith('.xiino'):
                # Convert xiino URLs to internal pages
                page = parsed_url.netloc.split('.')[0]
                if page == 'about':
                    page = 'home'
                    page_content = self.page_controller.handle_page(page)
                elif page == 'device':
                    # Get device info for device info page
                    colour_depth = self.COLOUR_DEPTH_REGEX.search(self.requestline)
                    gscale_depth = self.GSCALE_DEPTH_REGEX.search(self.requestline)
                    screen_width = self.SCREEN_WIDTH_REGEX.search(self.requestline)
                    txt_encoding = self.TXT_ENCODING_REGEX.search(self.requestline)
                    
                    request_info = {
                        "color_depth": colour_depth.group(1) if colour_depth else None,
                        "grayscale_depth": gscale_depth.group(1) if gscale_depth else None,
                        "screen_width": screen_width.group(1) if screen_width else None,
                        "encoding": txt_encoding.group(1) if txt_encoding else None,
                        "headers": self.headers.as_string()
                    }
                    page_content = self.page_controller.handle_page(page, request_info)
                else:
                    page_content = self.page_controller.handle_page(page)
                
                self.send_headers_if_needed()
                self.wfile.write(bytes([0x00] * 12))
                self.wfile.write(bytes([0x0D, 0x0A] * 2))
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
            else:
                # Check if this is a direct image request and determine type
                parsed_url = urlparse(url)
                mime_type, _ = mimetypes.guess_type(parsed_url.path)
                is_image = mime_type and mime_type.startswith('image/')
                is_svg = (mime_type == 'image/svg+xml' or parsed_url.path.lower().endswith('.svg'))

                # Handle external URLs asynchronously
                try:
                    fetch_start = time.time()
                    server_logger.info("Fetching external URL: %s" % url)
                    try:
                        # Get cookies for both main request and subsequent image requests
                        request_cookies = CookieManager.prepare_request_cookies(
                            self.headers.get('Cookie'),
                            url
                        )
                        
                        if is_image:
                            # Handle direct image requests
                            image_data, response_cookies = await fetch_binary(url, cookies=request_cookies)
                            
                            if is_svg:
                                # For SVGs, pass content directly as string
                                svg_content = image_data.decode('utf-8')
                                converter = EBDConverter(svg_content)
                            else:
                                # For other images, create PIL Image
                                from PIL import Image
                                from io import BytesIO
                                image = Image.open(BytesIO(image_data))
                                converter = EBDConverter(image)
                            await converter._ensure_initialized()
                            
                            # Convert to EBD format (use grayscale if requested)
                            gscale_depth = self.GSCALE_DEPTH_REGEX.search(self.requestline)
                            if gscale_depth:
                                ebd_data = await converter.convert_gs(depth=int(gscale_depth.group(1)), compressed=True)
                            else:
                                ebd_data = await converter.convert_colour(compressed=True)
                            
                            # Generate HTML with EBD tags
                            img_tag = ebd_data.generate_img_tag(name=f"#{self.next_ebd_ref}")
                            ebd_tag = ebd_data.generate_ebdimage_tag(name=self.next_ebd_ref)
                            
                            # Show image in template
                            page_content = self.page_controller.handle_page('image', {
                                'image_url': url,
                                'image_html': img_tag + "\n" + ebd_tag
                            })
                            
                            # Add Set-Cookie headers for image response
                            for cookie_header in CookieManager.prepare_response_cookies(
                                response_cookies,
                                url  # Use original URL for images since we don't have final URL
                            ):
                                self.send_header("Set-Cookie", cookie_header)
                            
                            # Write the page
                            self.send_headers_if_needed()
                            self.wfile.write(bytes([0x00] * 12))
                            self.wfile.write(bytes([0x0D, 0x0A] * 2))
                            self.wfile.write(page_content.encode("latin-1", errors="replace"))
                            
                            # Increment EBD reference for next image
                            self.next_ebd_ref += 1
                        else:
                            # For non-image requests, fetch and parse HTML
                            content, response_url, response_cookies = await fetch(url, cookies=request_cookies)
                            fetch_duration = time.time() - fetch_start
                            server_logger.debug(f"URL fetch completed in {fetch_duration:.2f}s")
                            
                            # Add Set-Cookie headers for HTML response
                            for cookie_header in CookieManager.prepare_response_cookies(
                                response_cookies,
                                response_url
                            ):
                                self.send_header("Set-Cookie", cookie_header)
                            
                            self.send_headers_if_needed()

                            
                            gscale_depth = self.GSCALE_DEPTH_REGEX.search(self.requestline)
                            grayscale_depth = int(gscale_depth.group(1)) if gscale_depth else None
                            
                            parse_start = time.time()

                            parser = XiinoHTMLParser(
                                base_url=response_url,
                                grayscale_depth=grayscale_depth,
                                cookies=request_cookies  # Pass cookies from the request
                            )
                            server_logger.debug(f"Processing URL: {response_url}")
                            await parser.feed_async(content)
                            clean_html = parser.get_parsed_data()
                            parse_duration = time.time() - parse_start
                            server_logger.debug(f"HTML parsing completed in {parse_duration:.2f}s")
                            
                            write_start = time.time()
                            self.wfile.write(bytes([0x00] * 12))
                            self.wfile.write(bytes([0x0D, 0x0A] * 2))
                            self.wfile.write(clean_html.encode("latin-1", errors="ignore"))
                            write_duration = time.time() - write_start
                            server_logger.debug(f"Response write completed in {write_duration:.2f}s")
                            
                            total_duration = time.time() - request_start
                            server_logger.info(
                                f"Request completed in {total_duration:.2f}s "
                                f"(fetch: {fetch_duration:.2f}s, "
                                f"parse: {parse_duration:.2f}s, "
                                f"write: {write_duration:.2f}s)"
                            )
                    except ContentTooLargeError:
                        server_logger.warning(f"Content too large for URL: {url}")
                        self.send_headers_if_needed()
                        page_content = self.page_controller.handle_page("page_too_large")
                        self.wfile.write(bytes([0x00] * 12))
                        self.wfile.write(bytes([0x0D, 0x0A] * 2))
                        self.wfile.write(page_content.encode("latin-1", errors="replace"))
                        return
                except Exception as e:
                    server_logger.error(f"Error processing URL {url}: {str(e)}")
                    self.send_headers_if_needed()
                    page_content = self.page_controller.handle_page("not-found")
                    self.wfile.write(bytes([0x00] * 12))
                    self.wfile.write(bytes([0x0D, 0x0A] * 2))
                    self.wfile.write(page_content.encode("latin-1", errors="replace"))

        except Exception as e:
            server_logger.error(f"Error handling request: {str(e)}")
            try:
                self.send_headers_if_needed()
                page_content = self.page_controller.handle_page("not-found")
                self.wfile.write(bytes([0x00] * 12))
                self.wfile.write(bytes([0x0D, 0x0A] * 2))
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
            except:
                # Last resort error handling
                server_logger.critical("Failed to serve error page")
                self.send_headers_if_needed()
                self.wfile.write(bytes([0x00] * 12))
                self.wfile.write(bytes([0x0D, 0x0A] * 2))
                self.wfile.write(iso8859("Internal Server Error"))

    def do_GET(self):
        """Handle GET requests by dispatching to async handler"""
        self.send_response(200)
        # Headers will be sent by handle_request based on content type
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.handle_request())
        finally:
            loop.close()

if __name__ == "__main__":
    # Get server configuration from .env
    host = os.getenv("HOST", "0.0.0.0")  # Default to all interfaces
    port = int(os.getenv("PORT", "4040"))  # Default to port 4040
    
    server_logger.info(f"Starting server on {host}:{port}")
    
    try:
        # Create and run a single server instance
        server = ThreadedHTTPServer((host, port), XiinoDataServer)
        server_logger.info("Server is ready to handle requests")
        server.serve_forever()
    except KeyboardInterrupt:
        server_logger.info("Shutting down server...")
    except Exception as e:
        server_logger.error(f"Error starting server: {str(e)}")
    finally:
        try:
            server.server_close()
        except:
            pass
        server_logger.info("Server stopped")
