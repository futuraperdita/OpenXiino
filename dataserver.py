import requests
import re
import http.server
from http.server import BaseHTTPRequestHandler
from lib.xiino_html_converter import XiinoHTMLParser
from lib.controllers.page_controller import PageController
import base64


def iso8859(string: str) -> bytes:
    "Shorthand to convert a string to iso-8859"
    return bytes(string, encoding="iso-8859-1")


class XiinoDataServer(BaseHTTPRequestHandler):
    DATASERVER_VERSION = "Pre-Alpha Development Release"

    COLOUR_DEPTH_REGEX = re.compile(r"\/c([0-9]*)\/")
    GSCALE_DEPTH_REGEX = re.compile(r"\/g([0-9]*)\/")
    SCREEN_WIDTH_REGEX = re.compile(r"\/w([0-9]*)\/")
    TXT_ENCODING_REGEX = re.compile(r"\/[de]{1,2}([a-zA-Z0-9-]*)\/")
    URL_REGEX = re.compile(r"\/\?(.*)\s")  # damn, length sync broken :(

    REQUESTS_HEADER = {
        "User-Agent": "OpenXiino/1.0 (http://github.com/nicl83/openxiino) python-requests/2.27.1"
    }

    def __init__(self, *args, **kwargs):
        self.page_controller = PageController()
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        url = self.URL_REGEX.search(self.requestline)

        # send magic padding xiino expects
        self.wfile.write(bytes([0x00] * 12))
        self.wfile.write(bytes([0x0D, 0x0A] * 2))

        if url:
            print(url)
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
                # Handle external URLs
                response = requests.get(url, headers=self.REQUESTS_HEADER, timeout=5)
                
                # Check if grayscale is requested
                gscale_depth = self.GSCALE_DEPTH_REGEX.search(self.requestline)
                grayscale_depth = int(gscale_depth.group(1)) if gscale_depth else None
                
                parser = XiinoHTMLParser(
                    base_url=response.url,
                    grayscale_depth=grayscale_depth
                )
                print(response.url)
                parser.feed(response.text)
                clean_html = parser.get_parsed_data()
                self.wfile.write(clean_html.encode("latin-1", errors="ignore"))
        else:
            # Handle invalid requests with 404 page
            page_content = self.page_controller.handle_page("about:not-found")
            self.wfile.write(page_content.encode("latin-1", errors="replace"))


if __name__ == "__main__":
    web_server = http.server.HTTPServer(("0.0.0.0", 4040), XiinoDataServer)
    print("Dataserver running on port 4040")
    try:
        web_server.serve_forever()
    except KeyboardInterrupt:
        pass

    web_server.server_close()
    print("Dataserver stopped.")
