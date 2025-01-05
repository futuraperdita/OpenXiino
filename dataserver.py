import os
import re
import asyncio
import socket
import multiprocessing
from aiohttp import ClientSession, ClientTimeout
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from dotenv import load_dotenv
from lib.xiino_html_converter import XiinoHTMLParser
from lib.controllers.page_controller import PageController
import base64

# Load environment variables
load_dotenv()

def iso8859(string: str) -> bytes:
    "Shorthand to convert a string to iso-8859"
    return bytes(string, encoding="iso-8859-1")

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    allow_reuse_address = True
    daemon_threads = True

class XiinoDataServer(BaseHTTPRequestHandler):
    DATASERVER_VERSION = "Pre-Alpha Development Release"

    COLOUR_DEPTH_REGEX = re.compile(r"\/c([0-9]*)\/")
    GSCALE_DEPTH_REGEX = re.compile(r"\/g([0-9]*)\/")
    SCREEN_WIDTH_REGEX = re.compile(r"\/w([0-9]*)\/")
    TXT_ENCODING_REGEX = re.compile(r"\/[de]{1,2}([a-zA-Z0-9-]*)\/")
    URL_REGEX = re.compile(r"\/\?(.*)\s")

    REQUESTS_HEADER = {
        "User-Agent": os.getenv("USER_AGENT", "OpenXiino/1.0 (http://github.com/nicl83/openxiino) python-requests/2.27.1")
    }

    def __init__(self, *args, **kwargs):
        self.page_controller = PageController()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        super().__init__(*args, **kwargs)

    async def fetch_url(self, url: str) -> tuple[str, str]:
        """Asynchronously fetch URL content"""
        timeout = ClientTimeout(total=float(os.getenv("REQUEST_TIMEOUT", "5")))
        async with ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=self.REQUESTS_HEADER) as response:
                return await response.text(), str(response.url)

    async def handle_request(self):
        """Async request handler"""
        try:
            url = self.URL_REGEX.search(self.requestline)

            # send magic padding xiino expects
            self.wfile.write(bytes([0x00] * 12))
            self.wfile.write(bytes([0x0D, 0x0A] * 2))

            if not url:
                # Handle invalid requests with 404 page
                page_content = self.page_controller.handle_page("about:not-found")
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
                return

            url = url.group(1)
            
            # Handle about: URLs
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
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
            else:
                # Handle external URLs asynchronously
                try:
                    content, response_url = await self.fetch_url(url)
                    
                    # Check if grayscale is requested
                    gscale_depth = self.GSCALE_DEPTH_REGEX.search(self.requestline)
                    grayscale_depth = int(gscale_depth.group(1)) if gscale_depth else None
                    
                    parser = XiinoHTMLParser(
                        base_url=response_url,
                        grayscale_depth=grayscale_depth
                    )
                    print(f"Processing URL: {response_url}")
                    parser.feed(content)
                    clean_html = parser.get_parsed_data()
                    self.wfile.write(clean_html.encode("latin-1", errors="ignore"))
                except Exception as e:
                    print(f"Error processing URL {url}: {str(e)}")
                    page_content = self.page_controller.handle_page("about:not-found")
                    self.wfile.write(page_content.encode("latin-1", errors="replace"))

        except Exception as e:
            print(f"Error handling request: {str(e)}")
            try:
                page_content = self.page_controller.handle_page("about:not-found")
                self.wfile.write(page_content.encode("latin-1", errors="replace"))
            except:
                # Last resort error handling
                self.wfile.write(iso8859("Internal Server Error"))

    def do_GET(self):
        """Handle GET requests by dispatching to async handler"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        
        self.loop.run_until_complete(self.handle_request())

def run_worker(server):
    """Run a worker process that handles requests from the shared server"""
    try:
        print(f"Worker process {multiprocessing.current_process().name} started")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error in worker process: {str(e)}")

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
    
    print(f"Starting server on {host}:{port} with {workers} workers")
    
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
        print("\nShutting down server...")
    finally:
        server.shutdown()
        server.server_close()
        
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
        
        print("Server stopped")
