"""保存计划接口的离线测试：使用模拟数据库，不调用模型。"""

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError


class SavedPlanTests(unittest.TestCase):
    def setUp(self):
        database = types.ModuleType("database")
        database.engine = MagicMock()
        source = Path(__file__).resolve().parents[1] / "plan_routes.py"
        spec = importlib.util.spec_from_file_location("_saved_plans_under_test", source)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"database": database}):
            spec.loader.exec_module(self.module)
        self.engine = database.engine
        self.write_connection = self.engine.begin.return_value.__enter__.return_value
        self.read_connection = self.engine.connect.return_value.__enter__.return_value

        app = FastAPI()
        app.include_router(self.module.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        guard = patch("httpx.post", side_effect=AssertionError("保存计划不应调用模型。"))
        self.model_call = guard.start()
        self.addCleanup(guard.stop)

        self.resource = {
            "id": 1, "title": "Python 函数", "url": "https://example.com/1",
            "status": "unread", "estimated_minutes": 20,
        }
        self.payload = {
            "goal": "学习 Python 函数", "budget_minutes": 30,
            "source": "manual", "items": [{"id": 1, "reason": "先学习函数基础。"}],
        }
        self.snapshot = [{
            "id": 1, "title": self.resource["title"], "url": self.resource["url"],
            "estimated_minutes": 20, "reason": self.payload["items"][0]["reason"],
        }]
        self.plan_row = {
            "id": 7, "goal": self.payload["goal"], "budget_minutes": 30,
            "total_minutes": 20, "source": "manual",
            "items": json.dumps(self.snapshot, ensure_ascii=False),
            "created_at": datetime(2026, 9, 26, 12, 0, 0),
        }

    def tearDown(self):
        self.model_call.assert_not_called()

    def set_save_results(self, resources=None):
        query = MagicMock()
        query.mappings.return_value.all.return_value = [self.resource] if resources is None else resources
        inserted = MagicMock()
        inserted.lastrowid = 7
        readback = MagicMock()
        readback.mappings.return_value.one.return_value = self.plan_row
        self.write_connection.execute.side_effect = [query, inserted, readback]

    def save(self):
        return self.client.post("/study-plans", json=self.payload)

    def test_saves_authoritative_snapshot_and_returns_201(self):
        self.set_save_results()
        response = self.save()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], 7)
        self.assertEqual(response.json()["items"], self.snapshot)
        parameters = self.write_connection.execute.call_args_list[1].args[1]
        self.assertEqual(parameters["total_minutes"], 20)
        self.assertEqual(json.loads(parameters["items"]), self.snapshot)
        self.engine.begin.assert_called_once()

    def test_exact_budget_is_accepted(self):
        self.payload["budget_minutes"] = 20
        self.plan_row["budget_minutes"] = 20
        self.set_save_results()
        self.assertEqual(self.save().status_code, 201)

    def test_duplicate_items_are_rejected_before_database_access(self):
        self.payload["items"].append(dict(self.payload["items"][0]))
        self.assertEqual(self.save().status_code, 422)
        self.engine.begin.assert_not_called()

    def test_missing_resource_prevents_insert(self):
        self.set_save_results(resources=[])
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.write_connection.execute.call_count, 1)

    def test_completed_resource_prevents_insert(self):
        self.resource["status"] = "done"
        self.set_save_results()
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.write_connection.execute.call_count, 1)

    def test_missing_duration_prevents_insert(self):
        self.resource["estimated_minutes"] = None
        self.set_save_results()
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.write_connection.execute.call_count, 1)

    def test_changed_duration_over_budget_prevents_insert(self):
        self.resource["estimated_minutes"] = 40
        self.set_save_results()
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.write_connection.execute.call_count, 1)

    def test_invalid_requests_are_rejected(self):
        invalid = [
            {**self.payload, "items": []},
            {**self.payload, "goal": " "},
            {**self.payload, "budget_minutes": 0},
            {**self.payload, "budget_minutes": 601},
            {**self.payload, "budget_minutes": "30"},
            {**self.payload, "source": "unknown"},
            {**self.payload, "total_minutes": 1},
            {**self.payload, "items": [{"id": 1, "estimated_minutes": 1}]},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.post("/study-plans", json=payload)
                self.assertEqual(response.status_code, 422)
        self.engine.begin.assert_not_called()

    def test_ai_plan_item_limit_is_checked(self):
        self.payload["source"] = "ai"
        self.payload["items"] = [{"id": number} for number in range(1, 10)]
        self.assertEqual(self.save().status_code, 422)
        self.engine.begin.assert_not_called()

    def test_snapshot_preserves_order_and_original_text(self):
        second = {**self.resource, "id": 2, "title": "练习", "estimated_minutes": 10}
        request = self.module.SavePlanRequest.model_validate({
            **self.payload, "items": [{"id": 2}, {"id": 1}],
        })
        snapshot, total = self.module.prepare_snapshot(request, [self.resource, second])
        self.assertEqual([item["id"] for item in snapshot], [2, 1])
        self.assertEqual(total, 30)
        self.resource["title"] = "之后修改的标题"
        self.assertEqual(snapshot[1]["title"], "Python 函数")

    def test_detail_decodes_json_and_does_not_query_resources(self):
        self.read_connection.execute.return_value.mappings.return_value.first.return_value = self.plan_row
        response = self.client.get("/study-plans/7")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], self.snapshot)
        self.read_connection.execute.assert_called_once()
        self.assertEqual(self.read_connection.execute.call_args.args[1], {"plan_id": 7})

    def test_missing_plan_returns_404(self):
        self.read_connection.execute.return_value.mappings.return_value.first.return_value = None
        self.assertEqual(self.client.get("/study-plans/99").status_code, 404)

    def test_invalid_plan_id_returns_422(self):
        self.assertEqual(self.client.get("/study-plans/0").status_code, 422)
        self.engine.connect.assert_not_called()

    def test_history_is_paginated(self):
        rows = [{"id": 9}, {"id": 8}, {"id": 7}]
        self.read_connection.execute.return_value.mappings.return_value.all.return_value = rows
        response = self.client.get("/study-plans?limit=2&offset=4")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], rows[:2])
        self.assertTrue(response.json()["has_more"])
        self.assertEqual(self.read_connection.execute.call_args.args[1], {"limit": 3, "offset": 4})

    def test_empty_history_is_valid(self):
        self.read_connection.execute.return_value.mappings.return_value.all.return_value = []
        response = self.client.get("/study-plans")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        self.assertFalse(response.json()["has_more"])

    def test_invalid_pagination_is_rejected(self):
        for query in ("limit=0", "limit=101", "offset=-1"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/study-plans?" + query).status_code, 422)
        self.engine.connect.assert_not_called()

    def test_database_failure_is_reported(self):
        self.engine.begin.side_effect = SQLAlchemyError("simulation")
        self.engine.connect.side_effect = SQLAlchemyError("simulation")
        self.assertEqual(self.save().status_code, 503)
        self.assertEqual(self.client.get("/study-plans").status_code, 503)
        self.assertEqual(self.client.get("/study-plans/7").status_code, 503)


if __name__ == "__main__":
    unittest.main()
