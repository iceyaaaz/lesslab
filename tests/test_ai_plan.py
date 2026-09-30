"""离线测试：不读取真实 .env，不访问 MySQL，不请求 DeepSeek。

将此文件放在项目的 tests/test_ai_plan.py，然后在项目根目录执行：
python -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
from auth_test_support import authorize
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError


class AIPlanTests(unittest.TestCase):
    def setUp(self):
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        # 导入接口时替换 database 模块，避免触碰真实数据库配置。
        fake_database = types.ModuleType("database")
        fake_database.engine = MagicMock()
        source = Path(__file__).resolve().parents[1] / "ai_routes.py"
        spec = importlib.util.spec_from_file_location("_lesslab_ai_under_test", source)
        self.ai = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"database": fake_database}):
            spec.loader.exec_module(self.ai)

        self.candidates = [
            {"id": 1, "title": "Python 函数", "url": "https://example.com/1", "estimated_minutes": 20},
            {"id": 2, "title": "Python 练习", "url": "https://example.com/2", "estimated_minutes": 15},
        ]
        self.connection = fake_database.engine.connect.return_value.__enter__.return_value
        self.rows = self.connection.execute.return_value.mappings.return_value
        self.rows.all.return_value = self.candidates

        config_patch = patch.object(self.ai, "dotenv_values", return_value={
            "DEEPSEEK_API_KEY": "dummy-test-key",
            "DEEPSEEK_MODEL": "deepseek-flash",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DB_PASSWORD": "dummy-database-password",
        })
        self.config_mock = config_patch.start()
        self.addCleanup(config_patch.stop)

        # 没有明确设置模拟响应时，任何模型调用都会让测试立即失败。
        http_patch = patch.object(
            self.ai.httpx, "post",
            side_effect=AssertionError("测试中禁止发送真实模型请求。"),
        )
        self.http_mock = http_patch.start()
        self.addCleanup(http_patch.stop)

        app = FastAPI()
        app.include_router(self.ai.router)
        authorize(app)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def set_model_response(self, items, finish_reason="stop"):
        self.http_mock.side_effect = None
        self.http_mock.return_value = httpx.Response(200, json={
            "choices": [{
                "finish_reason": finish_reason,
                "message": {"content": json.dumps({"items": items}, ensure_ascii=False)},
            }],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
        })

    def call_plan(self, minutes=30, goal="学习 Python 函数"):
        return self.client.post("/ai-study-plan", json={"goal": goal, "minutes": minutes})

    def test_valid_plan_uses_database_values(self):
        self.set_model_response([{"id": 1, "reason": "标题与函数学习目标相关。"}])
        response = self.call_plan()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["mode"], "ai")
        self.assertEqual(data["total_minutes"], 20)
        self.assertEqual(data["remaining_minutes"], 10)
        self.assertEqual(data["items"][0]["title"], self.candidates[0]["title"])
        self.assertEqual(data["items"][0]["url"], self.candidates[0]["url"])
        self.assertEqual(data["usage"]["prompt_tokens"], 100)
        self.http_mock.assert_called_once()

    def test_plan_can_exactly_fill_budget(self):
        self.set_model_response([{"id": 1, "reason": "学习函数。"}, {"id": 2, "reason": "练习巩固。"}])
        response = self.call_plan(minutes=35)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_minutes"], 35)
        self.assertEqual(response.json()["remaining_minutes"], 0)

    def test_unknown_id_is_rejected(self):
        self.set_model_response([{"id": 999, "reason": "不存在的收藏。"}])
        self.assertEqual(self.call_plan().status_code, 502)

    def test_duplicate_id_is_rejected(self):
        self.set_model_response([{"id": 1, "reason": "第一项。"}, {"id": 1, "reason": "重复项。"}])
        self.assertEqual(self.call_plan().status_code, 502)

    def test_over_budget_plan_is_rejected(self):
        self.set_model_response([{"id": 1, "reason": "第一项。"}, {"id": 2, "reason": "第二项。"}])
        self.assertEqual(self.call_plan(minutes=30).status_code, 502)

    def test_empty_reason_is_rejected(self):
        self.set_model_response([{"id": 1, "reason": "   "}])
        self.assertEqual(self.call_plan().status_code, 502)

    def test_unexpected_model_fields_are_rejected(self):
        self.set_model_response([{"id": 1, "reason": "函数相关。", "estimated_minutes": 1}])
        self.assertEqual(self.call_plan().status_code, 502)

    def test_string_id_is_rejected(self):
        self.set_model_response([{"id": "1", "reason": "编号类型不正确。"}])
        self.assertEqual(self.call_plan().status_code, 502)

    def test_too_many_choices_are_rejected(self):
        self.set_model_response([{"id": i + 1, "reason": "测试理由。"} for i in range(9)])
        self.assertEqual(self.call_plan().status_code, 502)

    def test_truncated_output_is_rejected(self):
        self.set_model_response([], finish_reason="length")
        self.assertEqual(self.call_plan().status_code, 502)

    def test_malformed_response_is_rejected(self):
        for content in ("not json", "{}", "null", '{"items":null}'):
            with self.subTest(content=content):
                self.http_mock.side_effect = None
                self.http_mock.return_value = httpx.Response(200, json={
                    "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                })
                self.assertEqual(self.call_plan().status_code, 502)

    def test_no_candidates_skips_model_and_configuration(self):
        self.rows.all.return_value = []
        response = self.call_plan()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "no_candidates")
        self.assertEqual(response.json()["total_minutes"], 0)
        self.assertIsNone(response.json()["usage"])
        self.http_mock.assert_not_called()
        self.config_mock.assert_not_called()

    def test_model_may_select_nothing_but_still_uses_tokens(self):
        self.set_model_response([])
        response = self.call_plan()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "ai")
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["usage"]["completion_tokens"], 30)
        self.http_mock.assert_called_once()

    def test_missing_key_skips_model_call(self):
        self.config_mock.return_value = {}
        self.assertEqual(self.call_plan().status_code, 503)
        self.http_mock.assert_not_called()

    def test_cloud_environment_works_without_local_env_file(self):
        self.config_mock.return_value = {}
        self.set_model_response([{"id": 1, "reason": "练习函数。"}])
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "cloud-test-key", "DEEPSEEK_BASE_URL": "https://example.com/api", "DEEPSEEK_MODEL": "test-model"}):
            self.assertEqual(self.call_plan().status_code, 200)
        self.assertEqual(self.http_mock.call_args.args[0], "https://example.com/api/chat/completions")
        self.assertEqual(self.http_mock.call_args.kwargs['headers']['Authorization'], 'Bearer cloud-test-key')
        self.assertEqual(self.http_mock.call_args.kwargs['json']['model'], 'test-model')

    def test_blank_cloud_key_disables_file_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            self.assertEqual(self.call_plan().status_code, 503)
        self.http_mock.assert_not_called()

    def test_timeout_is_reported_without_retry(self):
        self.http_mock.side_effect = httpx.ReadTimeout("simulated timeout")
        self.assertEqual(self.call_plan().status_code, 504)
        self.http_mock.assert_called_once()

    def test_connection_failure_is_reported_without_retry(self):
        self.http_mock.side_effect = httpx.ConnectError("simulated network failure")
        self.assertEqual(self.call_plan().status_code, 503)
        self.http_mock.assert_called_once()

    def test_provider_error_does_not_expose_key(self):
        self.http_mock.side_effect = None
        self.http_mock.return_value = httpx.Response(402)
        response = self.call_plan()
        self.assertEqual(response.status_code, 502)
        self.assertIn("402", response.json()["detail"])
        self.assertNotIn("dummy-test-key", response.text)
        self.http_mock.assert_called_once()

    def test_database_failure_skips_model_call(self):
        self.ai.engine.connect.side_effect = SQLAlchemyError("simulated database failure")
        self.assertEqual(self.call_plan().status_code, 503)
        self.http_mock.assert_not_called()

    def test_invalid_request_is_rejected_before_model_call(self):
        for minutes in (0, -1, 601, 1.5, "30"):
            with self.subTest(minutes=minutes):
                self.assertEqual(self.call_plan(minutes=minutes).status_code, 422)
        for goal in ("", " ", "a", "a" * 501):
            with self.subTest(goal_length=len(goal)):
                self.assertEqual(self.call_plan(goal=goal).status_code, 422)
        self.http_mock.assert_not_called()
        self.ai.engine.connect.assert_not_called()

    def test_model_payload_contains_only_allowed_task_data(self):
        self.set_model_response([{"id": 1, "reason": "函数相关。"}])
        self.assertEqual(self.call_plan().status_code, 200)
        payload = self.http_mock.call_args.kwargs["json"]
        task = json.loads(payload["messages"][1]["content"])
        self.assertEqual(set(task), {"goal", "budget_minutes", "candidates"})
        for item in task["candidates"]:
            self.assertEqual(set(item), {"id", "title", "estimated_minutes"})
        serialized = json.dumps(payload)
        self.assertNotIn("dummy-test-key", serialized)
        self.assertNotIn("dummy-database-password", serialized)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 1500)


if __name__ == "__main__":
    unittest.main()
