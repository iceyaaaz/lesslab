"""完整应用的真实会话与跨账号测试。仅用内存 SQLite，禁止读取 .env 或调用模型。

SQLite 适配器不模拟 MySQL FOR UPDATE；并发锁与 DDL 需另做 MySQL 验证。
"""
import json
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import test_archive as archive_support
import test_current_goal as goal_support
from security import (AuthConfig, COOKIE_NAME, hash_password, initialize_owner,
                      now_seconds, token_digest, verify_password)

PASSWORD = "a-long-local-test-password"
PASSWORD_HASH = hash_password(PASSWORD)
SCHEMA = [
    "CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL)",
    "CREATE TABLE user_sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL)",
    "CREATE TABLE auth_control(id INTEGER PRIMARY KEY CHECK(id=1), owner_id INTEGER REFERENCES users(id))",
    "CREATE TABLE auth_throttle(bucket_key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, window_start INTEGER NOT NULL)",
    goal_support.SCHEMA,
    "CREATE TABLE study_plan_progress(plan_id INTEGER NOT NULL, resource_id INTEGER NOT NULL, completed INTEGER DEFAULT 0, completed_at TEXT, PRIMARY KEY(plan_id,resource_id))",
    "CREATE TABLE current_goal(id INTEGER PRIMARY KEY, title TEXT, success_criteria TEXT DEFAULT '', due_date TEXT, daily_minutes INTEGER DEFAULT 30, version INTEGER DEFAULT 0)",
]


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.fixture = archive_support.ArchiveTests('test_archive_and_restore_preserve_unread_status')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture.real_engine
        self.app = self.fixture.main.app
        self.app.dependency_overrides.clear()  # 本组测试不绕过真实认证。
        self.client = self.fixture.client
        self.client.headers['Origin'] = 'http://testserver'
        self.app.state.auth_config = AuthConfig(origin='http://testserver', allow_registration=True)
        with self.engine.begin() as conn:
            for statement in SCHEMA:
                conn.execute(text(statement))
            conn.execute(text('INSERT INTO users(id,username,password_hash) VALUES(:id,:name,:password)'), [
                {'id': 1, 'name': 'alice', 'password': PASSWORD_HASH},
                {'id': 2, 'name': 'bob', 'password': PASSWORD_HASH},
            ])
            conn.execute(text('INSERT INTO auth_control(id,owner_id) VALUES(1,1)'))
            conn.execute(text("INSERT INTO user_goals(user_id,title) VALUES (1,'Alice 的目标'),(2,'Bob 的目标')"))
            conn.execute(text("INSERT INTO current_goal(id,title,daily_minutes,version) VALUES(1,'旧版目标',45,3)"))
            conn.execute(text("INSERT INTO resources(id,title,url,status,estimated_minutes,owner_id) VALUES(4,'Bob 私人资料','https://example.com/bob','unread',10,2)"))
            for plan_id, user_id, resource_id in [(1, 1, 1), (2, 2, 4)]:
                items = json.dumps([dict(id=resource_id, title=f'user {user_id} resource', url='https://example.com', estimated_minutes=20, reason='offline')])
                conn.execute(text("INSERT INTO study_plans(id,goal,budget_minutes,total_minutes,source,items,owner_id) VALUES(:id,'项目',30,20,'manual',:items,:owner)"), {'id': plan_id, 'items': items, 'owner': user_id})

    def login(self, username='alice', password=PASSWORD):
        response = self.client.post('/auth/login', json={'username': username, 'password': password})
        self.assertEqual(response.status_code, 200, response.text)
        me = self.client.get('/auth/me')
        self.assertEqual(me.status_code, 200, me.text)
        self.client.headers['X-CSRF-Token'] = me.json()['csrf_token']
        return response

    def count(self, table):
        with self.engine.connect() as conn:
            return conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar_one()

    def test_anonymous_cannot_access_any_private_api(self):
        operations = [
            ('GET', '/resources', None), ('POST', '/resources', dict(title='valid', url='https://example.com')),
            ('PATCH', '/resources/1/status', {'status': 'done'}),
            ('PATCH', '/resources/1/archive', {'archived': True}),
            ('GET', '/study-plan', None), ('POST', '/ai-study-plan', {'goal': 'Python', 'minutes': 30}),
            ('GET', '/study-plans', None), ('GET', '/study-plans/1', None),
            ('POST', '/study-plans', {'goal': 'Python', 'budget_minutes': 30, 'items': [{'id': 1}]}),
            ('GET', '/current-goal', None),
            ('PUT', '/current-goal', {'title': '我的目标', 'version': 0}),
            ('GET', '/study-plans/1/progress', None),
            ('PUT', '/study-plans/1/tasks/1/completion', {'completed': True}),
            ('GET', '/health/db', None), ('GET', '/auth/me', None), ('POST', '/auth/logout', None),
        ]
        for method, path, body in operations:
            with self.subTest(path=path, method=method):
                self.assertEqual(self.client.request(method, path, json=body).status_code, 401)
        self.fixture.model.assert_not_called()
        self.fixture.config.assert_not_called()

    def test_home_redirects_and_login_page_is_available(self):
        response = self.client.get('/', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/login')
        self.assertEqual(self.client.get('/login').status_code, 200)
        self.login()
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_valid_login_uses_httponly_cookie_and_hashed_session(self):
        response = self.login('ALICE')
        self.assertEqual(response.json(), {'id': 1, 'username': 'alice'})
        cookie = response.headers['set-cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=lax', cookie)
        self.assertIn('Max-Age=28800', cookie)
        token = self.client.cookies.get(COOKIE_NAME)
        with self.engine.connect() as conn:
            stored = conn.execute(text('SELECT token_hash FROM user_sessions')).scalar_one()
        self.assertNotEqual(stored, token)
        self.assertEqual(stored, token_digest(token))
        self.assertNotIn('password', response.text)

    def test_logout_revokes_replayed_cookie(self):
        self.login()
        token = self.client.cookies.get(COOKIE_NAME)
        self.assertEqual(self.client.post('/auth/logout').status_code, 200)
        self.assertEqual(self.count('user_sessions'), 0)
        self.client.cookies.set(COOKIE_NAME, token)
        self.assertEqual(self.client.get('/resources').status_code, 401)

    def test_expired_session_is_rejected(self):
        self.login()
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE user_sessions SET expires_at = :now'), {'now': now_seconds() - 1})
        self.assertEqual(self.client.get('/resources').status_code, 401)

    def test_wrong_and_unknown_password_have_same_error(self):
        responses = [self.client.post('/auth/login', json={'username': name, 'password': 'wrong-password-value'}) for name in ('alice', 'nonexistent')]
        self.assertEqual([x.status_code for x in responses], [401, 401])
        self.assertEqual(responses[0].json(), responses[1].json())
        self.assertEqual(self.count('user_sessions'), 0)

    def test_passwords_are_salted_and_verified(self):
        other = hash_password(PASSWORD)
        self.assertNotEqual(other, PASSWORD_HASH)
        self.assertNotIn(PASSWORD, other)
        self.assertTrue(verify_password(PASSWORD, other))
        self.assertFalse(verify_password('wrong', other))
        self.assertFalse(verify_password(PASSWORD, 'malformed'))

    def test_login_attempt_limit_survives_failed_passwords(self):
        for _ in range(10):
            self.assertEqual(self.client.post('/auth/login', json={'username': 'alice', 'password': 'wrong'}).status_code, 401)
        response = self.client.post('/auth/login', json={'username': 'alice', 'password': PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers['retry-after']), 0)
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE auth_throttle SET window_start = :old'), {'old': now_seconds() - 901})
        self.login()

    def test_ip_attempt_limit_cannot_be_evaded_with_forwarded_header(self):
        for number in range(20):
            response = self.client.post('/auth/login', headers={'X-Forwarded-For': f'1.2.3.{number}'}, json={'username': f'unknown{number}', 'password': 'wrong'})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code, 429)

    def test_cross_origin_and_missing_origin_login_rejected(self):
        for origin in ('https://evil.example', 'null', ''):
            self.assertEqual(self.client.post('/auth/login', headers={'Origin': origin}, json={'username': 'alice', 'password': PASSWORD}).status_code, 403)
        self.assertEqual(self.count('user_sessions'), 0)

    def test_forged_host_is_rejected(self):
        self.assertEqual(self.client.get('/auth/status', headers={'Host': 'evil.example'}).status_code, 400)

    def test_csrf_required_for_mutations_and_logout(self):
        self.login()
        for csrf in ('', 'incorrect'):
            response = self.client.patch('/resources/1/status', headers={'X-CSRF-Token': csrf}, json={'status': 'done'})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post('/auth/logout', headers={'X-CSRF-Token': ''}).status_code, 403)
        self.assertEqual(self.client.patch('/resources/1/status', json={'status': 'done'}).status_code, 200)

    def test_old_csrf_is_invalid_after_account_change(self):
        self.login()
        old_csrf = self.client.headers['X-CSRF-Token']
        self.login('bob')
        self.assertEqual(self.client.patch('/resources/4/status', headers={'X-CSRF-Token': old_csrf}, json={'status': 'done'}).status_code, 403)

    def test_private_responses_are_not_cached(self):
        self.login()
        response = self.client.get('/resources')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['x-frame-options'], 'DENY')

    def test_validation_never_echoes_password(self):
        secret = 'shortSecret'
        response = self.client.post('/auth/register', json={'username': 'newuser', 'password': secret})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)
        response = self.client.post('/auth/login', json={'username': 'bad user!', 'password': PASSWORD})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(PASSWORD, response.text)

    def test_register_creates_empty_goal_without_claiming_old_data(self):
        response = self.client.post('/auth/register', json={'username': 'Charlie', 'password': PASSWORD})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['username'], 'charlie')
        self.login('charlie')
        self.assertEqual(self.client.get('/resources').json()['items'], [])
        self.assertEqual(self.client.get('/study-plans').json()['items'], [])
        self.assertEqual(self.client.get('/current-goal').json(), {'goal': None, 'version': 0})

    def test_registration_can_be_disabled(self):
        self.app.state.auth_config = AuthConfig(origin='http://testserver')
        self.assertFalse(self.client.get('/auth/status').json()['registration_enabled'])
        self.assertEqual(self.client.post('/auth/register', json={'username': 'newuser', 'password': PASSWORD}).status_code, 403)

    def test_uninitialized_site_cannot_be_claimed_through_register(self):
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE auth_control SET owner_id = NULL'))
        self.assertTrue(self.client.get('/auth/status').json()['setup_required'])
        self.assertEqual(self.client.post('/auth/register', json={'username': 'newowner', 'password': PASSWORD}).status_code, 503)
        self.assertEqual(self.count('users'), 2)

    def test_duplicate_registration_is_case_insensitive(self):
        self.assertEqual(self.client.post('/auth/register', json={'username': 'ALICE', 'password': PASSWORD}).status_code, 409)
        self.assertEqual(self.count('users'), 2)

    def test_resource_lists_and_rule_plan_are_user_scoped(self):
        self.login()
        self.assertEqual([x['id'] for x in self.client.get('/resources').json()['items']], [2, 1])
        self.assertEqual([x['id'] for x in self.client.get('/resources?archived=true').json()['items']], [3])
        self.assertEqual([x['id'] for x in self.client.get('/study-plan').json()['items']], [1])
        self.login('bob')
        self.assertEqual([x['id'] for x in self.client.get('/resources').json()['items']], [4])
        self.assertEqual(self.client.get('/resources?archived=true').json()['items'], [])
        self.assertEqual([x['id'] for x in self.client.get('/study-plan').json()['items']], [4])

    def test_create_cannot_choose_another_owner(self):
        self.login('bob')
        body = {'title': 'new', 'url': 'https://example.com', 'estimated_minutes': 5}
        self.assertEqual(self.client.post('/resources', json={**body, 'owner_id': 1}).status_code, 422)
        response = self.client.post('/resources', json=body)
        self.assertEqual(response.status_code, 201)
        with self.engine.connect() as conn:
            owner = conn.execute(text('SELECT owner_id FROM resources WHERE id=:id'), {'id': response.json()['id']}).scalar_one()
        self.assertEqual(owner, 2)

    def test_cross_user_resource_mutations_return_not_found(self):
        self.login('bob')
        self.assertEqual(self.client.patch('/resources/1/status', json={'status': 'done'}).status_code, 404)
        self.assertEqual(self.client.patch('/resources/1/archive', json={'archived': True}).status_code, 404)
        with self.engine.connect() as conn:
            row = conn.execute(text('SELECT status, archived_at FROM resources WHERE id=1')).one()
        self.assertEqual(tuple(row), ('unread', None))

    def test_plans_and_progress_cannot_be_read_or_changed_by_another_user(self):
        self.login('bob')
        self.assertEqual([x['id'] for x in self.client.get('/study-plans').json()['items']], [2])
        self.assertEqual(self.client.get('/study-plans/1').status_code, 404)
        self.assertEqual(self.client.get('/study-plans/1/progress').status_code, 404)
        self.assertEqual(self.client.put('/study-plans/1/tasks/1/completion', json={'completed': True}).status_code, 404)
        self.assertEqual(self.count('study_plan_progress'), 0)
        self.assertEqual(self.client.put('/study-plans/2/tasks/4/completion', json={'completed': True}).status_code, 200)

    def test_saving_plan_rejects_other_users_resources(self):
        self.login('bob')
        body = {'goal': 'Python', 'budget_minutes': 30, 'items': [{'id': 1}]}
        self.assertEqual(self.client.post('/study-plans', json=body).status_code, 409)
        self.assertEqual(self.count('study_plans'), 2)
        body['items'] = [{'id': 4}]
        saved = self.client.post('/study-plans', json=body)
        self.assertEqual(saved.status_code, 201)
        self.login('alice')
        self.assertEqual(self.client.get('/study-plans/' + str(saved.json()['id'])).status_code, 404)

    def test_goals_are_separate_and_versioned_per_user(self):
        self.login('bob')
        self.assertEqual(self.client.get('/current-goal').json()['goal']['title'], 'Bob 的目标')
        self.assertEqual(self.client.put('/current-goal', json={'title': 'Bob 新目标', 'version': 0}).status_code, 200)
        self.login('alice')
        goal = self.client.get('/current-goal').json()
        self.assertEqual(goal['goal']['title'], 'Alice 的目标')
        self.assertEqual(goal['version'], 0)

    def test_ai_only_receives_logged_in_users_candidates(self):
        self.login('bob')
        self.fixture.config.side_effect = None
        self.fixture.config.return_value = {'DEEPSEEK_API_KEY': 'offline-only'}
        self.fixture.model.side_effect = None
        self.fixture.model.return_value = httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"items":[{"id":4,"reason":"相关"}]}'}}]})
        response = self.client.post('/ai-study-plan', json={'goal': 'Python', 'minutes': 30})
        self.assertEqual(response.status_code, 200)
        task = json.loads(self.fixture.model.call_args.kwargs['json']['messages'][1]['content'])
        self.assertEqual([x['id'] for x in task['candidates']], [4])

    def test_database_errors_do_not_leak_secrets(self):
        self.login()
        with patch.object(self.app.state.engine, 'connect', side_effect=SQLAlchemyError('private-password')):
            response = self.client.get('/resources')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-password', response.text)

    def test_secure_cookie_configuration(self):
        self.app.state.auth_config = AuthConfig(origin='https://testserver', cookie_secure=True)
        response = self.client.post('/auth/login', headers={'Origin': 'https://testserver'}, json={'username': 'alice', 'password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Secure', response.headers['set-cookie'])
        with self.assertRaises(ValueError):
            AuthConfig(origin='https://example.com', cookie_secure=False)
        with self.assertRaises(ValueError):
            AuthConfig(origin='http://example.com', cookie_secure=False)

    def test_owner_initialization_preserves_ids_snapshots_and_progress(self):
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE auth_control SET owner_id = NULL'))
            conn.execute(text('UPDATE resources SET owner_id = NULL WHERE owner_id=1'))
            conn.execute(text('UPDATE study_plans SET owner_id = NULL WHERE owner_id=1'))
            before = conn.execute(text('SELECT items FROM study_plans WHERE id=1')).scalar_one()
            conn.execute(text("INSERT INTO study_plan_progress VALUES(1,1,1,'2026-09-29 10:00:00')"))
        owner = initialize_owner(self.app.state.engine, 'realowner', PASSWORD)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT owner_id FROM resources WHERE id=1')).scalar_one(), owner)
            self.assertEqual(conn.execute(text('SELECT owner_id FROM study_plans WHERE id=1')).scalar_one(), owner)
            self.assertEqual(conn.execute(text('SELECT items FROM study_plans WHERE id=1')).scalar_one(), before)
            self.assertEqual(conn.execute(text('SELECT completed FROM study_plan_progress WHERE plan_id=1')).scalar_one(), 1)
            self.assertEqual(conn.execute(text('SELECT owner_id FROM resources WHERE id=4')).scalar_one(), 2)
        self.login('realowner')
        goal = self.client.get('/current-goal').json()
        self.assertEqual((goal['goal']['title'], goal['goal']['daily_minutes'], goal['version']), ('旧版目标', 45, 3))
        with self.assertRaises(ValueError):
            initialize_owner(self.app.state.engine, 'anotherowner', PASSWORD)

    def test_owner_setup_rolls_back_on_missing_legacy_goal(self):
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE auth_control SET owner_id = NULL'))
            conn.execute(text('UPDATE resources SET owner_id = NULL'))
            conn.execute(text('DELETE FROM current_goal'))
        with self.assertRaises(ValueError):
            initialize_owner(self.app.state.engine, 'realowner', PASSWORD)
        self.assertEqual(self.count('users'), 2)
        with self.engine.connect() as conn:
            self.assertIsNone(conn.execute(text('SELECT owner_id FROM resources WHERE id=1')).scalar_one())
            self.assertIsNone(conn.execute(text('SELECT owner_id FROM auth_control')).scalar_one())


if __name__ == '__main__':
    unittest.main()
