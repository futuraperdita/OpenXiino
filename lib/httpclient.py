import os
import time
from typing import Dict, Optional, Tuple, Union
from urllib.parse import urlparse
import aiohttp
from aiohttp_socks import ProxyConnector
from lib.logger import server_logger
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DEFAULT_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5"))
DEFAULT_USER_AGENT = os.getenv(
    "HTTP_USER_AGENT",
    "Mozilla/1.22 (compatible; MSIE 5.01; PalmOS 3.0) OpenXiino/1.0; 160x160"
)
MAX_PAGE_SIZE = int(os.getenv('HTTP_MAX_PAGE_SIZE', 100)) * 1024  # Convert KB to bytes

# Security settings
MAX_REDIRECTS = int(os.getenv('SECURITY_MAX_REDIRECTS', '10'))
ALLOW_REDIRECTS = os.getenv('SECURITY_ALLOW_REDIRECTS', 'true').lower() == 'true'

# Configure SOCKS proxy if available
PROXY_URL = os.getenv('HTTP_SOCKS_PROXY')
if PROXY_URL:
    proxy_parts = urlparse(PROXY_URL)
    if not proxy_parts.port:
        raise ValueError("SOCKS5 proxy URL must include port number")
    PROXY_HOST = proxy_parts.hostname
    PROXY_PORT = proxy_parts.port
else:
    PROXY_HOST = None
    PROXY_PORT = None

class ContentTooLargeError(Exception):
    """Raised when content exceeds maximum size limit"""
    pass

async def fetch(
    url: str,
    *,
    cookies: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None
) -> Tuple[Union[str, None], str, Dict[str, str]]:
    """
    Fetch URL content using aiohttp.
    Returns (content, final_url, cookies)
    """
    start_time = time.time()
    timeout_value = aiohttp.ClientTimeout(total=timeout or DEFAULT_TIMEOUT)
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    
    server_logger.debug(f"Starting fetch for URL: {url}")
    server_logger.debug(f"Using timeout: {timeout_value.total}s")
    if cookies:
        server_logger.debug(f"Using cookies: {cookies}")
    
    # Create connector with SOCKS5 proxy if configured
    connector = ProxyConnector.from_url(PROXY_URL) if PROXY_URL else None
    async with aiohttp.ClientSession(cookie_jar=None, connector=connector) as session:
        async with session.get(
            url,
            headers=headers,
            cookies=cookies,
            timeout=timeout_value,
            allow_redirects=ALLOW_REDIRECTS,  # Controlled by SECURITY_ALLOW_REDIRECTS
            max_redirects=MAX_REDIRECTS
        ) as response:
            if str(response.url).startswith('https://') and url.startswith('http://'):
                server_logger.debug(f"Connection upgraded to HTTPS: {response.url}")
            # Get response cookies
            response_cookies = {}
            for cookie_name, cookie_morsel in response.cookies.items():
                response_cookies[cookie_name] = cookie_morsel.value
                
            # Check content length if available in headers
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > MAX_PAGE_SIZE:
                server_logger.warning(f"Content length {content_length} bytes exceeds limit of {MAX_PAGE_SIZE} bytes")
                raise ContentTooLargeError()

            # Read content in chunks to check size
            content = ''
            current_size = 0
            async for chunk in response.content.iter_chunks():
                chunk_data = chunk[0]  # chunk is a tuple (data, end_of_chunk)
                current_size += len(chunk_data)
                if current_size > MAX_PAGE_SIZE:
                    server_logger.warning(f"Content size {current_size} bytes exceeds limit of {MAX_PAGE_SIZE} bytes")
                    raise ContentTooLargeError()
                content += chunk_data.decode('utf-8', errors='replace')

            end_time = time.time()
            duration = end_time - start_time
            
            server_logger.debug(f"Fetch completed in {duration:.2f}s")
            server_logger.debug(f"Final URL after redirects: {response.url}")
            server_logger.debug(f"Response status: {response.status}")
            server_logger.debug(f"Response cookies: {response_cookies}")
            server_logger.debug(f"Content size: {current_size} bytes")
            
            return (
                content,
                str(response.url),
                response_cookies
            )

