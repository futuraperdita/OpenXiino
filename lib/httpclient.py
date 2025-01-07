import os
import time
from typing import Dict, Optional
import aiohttp
from lib.logger import server_logger

DEFAULT_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5"))
DEFAULT_USER_AGENT = os.getenv(
    "USER_AGENT",
    "OpenXiino/1.0 (http://github.com/nicl83/openxiino)"
)

# Configure proxy if available
PROXY = os.getenv('SOCKS5_PROXY')

async def fetch(
    url: str,
    *,
    cookies: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None
) -> tuple[str, str, Dict[str, str]]:
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
            timeout=timeout_value
        ) as response:
            # Get response cookies
            response_cookies = {}
            for cookie_name, cookie_morsel in response.cookies.items():
                response_cookies[cookie_name] = cookie_morsel.value
                
            content = await response.text()
            end_time = time.time()
            duration = end_time - start_time
            
            server_logger.debug(f"Fetch completed in {duration:.2f}s")
            server_logger.debug(f"Final URL after redirects: {response.url}")
            server_logger.debug(f"Response status: {response.status}")
            server_logger.debug(f"Response cookies: {response_cookies}")
            
            return (
                content,
                str(response.url),
                response_cookies
            )

async def fetch_binary(url: str) -> bytes:
    """
    Fetch binary content (like images) using aiohttp.
    """
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers=headers,
            proxy=PROXY,
            timeout=DEFAULT_TIMEOUT
        ) as response:
            return await response.read()
