"""Local monitor: standard-library server, authorized JSON API adapters only."""
import argparse
import http.cookiejar
import ipaddress
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('MONITOR_DB', ROOT / 'data' / 'monitor.db'))
SITES = {'local': ('校园内网站点', 'http://10.177.41.90'), 'goj': ('GOJ 在线评测', 'https://www.goj.wiki')}
SESSIONS = {}
LOCK = threading.RLock()
WAKE = threading.Event()


def validate_assets():
    missing = [ROOT / 'static' / name for name in ('index.html', 'app.js', 'style.css')
               if not (ROOT / 'static' / name).is_file()]
    if missing:
        paths = '\n'.join(f'  - {path}' for path in missing)
        raise ValueError(
            f'缺少前端文件：\n{paths}\n'
            '请解压完整项目，不要只复制 Python 文件。'
            'static 文件夹必须与运行的 Python 文件位于同一目录。')


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def init():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS monitors (
        id TEXT PRIMARY KEY, site TEXT NOT NULL, target TEXT NOT NULL,
        login_path TEXT NOT NULL, status_path TEXT NOT NULL,
        user_field TEXT NOT NULL, password_field TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'disconnected', ip TEXT, checked REAL,
        error TEXT, enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, monitor_id TEXT, site TEXT, target TEXT,
        kind TEXT, message TEXT, time REAL);''')


def event(db, m, kind, message):
    db.execute('INSERT INTO events(monitor_id,site,target,kind,message,time) VALUES(?,?,?,?,?,?)',
               (m['id'], m['site'], m['target'], kind, message, time.time()))
    db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 500)')


def endpoint(site, path):
    # Never permit credentials or redirects to an arbitrary host.
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or '\\' in path:
        raise ValueError('接口路径必须以单个 / 开头')
    url = SITES[site][1] + path
    parsed = urllib.parse.urlsplit(url)
    if parsed.netloc != urllib.parse.urlsplit(SITES[site][1]).netloc or parsed.fragment:
        raise ValueError('接口必须位于选定站点内，且不能含片段标识')
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('接口发生重定向，已停止以避免凭据泄漏；请使用最终 API 路径')


def request_json(opener, url, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, body, {'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with opener.open(req, timeout=8) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('接口响应超过 1MB 限制')
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'接口返回 HTTP {exc.code}，请检查权限及接口路径') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('无法连接站点，请检查本机网络、VPN 或接口地址') from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('接口未返回 JSON，请确认使用的是 API 而非网页地址') from None


def poll(m):
    with LOCK:
        session = SESSIONS.get(m['id'])
        if session is None:
            return
        try:
            url = endpoint(m['site'], m['status_path'])
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode({'username': m['target']})
            result = request_json(session, url)
            if not isinstance(result, dict) or type(result.get('online')) is not bool:
                raise ValueError('状态接口需返回 {"online": true/false, "ip": "IP 地址"}')
            state = 'online' if result['online'] else 'offline'
            ip = result.get('ip') if result['online'] else None
            if ip is not None:
                ip = str(ipaddress.ip_address(ip))
            error = None
        except (ValueError, TypeError) as exc:
            state, ip, error = 'error', None, str(exc)
        with connect() as db:
            current = db.execute('SELECT * FROM monitors WHERE id=?', (m['id'],)).fetchone()
            if not current or not current['enabled']:
                return
            db.execute('UPDATE monitors SET state=?,ip=?,error=?,checked=? WHERE id=?',
                       (state, ip, error, time.time(), m['id']))
            if current['state'] != state or current['ip'] != ip or current['error'] != error:
                event(db, m, 'error' if error else 'change', error or f'{state} · {ip or "未提供 IP"}')


def worker():
    while True:
        with connect() as db:
            monitors = [dict(r) for r in db.execute('SELECT * FROM monitors WHERE enabled=1')]
        for m in monitors:
            poll(m)
        WAKE.wait(15)
        WAKE.clear()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log URL query strings or credentials.
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/api/state':
            with connect() as db:
                monitors = [dict(r) for r in db.execute('SELECT * FROM monitors ORDER BY rowid DESC')]
                events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 80')]
            return self.send_json({'monitors': monitors, 'events': events, 'interval': 15})
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path not in files:
            return self.send_json({'error': 'Not found'}, 404)
        filename, mime = files[path]
        try:
            body = (ROOT / 'static' / filename).read_bytes()
        except OSError:
            return self.send_json({'error': '无法读取前端文件，请检查完整项目中的 static 文件夹及读取权限'}, 503)
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'self' https://*.arena.ai https://*.e2b.app")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # JSON + custom header prevent cross-site form submissions. No CORS enabled.
        origin = self.headers.get('Origin')
        if (origin and urllib.parse.urlsplit(origin).netloc != self.headers.get('Host')) or self.headers.get('X-Monitor-Request') != '1':
            return self.send_json({'error': '禁止跨站请求'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 1 or size > 16384:
                raise ValueError('请求体大小不合法')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('请求格式不正确')
            path = urllib.parse.urlsplit(self.path).path
            if path == '/api/connect':
                site = data.get('site')
                if site not in SITES:
                    raise ValueError('无效站点')
                for key in ('username', 'password', 'target', 'login_path', 'status_path', 'user_field', 'password_field'):
                    if not isinstance(data.get(key), str) or not data[key].strip() or len(data[key]) > 1000:
                        raise ValueError('请完整填写登录信息和接口配置')
                if data['user_field'] == data['password_field']:
                    raise ValueError('用户名和密码字段名不能相同')
                login_url = endpoint(site, data['login_path'])
                endpoint(site, data['status_path'])
                opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                result = request_json(opener, login_url, {data['user_field']: data['username'], data['password_field']: data['password']})
                if not isinstance(result, dict) or result.get('success') is not True:
                    raise ValueError('登录接口需返回 {"success": true} 并设置会话 Cookie；请核对账号及接口协议')
                mid = secrets.token_hex(12)
                m = {'id': mid, **{k: data[k] for k in ('site', 'target', 'login_path', 'status_path', 'user_field', 'password_field')}}
                with LOCK:
                    SESSIONS[mid] = opener
                    with connect() as db:
                        db.execute('INSERT INTO monitors(id,site,target,login_path,status_path,user_field,password_field) VALUES(:id,:site,:target,:login_path,:status_path,:user_field,:password_field)', m)
                        event(db, m, 'connect', '登录成功，等待首次检查')
                WAKE.set()
                return self.send_json({'ok': True})
            if path in ('/api/toggle', '/api/delete'):
                mid = data.get('id')
                with LOCK, connect() as db:
                    m = db.execute('SELECT * FROM monitors WHERE id=?', (mid,)).fetchone()
                    if not m:
                        return self.send_json({'error': '监控不存在'}, 404)
                    if path == '/api/delete':
                        db.execute('DELETE FROM monitors WHERE id=?', (mid,))
                        SESSIONS.pop(mid, None)
                        event(db, m, 'delete', '已移除监控')
                    else:
                        if mid not in SESSIONS:
                            raise ValueError('登录会话已失效，请移除后重新添加监控')
                        db.execute('UPDATE monitors SET enabled=1-enabled WHERE id=?', (mid,))
                        event(db, m, 'pause', '已恢复监控' if not m['enabled'] else '已暂停监控')
                WAKE.set()
                return self.send_json({'ok': True})
            if path == '/api/refresh':
                WAKE.set()
                return self.send_json({'ok': True})
            return self.send_json({'error': 'Not found'}, 404)
        except (ValueError, TypeError, KeyError) as exc:
            return self.send_json({'error': str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    try:
        validate_assets()
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    init()
    with connect() as db:
        db.execute("UPDATE monitors SET state='disconnected',ip=NULL,error='服务已重启，请移除后重新登录'")
    threading.Thread(target=worker, daemon=True).start()
    print(f'Local Monitor running on http://{args.host}:{args.port}', flush=True)
    with ThreadingHTTPServer((args.host, args.port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nLocal Monitor 已停止。', flush=True)


if __name__ == '__main__':
    main()
