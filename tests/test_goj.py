import unittest
import urllib.request
from goj import parse_session, SameOriginRedirect, check_session_destination


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

    def test_sudo_is_not_expired_session(self):
        with self.assertRaisesRegex(ValueError, '二次身份确认'):
            check_session_destination('https://www.goj.wiki/user/sudo?redirect=%2Fhome%2Fsecurity')

    def test_login_destination(self):
        with self.assertRaisesRegex(ValueError, '登录未成功'):
            check_session_destination('https://www.goj.wiki/login?redirect=%2F')

    def test_unexpected_page(self):
        with self.assertRaises(ValueError):
            check_session_destination('https://www.goj.wiki/')
        with self.assertRaises(ValueError):
            check_session_destination('https://evil.example/home/security')
        check_session_destination('https://www.goj.wiki/home/security')

    def test_sudo_form_fields_and_csrf(self):
        from goj import SudoRequired, sudo_submission
        challenge = SudoRequired('https://www.goj.wiki/user/sudo?redirect=%2Fhome%2Fsecurity', '''
        <form method="post"><input type="hidden" name="csrf" value="test-token">
        <input name="password" type="password" required>
        <button name="confirm" value="true">确认</button></form>''')
        path, fields = sudo_submission(challenge, 'test-password')
        self.assertEqual(path, '/user/sudo?redirect=%2Fhome%2Fsecurity')
        self.assertEqual(fields, {'csrf': 'test-token', 'confirm': 'true', 'password': 'test-password'})

    def test_sudo_does_not_guess_or_send_cross_origin(self):
        from goj import SudoRequired, sudo_submission
        for action, confirm in [('https://evil.example/user/sudo', '<input type="hidden" name="confirm" value="1">'),
                                ('/other', '<input type="hidden" name="confirm" value="1">'),
                                ('/user/sudo', '')]:
            challenge = SudoRequired('https://www.goj.wiki/user/sudo', f'''
            <form method="post" action="{action}"><input name="password" type="password">{confirm}</form>''')
            with self.assertRaises(ValueError):
                sudo_submission(challenge, 'test-password')

    def test_sudo_opt_in_and_bounded_retry(self):
        from unittest.mock import patch
        from goj import SudoRequired, login
        challenge = SudoRequired('https://www.goj.wiki/user/sudo', '''<form method="post">
        <input name="password" type="password"><input type="hidden" name="confirm" value="1"></form>''')
        with patch('goj.fetch') as fetch, patch('goj.read_session', side_effect=challenge):
            with self.assertRaises(SudoRequired):
                login(object(), 'alice', 'test-password')
            self.assertEqual(fetch.call_count, 1)  # Login only, no sudo POST.
        with patch('goj.fetch') as fetch, patch('goj.read_session', side_effect=[challenge, {'ip': None}]):
            self.assertEqual(login(object(), 'alice', 'test-password', True), {'ip': None})
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(fetch.call_args.args[2]['confirm'], '1')
        with patch('goj.fetch') as fetch, patch('goj.read_session', side_effect=challenge):
            with self.assertRaisesRegex(ValueError, '未重复提交'):
                login(object(), 'alice', 'test-password', True)
            self.assertEqual(fetch.call_count, 2)
