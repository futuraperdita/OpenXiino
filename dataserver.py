import os
import re
import asyncio
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from dotenv import load_dotenv
from urllib.parse import urlparse
import time
from lib.xiino_html_converter import XiinoHTMLParser
from lib.controllers.page_controller import PageController
from lib.logger import setup_logging, server_logger
from lib.cookie_manager import CookieManager
from lib.httpclient import fetch, ContentTooLargeError

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
                page_content = self.page_controller.handle_page("not-found")
                self.wfile.write(bytes([0x00] * 12))
                self.wfile.write(bytes([0x0D, 0x0A] * 2))
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
                return

            url = url.group(1)
            
            # Handle xiino URLs and validate
            if not url or not self.validate_url(url):
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
                
                self.wfile.write(bytes([0x00] * 12))
                self.wfile.write(bytes([0x0D, 0x0A] * 2))
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
            else:
                # Handle external URLs asynchronously
                try:
                    fetch_start = time.time()
                    server_logger.info("Fetching external URL: %s" % url)
                    try:
                        content, response_url, response_cookies = await self.fetch_url(url)
                        fetch_duration = time.time() - fetch_start
                        server_logger.debug(f"URL fetch completed in {fetch_duration:.2f}s")
                        
                        # Add Set-Cookie headers to response
                        for cookie_header in CookieManager.prepare_response_cookies(
                            response_cookies,
                            response_url
                        ):
                            self.send_header("Set-Cookie", cookie_header)
                    except ContentTooLargeError:
                        server_logger.warning(f"Content too large for URL: {url}")
                        page_content = self.page_controller.handle_page("page_too_large")
                        self.wfile.write(bytes([0x00] * 12))
                        self.wfile.write(bytes([0x0D, 0x0A] * 2))
                        self.wfile.write(page_content.encode("latin-1", errors="replace"))
                        return
                    
                    # Check if grayscale is requested
                    gscale_depth = self.GSCALE_DEPTH_REGEX.search(self.requestline)
                    grayscale_depth = int(gscale_depth.group(1)) if gscale_depth else None
                    
                    parse_start = time.time()
                    try:
                        parser = XiinoHTMLParser(
                            base_url=response_url,
                            grayscale_depth=grayscale_depth
                        )
                        server_logger.debug(f"Processing URL: {response_url}")
                        await parser.feed_async(content)
                        clean_html = parser.get_parsed_data()
                        parse_duration = time.time() - parse_start
                        server_logger.debug(f"HTML parsing completed in {parse_duration:.2f}s")
                    except ContentTooLargeError:
                        server_logger.warning(f"Content too large for URL: {url}")
                        page_content = self.page_controller.handle_page("error_toolarge")
                        self.wfile.write(bytes([0x00] * 12))
                        self.wfile.write(bytes([0x0D, 0x0A] * 2))
                        self.wfile.write(page_content.encode("latin-1", errors="replace"))
                        return
                    
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
                except Exception as e:
                    server_logger.error(f"Error processing URL {url}: {str(e)}")
                    page_content = self.page_controller.handle_page("not-found")
                    self.wfile.write(bytes([0x00] * 12))
                    self.wfile.write(bytes([0x0D, 0x0A] * 2))
                    self.wfile.write(page_content.encode("latin-1", errors="replace"))

        except Exception as e:
            server_logger.error(f"Error handling request: {str(e)}")
            try:
                page_content = self.page_controller.handle_page("not-found")
                self.wfile.write(bytes([0x00] * 12))
                self.wfile.write(bytes([0x0D, 0x0A] * 2))
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
            except:
                # Last resort error handling
                server_logger.critical("Failed to serve error page")
                self.wfile.write(bytes([0x00] * 12))
                self.wfile.write(bytes([0x0D, 0x0A] * 2))
                self.wfile.write(iso8859("Internal Server Error"))

    def do_GET(self):
        """Handle GET requests by dispatching to async handler"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        
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
