import unittest
from http.cookies import SimpleCookie
from lib.cookie_manager import CookieManager

class TestCookieManager(unittest.TestCase):
    def test_parse_cookie_header(self):
        header = "session=abc123; user=john"
        cookies = CookieManager.parse_cookie_header(header)
        self.assertIsInstance(cookies, SimpleCookie)
        self.assertEqual(cookies["session"].value, "abc123")
        self.assertEqual(cookies["user"].value, "john")
        
    def test_parse_cookie_header_empty(self):
        cookies = CookieManager.parse_cookie_header(None)
        self.assertIsInstance(cookies, SimpleCookie)
        self.assertEqual(len(cookies), 0)
        
    def test_get_domain_from_url(self):
        url = "http://example.com/path?query=1"
        domain = CookieManager.get_domain_from_url(url)
        self.assertEqual(domain, "example.com")
        
    def test_get_domain_from_invalid_url(self):
        domain = CookieManager.get_domain_from_url("invalid")
        self.assertEqual(domain, "")
        
    def test_cookie_size(self):
        cookie = SimpleCookie()
        cookie["test"] = "value"
        size = CookieManager.cookie_size(cookie["test"])
        self.assertEqual(size, len("test=value".encode()))
        
    def test_validate_cookie_size_limit(self):
        cookie = SimpleCookie()
        cookie["large"] = "x" * 5000  # Exceeds 4KB limit
        valid = CookieManager.validate_cookie(
            cookie["large"],
            "example.com",
            0
        )
        self.assertFalse(valid)
        
    def test_validate_cookie_domain_limit(self):
        cookie = SimpleCookie()
        cookie["test"] = "value"
        valid = CookieManager.validate_cookie(
            cookie["test"],
            "example.com",
            20  # At domain limit
        )
        self.assertFalse(valid)
        
    def test_validate_cookie_valid(self):
        cookie = SimpleCookie()
        cookie["test"] = "value"
        valid = CookieManager.validate_cookie(
            cookie["test"],
            "example.com",
            0  # No cookies yet for domain
        )
        self.assertTrue(valid)
        
    def test_prepare_request_cookies(self):
        header = "session=abc123; user=john"
        url = "http://example.com"
        cookies = CookieManager.prepare_request_cookies(header, url)
        self.assertEqual(cookies["session"], "abc123")
        self.assertEqual(cookies["user"], "john")
        
    def test_prepare_request_cookies_empty(self):
        cookies = CookieManager.prepare_request_cookies(None, "http://example.com")
        self.assertEqual(len(cookies), 0)
        
    def test_prepare_response_cookies(self):
        cookies = {"session": "abc123", "user": "john"}
        url = "http://example.com"
        headers = CookieManager.prepare_response_cookies(cookies, url)
        self.assertEqual(len(headers), 2)
        self.assertTrue(any("session=abc123" in h for h in headers))
        self.assertTrue(any("user=john" in h for h in headers))
        
    def test_prepare_response_cookies_domain_limit(self):
        # Create more cookies than allowed per domain
        cookies = {f"cookie{i}": f"value{i}" for i in range(25)}
        url = "http://example.com"
        headers = CookieManager.prepare_response_cookies(cookies, url)
        self.assertEqual(len(headers), CookieManager.MAX_COOKIES_PER_SITE)

if __name__ == "__main__":
    unittest.main()
