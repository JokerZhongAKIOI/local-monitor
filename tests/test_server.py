import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = server.DB
        server.DB = Path(self.temp.name) / 'test.db'
        server.init()
        self.m = dict(id='test', site='goj', target='alice', login_path='/login', status_path='/status', user_field='username', password_field='password')
        with server.connect() as db:
            db.execute('INSERT INTO monitors(id,site,target,login_path,status_path,user_field,password_field) VALUES(:id,:site,:target,:login_path,:status_path,:user_field,:password_field)', self.m)
        server.SESSIONS['test'] = object()

    def tearDown(self):
        server.DB = self.old_db
        server.SESSIONS.clear()
        self.temp.cleanup()

    def row(self):
        with server.connect() as db:
            return dict(db.execute('SELECT * FROM monitors').fetchone())

    def test_personal_login_only_requires_credentials(self):
        for mode in ('personal', None):
            data = dict(site='goj', username='alice', password='test-only')
            if mode:
                data['mode'] = mode
            self.assertTrue(server.prepare_login(data))
            self.assertEqual(data['target'], 'alice')
            self.assertEqual(data['user_field'], 'uname')
            self.assertEqual(data['status_path'], '/home/security')

    def test_missing_password_names_field(self):
        with self.assertRaisesRegex(ValueError, '登录密码'):
            server.prepare_login(dict(site='goj', username='alice'))

    def test_json_still_requires_config(self):
        with self.assertRaisesRegex(ValueError, '监控用户名'):
            server.prepare_login(dict(site='local', username='alice', password='test-only'))

    def test_assets_present(self):
        server.validate_assets()

    def test_missing_assets_has_helpful_message(self):
        with patch('server.ROOT', Path(self.temp.name)):
            with self.assertRaisesRegex(ValueError, 'static 文件夹必须'):
                server.validate_assets()

    def test_endpoint(self):
        for bad in ('//evil.com', 'https://evil.com', '/\\evil.com', '/ok#fragment'):
            with self.assertRaises(ValueError):
                server.endpoint('goj', bad)
        self.assertEqual(server.endpoint('goj', '/api/status'), 'https://www.goj.wiki/api/status')

    def test_online_and_change_log(self):
        with patch('server.request_json', return_value={'online': True, 'ip': '203.0.113.1'}):
            server.poll(self.m)
            server.poll(self.m)
        self.assertEqual(self.row()['ip'], '203.0.113.1')
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 1)

    def test_bad_ip_never_shown(self):
        with patch('server.request_json', return_value={'online': True, 'ip': 'not-an-ip'}):
            server.poll(self.m)
        self.assertEqual(self.row()['state'], 'error')
        self.assertIsNone(self.row()['ip'])

    def test_offline_clears_ip(self):
        with patch('server.request_json', return_value={'online': False, 'ip': '203.0.113.1'}):
            server.poll(self.m)
        self.assertEqual(self.row()['state'], 'offline')
        self.assertIsNone(self.row()['ip'])

    def test_requires_boolean(self):
        with patch('server.request_json', return_value={'online': 'true'}):
            server.poll(self.m)
        self.assertEqual(self.row()['state'], 'error')

    def test_paused_does_not_update(self):
        with server.connect() as db:
            db.execute('UPDATE monitors SET enabled=0')
        with patch('server.request_json', return_value={'online': True}):
            server.poll(self.m)
        self.assertIsNone(self.row()['checked'])


if __name__ == '__main__':
    unittest.main()
