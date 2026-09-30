"""部署配置测试：只读临时目录中的模拟 .env，不访问数据库、Render 或模型。"""
import importlib.util
import os
from pathlib import Path
import shutil
import ssl
import sys
import tempfile
import unittest
from unittest.mock import patch

import certifi

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        shutil.copyfile(ROOT / 'database.py', self.directory / 'database.py')
        self.env = dict(DB_HOST='db.example.com', DB_PORT='12345', DB_USER='test-user',
                        DB_PASSWORD='test-password', DB_NAME='lesslab')

    def load(self, env=None):
        spec = importlib.util.spec_from_file_location('_deployment_database', self.directory / 'database.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {**self.env, **(env or {})}, clear=True), patch('sqlalchemy.create_engine') as factory:
            spec.loader.exec_module(module)
        return module, factory.call_args

    def test_local_configuration_still_uses_existing_defaults(self):
        module, call = self.load()
        self.assertEqual(module.auth_config.origin, 'http://127.0.0.1:8000')
        self.assertFalse(module.auth_config.cookie_secure)
        self.assertNotIn('ssl', call.kwargs['connect_args'])

    def test_cloud_credentials_override_env_file(self):
        (self.directory / '.env').write_text('DB_HOST=old.example.com\nDB_PASSWORD=old-test-password\n', encoding='utf-8')
        _, call = self.load()
        url = call.args[0]
        self.assertEqual((url.host, url.port, url.database), ('db.example.com', 12345, 'lesslab'))
        self.assertEqual(url.password, 'test-password')

    def test_render_origin_and_secure_cookie_are_automatic(self):
        module, _ = self.load({'RENDER_EXTERNAL_URL': 'https://demo.onrender.com', 'DB_SSL_CA': certifi.where()})
        self.assertEqual(module.auth_config.origin, 'https://demo.onrender.com')
        self.assertTrue(module.auth_config.cookie_secure)

    def test_explicit_custom_origin_overrides_render_domain(self):
        module, _ = self.load({'RENDER_EXTERNAL_URL': 'https://demo.onrender.com', 'DB_SSL_CA': certifi.where(), 'APP_ORIGIN': 'https://example.com'})
        self.assertEqual(module.auth_config.origin, 'https://example.com')

    def test_cloud_tls_checks_ca_and_server_hostname(self):
        _, call = self.load({'DB_SSL_CA': certifi.where()})
        context = call.kwargs['connect_args']['ssl']
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreater(context.cert_store_stats()['x509_ca'], 0)

    def test_render_without_ca_fails_before_engine_creation(self):
        with self.assertRaisesRegex(ValueError, 'DB_SSL_CA'):
            self.load({'RENDER_EXTERNAL_URL': 'https://demo.onrender.com'})

    def test_missing_or_invalid_ca_never_falls_back_to_plaintext(self):
        invalid = self.directory / 'bad.pem'
        invalid.write_text('not a certificate', encoding='utf-8')
        for filename in (str(self.directory / 'missing.pem'), str(invalid)):
            with self.subTest(filename=filename), self.assertRaises(OSError):
                self.load({'DB_SSL_CA': filename})


if __name__ == '__main__':
    unittest.main()
