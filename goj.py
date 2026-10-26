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
        raise ValueError('会话页面未包含当前会话标记，可能是页面结构变化或访问受限；请勿将此结果视为离线')
    text = ' '.join(current['text'])
    match = re.search(r'(?:位置|Location)\s*[:：]\s*[^()]*\(([^()]*)\)', text, re.I)
    ip = None
    if match and match.group(1).strip():
        try:
            ip = str(ipaddress.ip_address(match.group(1).strip()))
        except ValueError:
            raise ValueError('会话页面 IP 格式无法识别') from None
    return {'ip': ip, 'last_activity': current['last_activity']}


class SudoRequired(ValueError):
    def __init__(self, url, html=''):
        super().__init__('GOJ 要求本监控会话完成二次身份确认（/user/sudo）；请重新连接并勾选允许本次二次验证，浏览器的确认不会授权本程序')
        self.url = url
        self.html = html


class SudoForms(HTMLParser):
    """Read the actual same-origin confirmation form, including hidden CSRF fields."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.form = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self.form = {'action': a.get('action', ''), 'method': a.get('method', 'get').lower(),
                         'fields': {}, 'password': False, 'unsupported': False}
        elif self.form is not None and tag in ('input', 'button'):
            if 'disabled' in a or not a.get('name'):
                return
            name = a['name']
            kind = a.get('type', 'submit' if tag == 'button' else 'text').lower()
            if name == 'password' and kind == 'password':
                self.form['password'] = True
            elif kind == 'hidden' or (name == 'confirm' and kind == 'submit'):
                self.form['fields'][name] = a.get('value', '')
            elif kind in ('checkbox', 'radio') and 'checked' in a:
                self.form['fields'][name] = a.get('value', 'on')
            elif 'required' in a:
                self.form['unsupported'] = True

    def handle_endtag(self, tag):
        if tag == 'form' and self.form is not None:
            self.forms.append(self.form)
            self.form = None


def sudo_submission(challenge, password):
    parser = SudoForms()
    parser.feed(challenge.html)
    forms = [f for f in parser.forms if f['password']]
    if len(forms) != 1:
        raise ValueError('无法识别唯一的二次验证表单，已停止；请确认网站是否改变验证方式')
    form = forms[0]
    url = urllib.parse.urljoin(challenge.url, form['action'])
    parsed = urllib.parse.urlsplit(url)
    if (parsed[:2] != urllib.parse.urlsplit(BASE)[:2] or parsed.path != '/user/sudo'
            or parsed.fragment or form['method'] != 'post'):
        raise ValueError('二次验证表单目标不安全或不受支持，未提交密码')
    if form['unsupported'] or 'confirm' not in form['fields']:
        raise ValueError('二次验证表单包含未支持字段或缺少 confirm，未猜测确认参数')
    fields = dict(form['fields'])
    fields['password'] = password
    return urllib.parse.urlunsplit(('', '', parsed.path, parsed.query, '')), fields


def check_session_destination(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed[:2] != urllib.parse.urlsplit(BASE)[:2]:
        raise ValueError('会话响应来自其他站点，已停止')
    path = parsed.path.rstrip('/')
    if path == '/user/sudo':
        raise SudoRequired(url)
    if path == '/login':
        raise ValueError('GOJ 将本监控会话退回登录页，登录未成功或会话已失效')
    if path != '/home/security':
        raise ValueError('GOJ 未返回预期的个人安全页面，可能需要额外验证或权限')


def fetch(opener, path, payload=None, referer=None):
    body = urllib.parse.urlencode(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers={
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': BASE, 'Referer': referer or BASE + '/login', 'Accept': 'text/html'})
    try:
        with opener.open(req, timeout=8) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('会话页面超过 1MB 限制')
            html = raw.decode('utf-8')
            if path == '/home/security':
                try:
                    check_session_destination(response.geturl())
                except SudoRequired as exc:
                    exc.html = html
                    raise
            return html
    except (urllib.error.URLError, OSError, UnicodeDecodeError):
        raise ValueError('GOJ 请求失败，请检查网络、账号权限及登录状态') from None


def login(opener, username, password, allow_sudo=False):
    fetch(opener, '/login?redirect=%2F', {'uname': username, 'password': password,
                                      'tfa': '', 'authnChallenge': ''})
    # A 200 or 302 alone does not prove successful authentication.
    try:
        return read_session(opener)
    except SudoRequired as challenge:
        if not allow_sudo:
            raise
        path, fields = sudo_submission(challenge, password)
        # One attempt only, same CookieJar. Do not retain the password for polling.
        fetch(opener, path, fields, referer=challenge.url)
        try:
            return read_session(opener)
        except SudoRequired:
            raise ValueError('GOJ 二次验证未通过或仍需其他验证；已停止，未重复提交密码') from None


def read_session(opener):
    return parse_session(fetch(opener, '/home/security'))
