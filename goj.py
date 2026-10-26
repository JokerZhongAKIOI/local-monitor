"""GOJ personal-session adapter. Never queries other users."""
import ipaddress
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BASE = 'https://www.goj.wiki'


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl)[:2] != urllib.parse.urlsplit(BASE)[:2]:
            raise ValueError('登录跳转到其他站点，已停止')
        if req.data is not None and code not in (301, 302, 303):
            raise ValueError('拒绝重新转发登录凭据')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Sessions(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.item = None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = a.get('class', '').split()
        if tag == 'li':
            if self.item is not None:
                self.depth += 1
            elif 'sessionlist__item' in classes:
                self.item = {'text': [], 'current': False, 'last_activity': None}
                self.depth = 1
        if self.item is not None:
            if 'sessionlist__current-session' in classes:
                self.item['current'] = True
            if 'data-timestamp' in a:
                try:
                    timestamp = float(a['data-timestamp'])
                    if 0 <= timestamp < 253402300800:
                        self.item['last_activity'] = timestamp
                except ValueError:
                    pass

    def handle_data(self, text):
        if self.item is not None:
            self.item['text'].append(text)

    def handle_endtag(self, tag):
        if tag == 'li' and self.item is not None:
            self.depth -= 1
            if self.depth == 0:
                self.items.append(self.item)
                self.item = None


def parse_session(html):
    parser = Sessions()
    parser.feed(html)
    # Select only the monitor client's own session, not a different device.
    current = next((item for item in parser.items if item['current']), None)
    if current is None:
        raise ValueError('未找到当前活动会话；可能需要重新登录或在网站完成身份确认')
    text = ' '.join(current['text'])
    match = re.search(r'(?:位置|Location)\s*[:：]\s*[^()]*\(([^()]*)\)', text, re.I)
    ip = None
    if match and match.group(1).strip():
        try:
            ip = str(ipaddress.ip_address(match.group(1).strip()))
        except ValueError:
            raise ValueError('会话页面 IP 格式无法识别') from None
    return {'ip': ip, 'last_activity': current['last_activity']}


def fetch(opener, path, payload=None):
    body = urllib.parse.urlencode(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers={
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': BASE, 'Referer': BASE + '/login', 'Accept': 'text/html'})
    try:
        with opener.open(req, timeout=8) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('会话页面超过 1MB 限制')
            return raw.decode('utf-8')
    except (urllib.error.URLError, OSError, UnicodeDecodeError):
        raise ValueError('GOJ 请求失败，请检查网络、账号权限及登录状态') from None


def login(opener, username, password):
    fetch(opener, '/login?redirect=%2F', {'uname': username, 'password': password,
                                      'tfa': '', 'authnChallenge': ''})
    # A 200 or 302 alone does not prove successful authentication.
    return read_session(opener)


def read_session(opener):
    return parse_session(fetch(opener, '/home/security'))
