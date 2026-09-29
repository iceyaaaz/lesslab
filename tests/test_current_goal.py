"""当前目标的离线测试；使用内存数据库，不读取真实配置、不调用模型。"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

SCHEMA = '''CREATE TABLE current_goal (
    id INTEGER PRIMARY KEY CHECK(id = 1), title TEXT,
    success_criteria TEXT NOT NULL DEFAULT '', due_date TEXT,
    daily_minutes INTEGER NOT NULL DEFAULT 30 CHECK(daily_minutes BETWEEN 1 AND 600),
    version INTEGER NOT NULL DEFAULT 0
)'''


class CurrentGoalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            conn.execute(text(SCHEMA))
            conn.execute(text('INSERT INTO current_goal(id) VALUES(1)'))
        database = types.ModuleType('database')
        database.engine = self.engine
        source = Path(__file__).resolve().parents[1] / 'goal_routes.py'
        spec = importlib.util.spec_from_file_location('_current_goal_test', source)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'database': database}):
            spec.loader.exec_module(self.module)
        app = FastAPI()
        app.include_router(self.module.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        guard = patch('httpx.post', side_effect=AssertionError('目标管理不应调用模型'))
        self.model = guard.start()
        self.addCleanup(guard.stop)
        self.payload = dict(title='独立完成 Python 项目', success_criteria='能演示新增和查询资料', due_date='2026-10-12', daily_minutes=45, version=0)

    def tearDown(self):
        self.model.assert_not_called()

    def save(self, **changes):
        return self.client.put('/current-goal', json={**self.payload, **changes})

    def read(self):
        return self.client.get('/current-goal')

    def test_initial_goal_is_empty(self):
        self.assertEqual(self.read().json(), {'goal': None, 'version': 0})

    def test_save_is_persisted_and_readable(self):
        response = self.save()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.read().json())
        self.assertEqual(response.json()['version'], 1)
        self.assertEqual(response.json()['goal'], {k: v for k, v in self.payload.items() if k != 'version'})

    def test_edit_and_clear_optional_fields(self):
        self.save()
        response = self.save(version=1, title='完成一个小工具', due_date=None, success_criteria='', daily_minutes=20)
        self.assertEqual(response.status_code, 200)
        goal = response.json()['goal']
        self.assertEqual(goal['title'], '完成一个小工具')
        self.assertIsNone(goal['due_date'])
        self.assertEqual(goal['success_criteria'], '')
        self.assertEqual(response.json()['version'], 2)

    def test_stale_window_cannot_overwrite_new_goal(self):
        first = self.save().json()
        self.assertEqual(self.save(title='旧窗口的内容').status_code, 409)
        self.assertEqual(self.read().json(), first)

    def test_repeated_network_submission_does_not_overwrite(self):
        self.save()
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.read().json()['version'], 1)

    def test_invalid_inputs_leave_saved_goal_unchanged(self):
        for update in ({'title': ' '}, {'title': 'a'}, {'title': 'x' * 201}, {'success_criteria': 'x' * 251}, {'daily_minutes': 0}, {'daily_minutes': 601}, {'daily_minutes': '30'}, {'daily_minutes': True}, {'version': -1}, {'version': '0'}, {'unexpected': 'value'}):
            with self.subTest(update=update):
                self.assertEqual(self.save(**update).status_code, 422)
        self.assertIsNone(self.read().json()['goal'])

    def test_limits_fit_existing_ai_goal_input(self):
        response = self.save(title='目' * 200, success_criteria='标' * 250, daily_minutes=600)
        self.assertEqual(response.status_code, 200)
        goal = response.json()['goal']
        self.assertLessEqual(len(goal['title'] + '\n验收标准：' + goal['success_criteria']), 500)
        self.assertEqual(self.save(version=1, daily_minutes=1).status_code, 200)

    def test_strings_are_trimmed(self):
        goal = self.save(title='  我的项目  ', success_criteria='  可运行  ').json()['goal']
        self.assertEqual(goal['title'], '我的项目')
        self.assertEqual(goal['success_criteria'], '可运行')

    def test_invalid_dates_are_rejected(self):
        for value in ('2026-02-30', '2026/09/27', '2026-9-27', '', 0, '2026-09-27T00:00:00'):
            with self.subTest(value=value):
                self.assertEqual(self.save(due_date=value).status_code, 422)

    def test_overdue_goal_can_still_be_edited(self):
        self.assertEqual(self.save(due_date='2020-01-01').status_code, 200)

    def test_missing_required_version_is_rejected(self):
        payload = dict(self.payload)
        del payload['version']
        self.assertEqual(self.client.put('/current-goal', json=payload).status_code, 422)

    def test_missing_seed_reports_setup_error(self):
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM current_goal'))
        self.assertEqual(self.read().status_code, 503)
        self.assertEqual(self.save().status_code, 503)

    def test_database_errors_are_sanitized(self):
        engine = MagicMock()
        engine.connect.side_effect = SQLAlchemyError('private-database-detail')
        engine.begin.side_effect = SQLAlchemyError('private-database-detail')
        with patch.object(self.module, 'engine', engine):
            for response in (self.read(), self.save()):
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('private-database-detail', response.text)


if __name__ == '__main__':
    unittest.main()