async def post(
    url: str,
    data: Dict[str, str],
    *,
    cookies: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None
) -> Tuple[Union[str, None], str, Dict[str, str]]:
    """
    Submit form data via POST using aiohttp.
    Returns (content, final_url, cookies)
    """
    start_time = time.time()
    timeout_value = aiohttp.ClientTimeout(total=timeout or DEFAULT_TIMEOUT)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    server_logger.debug(f"Starting POST request to URL: {url}")
    server_logger.debug(f"Using timeout: {timeout_value.total}s")
    server_logger.debug(f"POST data: {data}")
    if cookies:
        server_logger.debug(f"Using cookies: {cookies}")
    
    # Create connector with SOCKS5 proxy if configured
    connector = ProxyConnector.from_url(PROXY_URL) if PROXY_URL else None
    async with aiohttp.ClientSession(cookie_jar=None, connector=connector) as session:
        async with session.post(
            url,
            headers=headers,
            cookies=cookies,
            data=data,
            timeout=timeout_value,
            allow_redirects=ALLOW_REDIRECTS,
            max_redirects=MAX_REDIRECTS
        ) as response:
            if str(response.url).startswith('https://') and url.startswith('http://'):
                server_logger.debug(f"Connection upgraded to HTTPS: {response.url}")
            
            # Get response cookies
            response_cookies = {}
            for cookie_name, cookie_morsel in response.cookies.items():
                response_cookies[cookie_name] = cookie_morsel.value
                
            # Check content length if available in headers
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > MAX_PAGE_SIZE:
                server_logger.warning(f"Content length {content_length} bytes exceeds limit of {MAX_PAGE_SIZE} bytes")
                raise ContentTooLargeError()

            # Read content in chunks to check size
            content = ''
            current_size = 0
            async for chunk in response.content.iter_chunks():
                chunk_data = chunk[0]  # chunk is a tuple (data, end_of_chunk)
                current_size += len(chunk_data)
                if current_size > MAX_PAGE_SIZE:
                    server_logger.warning(f"Content size {current_size} bytes exceeds limit of {MAX_PAGE_SIZE} bytes")
                    raise ContentTooLargeError()
                content += chunk_data.decode('utf-8', errors='replace')

            end_time = time.time()
            duration = end_time - start_time
            
            server_logger.debug(f"POST request completed in {duration:.2f}s")
            server_logger.debug(f"Final URL after redirects: {response.url}")
            server_logger.debug(f"Response status: {response.status}")
            server_logger.debug(f"Response cookies: {response_cookies}")
            server_logger.debug(f"Content size: {current_size} bytes")
            
            return (
                content,
                str(response.url),
                response_cookies
            )

async def fetch_binary(
    url: str,
    *,
    cookies: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None
) -> Tuple[bytes, Dict[str, str]]:
    """
    Fetch binary content (like images) using aiohttp.
    Returns (content, cookies)
    """
    timeout_value = aiohttp.ClientTimeout(total=timeout or DEFAULT_TIMEOUT)
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    
    server_logger.debug(f"Starting binary fetch for URL: {url}")
    if cookies:
        server_logger.debug(f"Using cookies: {cookies}")
    
    # Create connector with SOCKS5 proxy if configured
    connector = ProxyConnector.from_url(PROXY_URL) if PROXY_URL else None
    async with aiohttp.ClientSession(cookie_jar=None, connector=connector) as session:
        async with session.get(
            url,
            headers=headers,
            cookies=cookies,
            timeout=timeout_value,
            allow_redirects=ALLOW_REDIRECTS,  # Controlled by SECURITY_ALLOW_REDIRECTS
            max_redirects=MAX_REDIRECTS
        ) as response:
            if str(response.url).startswith('https://') and url.startswith('http://'):
                server_logger.debug(f"Binary fetch connection upgraded to HTTPS: {response.url}")
            # Get response cookies
            response_cookies = {}
            for cookie_name, cookie_morsel in response.cookies.items():
                response_cookies[cookie_name] = cookie_morsel.value
                
            content = await response.read()
            server_logger.debug(f"Binary fetch completed, content size: {len(content)} bytes")
            server_logger.debug(f"Response cookies: {response_cookies}")
            
            return content, response_cookies
