"""在内存 SQLite 中执行计划进度查询，不读取真实 .env 或调用模型。"""
import json
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import test_archive as archive_support


SCHEMA = '''CREATE TABLE study_plan_progress (
    plan_id INTEGER NOT NULL REFERENCES study_plans(id),
    resource_id INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0, 1)),
    completed_at TEXT,
    PRIMARY KEY(plan_id, resource_id),
    CHECK((completed = 0 AND completed_at IS NULL) OR
          (completed = 1 AND completed_at IS NOT NULL))
)'''


class PlanProgressTests(unittest.TestCase):
    def setUp(self):
        self.fixture = archive_support.ArchiveTests('test_archive_and_restore_preserve_unread_status')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = self.fixture.client
        self.engine = self.fixture.real_engine
        self.module = self.fixture.modules['progress_routes']
        self.items = [
            {'id': 1, 'title': 'Python 函数', 'url': 'https://example.com/1', 'estimated_minutes': 20, 'reason': '先练习函数'},
            {'id': 3, 'title': 'Python 练习', 'url': 'https://example.com/3', 'estimated_minutes': 5, 'reason': '再完成练习'},
        ]
        with self.engine.begin() as conn:
            conn.execute(text(SCHEMA))
            for plan_id in (1, 2):
                conn.execute(text('INSERT INTO study_plans (id,goal,budget_minutes,total_minutes,source,items) VALUES (:id,\'Python 项目\',30,25,\'manual\',:items)'), {'id': plan_id, 'items': json.dumps(self.items, ensure_ascii=False)})

    def tearDown(self):
        self.fixture.model.assert_not_called()

    def read(self, plan_id=1):
        return self.client.get(f'/study-plans/{plan_id}/progress')

    def change(self, value=True, plan_id=1, resource_id=1):
        return self.client.put(f'/study-plans/{plan_id}/tasks/{resource_id}/completion', json={'completed': value})

    def test_old_plan_starts_incomplete(self):
        response = self.read()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total_count'], 2)
        self.assertEqual(data['completed_count'], 0)
        self.assertEqual([x['resource_id'] for x in data['items']], [1, 3])
        self.assertTrue(all(not x['completed'] and x['completed_at'] is None for x in data['items']))

    def test_reading_does_not_write_progress(self):
        self.read()
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT COUNT(*) FROM study_plan_progress')).scalar_one(), 0)

    def test_completion_survives_new_request(self):
        response = self.change()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.read().json())
        self.assertEqual(response.json()['completed_count'], 1)
        self.assertIsNotNone(response.json()['items'][0]['completed_at'])

    def test_uncheck_clears_completion_time(self):
        self.change()
        data = self.change(False).json()
        self.assertEqual(data['completed_count'], 0)
        self.assertIsNone(data['items'][0]['completed_at'])

    def test_repeat_completion_is_idempotent(self):
        self.change()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE study_plan_progress SET completed_at = '2026-01-01 12:00:00' WHERE plan_id = 1 AND resource_id = 1"))
        first = self.change().json()
        self.assertEqual(first, self.change().json())
        self.assertEqual(first['items'][0]['completed_at'], '2026-01-01 12:00:00')

    def test_tasks_cannot_be_updated_outside_plan(self):
        self.assertEqual(self.change(resource_id=2).status_code, 404)
        self.assertEqual(self.read().json()['completed_count'], 0)

    def test_missing_plan_is_404(self):
        self.assertEqual(self.read(99).status_code, 404)
        self.assertEqual(self.change(plan_id=99).status_code, 404)

    def test_invalid_requests_are_rejected(self):
        for payload in ({}, {'completed': 'false'}, {'completed': 1}, {'completed': True, 'title': 'rewrite'}):
            with self.subTest(payload=payload):
                response = self.client.put('/study-plans/1/tasks/1/completion', json=payload)
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.change(resource_id=0).status_code, 422)
        self.assertEqual(self.read(0).status_code, 422)

    def test_same_resource_in_two_plans_has_independent_progress(self):
        self.change(plan_id=1)
        self.assertEqual(self.read(1).json()['completed_count'], 1)
        self.assertEqual(self.read(2).json()['completed_count'], 0)

    def test_snapshot_and_resource_status_are_unchanged(self):
        before = self.client.get('/study-plans/1').json()
        self.change()
        self.assertEqual(before, self.client.get('/study-plans/1').json())
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT status FROM resources WHERE id=1')).scalar_one(), 'unread')

    def test_archived_resource_can_still_complete_historical_task(self):
        response = self.change(resource_id=3)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['items'][1]['completed'])

    def test_summary_counts_all_completed_tasks(self):
        self.change(resource_id=1)
        self.change(resource_id=3)
        data = self.read().json()
        self.assertEqual(data['completed_count'], data['total_count'])

    def test_database_errors_do_not_expose_details(self):
        broken = MagicMock()
        broken.connect.side_effect = SQLAlchemyError('private-detail')
        broken.begin.side_effect = SQLAlchemyError('private-detail')
        with patch.object(self.module, 'engine', broken):
            for response in (self.read(), self.change()):
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('private-detail', response.text)


if __name__ == '__main__':
    unittest.main()
