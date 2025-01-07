import os
import time
from typing import Dict, Optional, Tuple, Union
import aiohttp
from lib.logger import server_logger
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DEFAULT_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5"))
DEFAULT_USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/1.22 (compatible; MSIE 5.01; PalmOS 3.0) OpenXiino/1.0; 160x160"
)
MAX_PAGE_SIZE = int(os.getenv('MAX_PAGE_SIZE', 100)) * 1024  # Convert KB to bytes

# Configure proxy if available
PROXY = os.getenv('SOCKS5_PROXY')

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
    
    async with aiohttp.ClientSession(cookie_jar=None) as session:
        async with session.get(
            url,
            headers=headers,
            cookies=cookies,
            proxy=PROXY,
            timeout=timeout_value,
            allow_redirects=True,  # Explicitly enable redirects (including HTTP->HTTPS)
            max_redirects=10
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
    
    async with aiohttp.ClientSession(cookie_jar=None) as session:
        async with session.post(
            url,
            headers=headers,
            cookies=cookies,
            data=data,
            proxy=PROXY,
            timeout=timeout_value,
            allow_redirects=True,
            max_redirects=10
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
    
    async with aiohttp.ClientSession(cookie_jar=None) as session:
        async with session.get(
            url,
            headers=headers,
            cookies=cookies,
            proxy=PROXY,
            timeout=timeout_value,
            allow_redirects=True,  # Explicitly enable redirects (including HTTP->HTTPS)
            max_redirects=10
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
