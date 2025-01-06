import os
import re
import asyncio
import multiprocessing
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from dotenv import load_dotenv
from urllib.parse import urlparse
import time
from lib.xiino_html_converter import XiinoHTMLParser
from lib.controllers.page_controller import PageController
from lib.logger import setup_logging, server_logger
from lib.cookie_manager import CookieManager
from lib.httpclient import fetch

# Load environment variables and setup logging
load_dotenv()
setup_logging()

def iso8859(string: str) -> bytes:
    "Shorthand to convert a string to iso-8859"
    return bytes(string, encoding="iso-8859-1")

# Security constants
MAX_WORKERS = 16  # Maximum number of worker processes
MAX_REQUEST_SIZE = 1024 * 1024 * 10  # 10MB max request size
REQUEST_TIMEOUT = 30  # 30 second timeout for requests
MAX_REQUESTS_PER_MIN = 60  # Rate limit per IP
REQUEST_TRACKING = {}  # Track requests per IP

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    allow_reuse_address = True
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

    def __init__(self, *args, **kwargs):
        self.page_controller = PageController()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.request_start_time = None
        super().__init__(*args, **kwargs)
        
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
        if not parsed.scheme in ('http', 'https'):
            return False
        if not parsed.netloc:
            return False
        # Add additional validation as needed
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

            # send magic padding xiino expects
            self.wfile.write(bytes([0x00] * 12))
            self.wfile.write(bytes([0x0D, 0x0A] * 2))

            if not url:
                # Handle invalid requests with 404 page
                page_content = self.page_controller.handle_page("about:not-found")
                self.end_headers()  # End headers before writing response
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
                return

            url = url.group(1)
            
            # Handle about: URLs
            # Validate URL
            if not url or not self.validate_url(url):
                page_content = self.page_controller.handle_page("about:not-found")
                self.end_headers()
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
                return
                
            if url.startswith("http://about/"):
                url = "about:"
            elif url == "http://github/":
                url = "about:github"
            elif url == "http://about2/":
                url = "about:more"
            elif url == "http://deviceinfo/":
                url = "about:device"
                
            if url.startswith("about:"):
                # Get device info for device info page
                request_info = None
                if url == "about:device":
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
                
                # Render page using controller
                page_content = self.page_controller.handle_page(url, request_info)
                self.end_headers()  # End headers before writing response
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
            else:
                # Handle external URLs asynchronously
                try:
                    content, response_url, response_cookies = await self.fetch_url(url)
                    
                    # Add Set-Cookie headers to response
                    set_cookie_headers = CookieManager.prepare_response_cookies(
                        response_cookies,
                        response_url
                    )
                    for cookie_header in set_cookie_headers:
                        self.send_header("Set-Cookie", cookie_header)
                    
                    # Check if grayscale is requested
                    gscale_depth = self.GSCALE_DEPTH_REGEX.search(self.requestline)
                    grayscale_depth = int(gscale_depth.group(1)) if gscale_depth else None
                    
                    parser = XiinoHTMLParser(
                        base_url=response_url,
                        grayscale_depth=grayscale_depth
                    )
                    server_logger.debug(f"Processing URL: {response_url}")
                    await parser.feed_async(content)
                    clean_html = parser.get_parsed_data()
                    self.end_headers()  # End headers after adding Set-Cookie headers
                    self.wfile.write(clean_html.encode("latin-1", errors="ignore"))
                except Exception as e:
                    server_logger.error(f"Error processing URL {url}: {str(e)}")
                    page_content = self.page_controller.handle_page("about:not-found")
                    self.end_headers()  # End headers before writing response
                    self.wfile.write(page_content.encode("latin-1", errors="replace"))

        except Exception as e:
            server_logger.error(f"Error handling request: {str(e)}")
            try:
                page_content = self.page_controller.handle_page("about:not-found")
                self.end_headers()  # End headers before writing response
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
            except:
                # Last resort error handling
                server_logger.critical("Failed to serve error page")
                self.end_headers()  # End headers before writing response
                self.wfile.write(iso8859("Internal Server Error"))

    def do_GET(self):
        """Handle GET requests by dispatching to async handler"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        # Headers will be ended in handle_request after adding any Set-Cookie headers
        
        self.loop.run_until_complete(self.handle_request())

def run_worker(server):
    """Run a worker process that handles requests from the shared server"""
    try:
        server_logger.info(f"Worker process {multiprocessing.current_process().name} started")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        server_logger.error(f"Error in worker process: {str(e)}")

if __name__ == "__main__":
    # Determine number of worker processes
    workers = int(os.getenv("WORKERS", "0"))
    if workers <= 0:
        workers = multiprocessing.cpu_count()

    # Create and configure the server
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "4040"))
    
    # Create a single server instance that will be shared
    server = ThreadedHTTPServer((host, port), XiinoDataServer)
    server.allow_reuse_address = True
    
    server_logger.info(f"Starting server on {host}:{port} with {workers} workers")
    
    # Start worker processes
    processes = []
    try:
        for _ in range(workers):
            process = multiprocessing.Process(target=run_worker, args=(server,))
            process.start()
            processes.append(process)

        # Wait for all processes to complete
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        server_logger.info("Shutting down server...")
    finally:
        server.shutdown()
        server.server_close()
        
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
        
        server_logger.info("Server stopped")
