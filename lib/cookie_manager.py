from http.cookies import SimpleCookie, Morsel
from typing import Dict, List, Optional
from urllib.parse import urlparse
import logging

class CookieManager:
    """
    Manages cookies for Xiino proxy requests while respecting Xiino limitations:
    - Maximum 40 cookies total
    - Maximum 20 cookies per site
    - Maximum cookie size of 4KB
    """
    
    MAX_TOTAL_COOKIES = 40
    MAX_COOKIES_PER_SITE = 20
    MAX_COOKIE_SIZE = 4096  # 4KB
    
    @staticmethod
    def parse_cookie_header(cookie_header: Optional[str]) -> SimpleCookie:
        """Parse Cookie header from Palm client into SimpleCookie object"""
        if not cookie_header:
            return SimpleCookie()
        
        try:
            cookies = SimpleCookie()
            cookies.load(cookie_header)
            return cookies
        except Exception as e:
            logging.error(f"Error parsing cookie header: {e}")
            return SimpleCookie()
    
    @staticmethod
    def get_domain_from_url(url: str) -> str:
        """Extract domain from URL for cookie domain matching"""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            return ""
    
    @staticmethod
    def cookie_size(cookie: Morsel) -> int:
        """Calculate size of a cookie in bytes"""
        return len(f"{cookie.key}={cookie.value}".encode())
    
    @classmethod
    def validate_cookie(cls, cookie: Morsel, domain: str, existing_domain_cookies: int) -> bool:
        """
        Validate if a cookie meets Xiino's requirements:
        - Size limit
        - Per-site limit
        """
        if cls.cookie_size(cookie) > cls.MAX_COOKIE_SIZE:
            logging.warning(f"Cookie {cookie.key} exceeds max size of {cls.MAX_COOKIE_SIZE} bytes")
            return False
            
        if existing_domain_cookies >= cls.MAX_COOKIES_PER_SITE:
            logging.warning(f"Domain {domain} has reached max cookies limit of {cls.MAX_COOKIES_PER_SITE}")
            return False
            
        return True
    
    @classmethod
    def prepare_request_cookies(cls, palm_cookie_header: Optional[str], url: str) -> Dict[str, str]:
        """
        Process cookies from Palm client for outgoing WWW request.
        Returns dict of cookies to be sent.
        """
        cookies = cls.parse_cookie_header(palm_cookie_header)
        domain = cls.get_domain_from_url(url)
        
        # Convert to dict format expected by requests/aiohttp
        cookie_dict = {}
        domain_cookie_count = 0
        
        for cookie in cookies.values():
            if domain_cookie_count >= cls.MAX_COOKIES_PER_SITE:
                break
                
            if cls.validate_cookie(cookie, domain, domain_cookie_count):
                cookie_dict[cookie.key] = cookie.value
                domain_cookie_count += 1
                
        return cookie_dict
    
    @classmethod
    def prepare_response_cookies(cls, response_cookies: Dict[str, str], url: str) -> List[str]:
        """
        Process cookies from WWW response to send back to Palm client.
        Returns list of Set-Cookie headers.
        """
        domain = cls.get_domain_from_url(url)
        set_cookie_headers = []
        domain_cookie_count = 0
        
        for name, value in response_cookies.items():
            if domain_cookie_count >= cls.MAX_COOKIES_PER_SITE:
                break
                
            cookie = SimpleCookie()
            cookie[name] = value
            morsel = cookie[name]
            
            if cls.validate_cookie(morsel, domain, domain_cookie_count):
                set_cookie_headers.append(cookie.output(header="").strip())
                domain_cookie_count += 1
                
        return set_cookie_headers
