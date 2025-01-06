import os
from typing import Dict, Optional
import aiohttp
from lib.logger import server_logger

DEFAULT_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5"))
DEFAULT_USER_AGENT = os.getenv(
    "USER_AGENT",
    "OpenXiino/1.0 (http://github.com/nicl83/openxiino) python-requests/2.27.1"
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
    timeout_value = aiohttp.ClientTimeout(total=timeout or DEFAULT_TIMEOUT)
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    
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
                
            return (
                await response.text(),
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
