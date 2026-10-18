import unittest
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

from app.schemas.conversation import ConversationDecision
from app.schemas.ai import ChatResponse
from tests import test_agent_api as fixtures


class ConversationApiTest(unittest.TestCase):
    setUp = fixtures.AgentApiTest.setUp
    request = fixtures.AgentApiTest.request
    catalogue = fixtures.AgentApiTest.catalogue
    setup_agent = fixtures.AgentApiTest.setup_agent

    def create(self):
        result = self.request("POST", "/conversations", role="reader", json={"request_id": str(uuid4())})
        return "/conversations/" + result["conversation_id"]

    def send(self, path, text="找测试书并申请借阅", kind="borrow", read_only=False, **kwargs):
        decision = ConversationDecision(action="plan", plan={"steps": [
            {"task_type": kind, "query": text, "title": "处理需求", "read_only": read_only}]}, **kwargs)
        with patch("app.agent.conversation.route_conversation", return_value=decision):
            return self.request("POST", path + "/messages", role="reader", json={"request_id": str(uuid4()), "text": text})

    def test_one_conversation_keeps_chat_and_business_and_replays_confirmation(self):
        book = self.setup_agent(); path = self.create()
        with patch("app.agent.specialists.ai_services.chat", return_value=ChatResponse(content="你好")):
            self.send(path, "你好", "chat", True)
        result = self.send(path)
        self.assertEqual(len(result["turns"]), 2)
        self.assertEqual(len(result["tasks"]), 2)
        task = result["tasks"][-1]; task_path = path + "/tasks/" + task["workflow_id"]
        payload = {"step_id": task["steps"][0]["id"], "operation": "select", "book_id": book["id"]}
        result = self.request("POST", task_path + "/steps", role="reader", json=payload)
        self.assertEqual(self.request("GET", "/loans", role="reader")["total"], 0)
        action = result["tasks"][-1]["steps"][0]["result"]["action"]
        payload = {"step_id": payload["step_id"], "operation": "decision", "action_id": action["id"], "confirmed": True}
        self.request("POST", task_path + "/steps", role="reader", json=payload)
        self.request("POST", task_path + "/steps", role="reader", json=payload)
        self.assertEqual(self.request("GET", "/loans", role="reader")["total"], 1)
        restored = self.request("GET", path, role="reader")
        self.assertEqual(restored["tasks"][-1]["steps"][0]["result"]["status"], "pending")
        self.assertEqual(len(restored["turns"]), 2)

    def test_ownership_task_binding_and_strict_operations(self):
        self.setup_agent(); path = self.create(); result = self.send(path)
        task = result["tasks"][0]; suffix = "/tasks/" + task["workflow_id"] + "/retry"
        other_path = self.create()
        self.assertEqual(self.client.post("/api" + other_path + suffix, headers=self.headers["reader"]).json()["code"], 404)
        self.assertEqual(self.client.get("/api" + path, headers=self.headers["other"]).json()["code"], 404)
        for extra in ({"user_id": 99}, {"confirmed": True}, {"hint": "admin"}):
            response = self.client.post("/api" + path + "/messages", headers=self.headers["reader"],
                json={"request_id": str(uuid4()), "text": "你好", **extra})
            self.assertEqual(response.json()["code"], 422)

    def test_natural_conditions_are_drafts_and_ambiguous_date_is_not_bound(self):
        path = self.create()
        result = self.send(path, "预约周六的研讨室", "reservation", draft={"date_expression": "周六", "people": 3})
        task = result["tasks"][0]
        self.assertEqual(task["status"], "needs_conditions")
        self.assertIsNone(task["conditions"])
        self.assertNotIn("date", task["draft_conditions"])
        self.assertEqual(len(task["draft_conditions"]["date_candidates"]), 2)
        decision = ConversationDecision(action="conditions", workflow_id=task["workflow_id"],
            draft={"date_expression": "明天", "start": "14:00", "end": "16:00", "purpose": "讨论"})
        with patch("app.agent.conversation.route_conversation", return_value=decision):
            result = self.request("POST", path + "/messages", role="reader",
                json={"request_id": str(uuid4()), "text": "明天下午两点到四点用于讨论"})
        task = result["tasks"][0]
        self.assertEqual(task["draft_conditions"]["people"], 3)
        self.assertIn("date", task["draft_conditions"])
        self.assertIsNone(task["conditions"])
        conditions = {"date": str(date.today() + timedelta(days=2)), "start": "14:00", "end": "16:00", "people": 3, "purpose": "讨论"}
        result = self.request("POST", path + "/tasks/" + task["workflow_id"] + "/conditions", role="reader", json={"conditions": conditions})
        self.assertEqual(result["tasks"][0]["conditions"]["people"], 3)
        self.assertEqual(self.request("GET", "/reservation/mine", role="reader"), [])
