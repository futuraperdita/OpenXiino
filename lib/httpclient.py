import os
import time
import ssl
from typing import Dict, Optional, Tuple, Union
from urllib.parse import urlparse, urlunparse
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
ATTEMPT_HTTPS_UPGRADE = os.getenv('SECURITY_ATTEMPT_HTTPS_UPGRADE', 'true').lower() == 'true'

# SSL context for HTTPS connections
ssl_context = ssl.create_default_context()
ssl_context.set_alpn_protocols(['http/1.1', 'http/1.0'])

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

async def try_https_upgrade(url: str, session: aiohttp.ClientSession, **kwargs) -> Optional[aiohttp.ClientResponse]:
    """
    Attempt to upgrade an HTTP connection to HTTPS.
    Returns the response if successful, None if upgrade failed.
    """
    if not ATTEMPT_HTTPS_UPGRADE or url.startswith('https://'):
        return None
        
    # Try direct HTTPS
    https_url = urlunparse(urlparse(url)._replace(scheme='https'))
    try:
        # Add Upgrade header for HTTP/1.1 upgrade mechanism
        headers = kwargs.get('headers', {}).copy()
        headers.update({
            'Upgrade': 'TLS/1.0, HTTP/1.1',
            'Connection': 'Upgrade'
        })
        kwargs['headers'] = headers
        
        response = await session.get(https_url, ssl=ssl_context, **kwargs)
        if response.status == 101:  # Switching Protocols
            server_logger.debug("Successfully upgraded to HTTPS via HTTP/1.1 Upgrade")
            return response
        elif response.status < 400:
            server_logger.debug("Successfully connected via direct HTTPS")
            return response
        else:
            await response.close()
            return None
    except (aiohttp.ClientError, ssl.SSLError) as e:
        server_logger.debug(f"HTTPS upgrade attempt failed: {str(e)}")
        return None

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
        # Try HTTPS upgrade first
        kwargs = {
            'headers': headers,
            'cookies': cookies,
            'timeout': timeout_value,
            'allow_redirects': ALLOW_REDIRECTS,
            'max_redirects': MAX_REDIRECTS
        }
        
        upgraded_response = await try_https_upgrade(url, session, **kwargs)
        if upgraded_response:
            response = upgraded_response
        else:
            # Fall back to original HTTP request if upgrade fails
            response = await session.get(url, **kwargs)
            
        async with response:
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
        # Try HTTPS upgrade first
        kwargs = {
            'headers': headers,
            'cookies': cookies,
            'data': data,
            'timeout': timeout_value,
            'allow_redirects': ALLOW_REDIRECTS,
            'max_redirects': MAX_REDIRECTS
        }
        
        upgraded_response = await try_https_upgrade(url, session, **kwargs)
        if upgraded_response:
            response = upgraded_response
        else:
            # Fall back to original HTTP request if upgrade fails
            response = await session.post(url, **kwargs)
            
        async with response:
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
        # Try HTTPS upgrade first
        kwargs = {
            'headers': headers,
            'cookies': cookies,
            'timeout': timeout_value,
            'allow_redirects': ALLOW_REDIRECTS,
            'max_redirects': MAX_REDIRECTS
        }
        
        upgraded_response = await try_https_upgrade(url, session, **kwargs)
        if upgraded_response:
            response = upgraded_response
        else:
            # Fall back to original HTTP request if upgrade fails
            response = await session.get(url, **kwargs)
            
        async with response:
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
