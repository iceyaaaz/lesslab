"""离线执行归档与计划查询，使用内存 SQLite，不读取 .env 或调用模型。

SQLite 不支持 FOR UPDATE，适配器仅移除锁语法；行锁语义仍需 MySQL 验证。
"""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from auth_test_support import authorize
from security import AuthConfig
from unittest.mock import patch, MagicMock

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, create_engine, text, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool


class SQLiteAdapter:
    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def connect(self):
        with self.engine.connect() as connection:
            yield connection

    @contextmanager
    def begin(self):
        with self.engine.begin() as connection:
            class Writer:
                def execute(self, statement, params=None):
                    sql = str(statement)
                    if 'FOR UPDATE' in sql:
                        statement = text(sql.replace('FOR UPDATE', ''))
                        if ':resource_ids' in sql or '__[POSTCOMPILE_resource_ids]' in sql:
                            statement = text(sql.replace('FOR UPDATE', '').replace('__[POSTCOMPILE_resource_ids]', ':resource_ids')).bindparams(bindparam('resource_ids', expanding=True))
                    return connection.execute(statement, params or {})
            yield Writer()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.real_engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        event.listen(self.real_engine, 'connect', lambda conn, _: conn.create_function('JSON_LENGTH', 1, lambda value: len(json.loads(value))))
        self.addCleanup(self.real_engine.dispose)
        with self.real_engine.begin() as conn:
            conn.execute(text('CREATE TABLE resources (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, url TEXT, owner_id INTEGER DEFAULT 1, status TEXT DEFAULT \'unread\', estimated_minutes INTEGER, archived_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)'))
            conn.execute(text('CREATE TABLE study_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT, owner_id INTEGER DEFAULT 1, budget_minutes INTEGER, total_minutes INTEGER, source TEXT, items TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)'))
            conn.execute(text('INSERT INTO resources (id,title,url,status,estimated_minutes,archived_at) VALUES (:id,:title,:url,:status,:minutes,:archived)'), [
                dict(id=1, title='Python 函数', url='https://example.com/1', status='unread', minutes=20, archived=None),
                dict(id=2, title='Python 基础', url='https://example.com/2', status='done', minutes=10, archived=None),
                dict(id=3, title='Python 练习', url='https://example.com/3', status='unread', minutes=5, archived='2026-09-01 12:00:00'),
            ])
        database = types.ModuleType('database')
        database.engine = SQLiteAdapter(self.real_engine)
        database.auth_config = AuthConfig(origin="http://testserver")
        root = Path(__file__).resolve().parents[1]
        with patch.dict(sys.modules, {'database': database}):
            self.modules = {}
            for name in ('ai_routes', 'plan_routes', 'archive_routes', 'goal_routes', 'progress_routes'):
                spec = importlib.util.spec_from_file_location(name, root / (name + '.py'))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.modules[name] = module
            with patch.dict(sys.modules, self.modules):
                spec = importlib.util.spec_from_file_location('_main_archive_test', root / 'main.py')
                self.main = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self.main)
        authorize(self.main.app)
        self.client = TestClient(self.main.app)
        self.addCleanup(self.client.close)
        for target, attribute in ((self.modules['ai_routes'], 'dotenv_values'), (httpx, 'post')):
            guard = patch.object(target, attribute, side_effect=AssertionError('禁止读取真实配置或发送模型请求'))
            mocked = guard.start()
            self.addCleanup(guard.stop)
            if attribute == 'post': self.model = mocked
            else: self.config = mocked

    def archive(self, resource_id, value=True):
        return self.client.patch(f'/resources/{resource_id}/archive', json={'archived': value})

    def test_archive_and_restore_preserve_unread_status(self):
        response = self.archive(1)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()['archived_at'])
        self.assertEqual(response.json()['status'], 'unread')
        self.assertEqual([x['id'] for x in self.client.get('/resources').json()['items']], [2])
        restored = self.archive(1, False).json()
        self.assertIsNone(restored['archived_at'])
        self.assertEqual(restored['status'], 'unread')

    def test_done_status_survives_roundtrip(self):
        self.assertEqual(self.archive(2).json()['status'], 'done')
        self.assertEqual(self.archive(2, False).json()['status'], 'done')

    def test_repeated_archive_and_restore_are_idempotent(self):
        first = self.archive(3).json()
        second = self.archive(3).json()
        self.assertEqual(first['archived_at'], '2026-09-01 12:00:00')
        self.assertEqual(first, second)
        self.assertEqual(self.archive(3, False).json(), self.archive(3, False).json())

    def test_archive_view_is_separate_from_active_view(self):
        self.assertEqual([x['id'] for x in self.client.get('/resources?archived=true').json()['items']], [3])
        self.assertEqual([x['id'] for x in self.client.get('/resources?archived=false').json()['items']], [2, 1])

    def test_filter_runs_before_limit(self):
        with self.real_engine.begin() as conn:
            conn.execute(text("INSERT INTO resources(title,archived_at) VALUES ('later archived', '2026-09-02')"), [{} for _ in range(101)])
        self.assertEqual([x['id'] for x in self.client.get('/resources').json()['items']], [2, 1])

    def test_rule_plan_excludes_archive_and_includes_restored_item(self):
        self.assertEqual([x['id'] for x in self.client.get('/study-plan?minutes=30').json()['items']], [1])
        self.archive(3, False)
        self.assertEqual([x['id'] for x in self.client.get('/study-plan?minutes=30').json()['items']], [3, 1])

    def test_no_model_call_when_only_archived_or_done_candidates_exist(self):
        self.archive(1)
        response = self.client.post('/ai-study-plan', json={'goal': 'Python', 'minutes': 30})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'no_candidates')
        self.config.assert_not_called()
        self.model.assert_not_called()

    def test_ai_receives_only_unarchived_candidates(self):
        self.config.side_effect = None
        self.config.return_value = {'DEEPSEEK_API_KEY': 'offline-test'}
        self.model.side_effect = None
        self.model.return_value = httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"items":[{"id":1,"reason":"相关"}]}'}}]})
        response = self.client.post('/ai-study-plan', json={'goal': 'Python', 'minutes': 30})
        self.assertEqual(response.status_code, 200)
        payload = self.model.call_args.kwargs['json']
        candidates = json.loads(payload['messages'][1]['content'])['candidates']
        self.assertEqual([x['id'] for x in candidates], [1])

    def test_saving_archived_resource_fails_then_restore_allows_save(self):
        payload = {'goal': 'Python', 'budget_minutes': 30, 'items': [{'id': 3}]}
        response = self.client.post('/study-plans', json=payload)
        self.assertEqual(response.status_code, 409)
        self.archive(3, False)
        response = self.client.post('/study-plans', json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['total_minutes'], 5)

    def test_historical_snapshot_survives_archive(self):
        saved = self.client.post('/study-plans', json={'goal': 'Python', 'budget_minutes': 30, 'items': [{'id': 1}]}).json()
        self.archive(1)
        found = self.client.get(f'/study-plans/{saved["id"]}').json()
        self.assertEqual(found, saved)

    def test_missing_resource_is_404(self):
        self.assertEqual(self.archive(999).status_code, 404)

    def test_invalid_input_does_not_change_data(self):
        for payload in ({'archived': 'false'}, {'archived': 1}, {}, {'archived': True, 'status': 'done'}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.patch('/resources/1/archive', json=payload).status_code, 422)
        self.assertEqual(self.archive(0).status_code, 422)
        self.assertEqual(self.client.get('/resources?archived=wrong').status_code, 422)
        self.assertEqual(len(self.client.get('/resources').json()['items']), 2)

    def test_database_failure_is_reported_without_leaking_details(self):
        broken = MagicMock()
        broken.begin.side_effect = SQLAlchemyError('private-detail')
        with patch.object(self.modules['archive_routes'], 'engine', broken):
            response = self.archive(1)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-detail', response.text)


if __name__ == '__main__':
    unittest.main()
