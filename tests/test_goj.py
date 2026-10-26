import unittest
import urllib.request
from goj import parse_session, SameOriginRedirect


class GojTests(unittest.TestCase):
    def test_current_only(self):
        html = '''<ul class="sessionlist"><li class="sessionlist__item"><p>位置: (192.0.2.1)</p></li>
        <li class="sessionlist__item"><span data-timestamp="1793003222.484">time</span>
        <p>位置: (203.0.113.10)</p><p class="sessionlist__current-session">current</p></li></ul>'''
        result = parse_session(html)
        self.assertEqual(result['ip'], '203.0.113.10')
        self.assertEqual(result['last_activity'], 1793003222.484)

    def test_blank_ip(self):
        self.assertIsNone(parse_session('<li class="sessionlist__item"><p>位置: ()</p><p class="sessionlist__current-session"></p></li>')['ip'])

    def test_no_session_not_success(self):
        with self.assertRaises(ValueError):
            parse_session('<form>login or sudo required</form>')

    def test_redirect_guard(self):
        req = urllib.request.Request('https://www.goj.wiki/login', data=b'password=secret')
        handler = SameOriginRedirect()
        with self.assertRaises(ValueError):
            handler.redirect_request(req, None, 302, '', {}, 'https://evil.example/')
        redirected = handler.redirect_request(req, None, 302, '', {}, 'https://www.goj.wiki/')
        self.assertIsNone(redirected.data)
