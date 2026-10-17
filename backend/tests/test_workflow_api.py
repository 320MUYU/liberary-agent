import unittest
from unittest.mock import patch
from uuid import uuid4

from app.schemas.workflow import WorkflowPlan
from tests import test_agent_api as fixtures


class WorkflowApiTest(unittest.TestCase):
    setUp = fixtures.AgentApiTest.setUp
    request = fixtures.AgentApiTest.request
    catalogue = fixtures.AgentApiTest.catalogue
    setup_agent = fixtures.AgentApiTest.setup_agent

    def start(self, read_only=False):
        plan = patch("app.agent.workflow.plan_workflow", return_value=WorkflowPlan(steps=[{
            "task_type": "borrow", "query": "测试", "title": "查找图书", "read_only": read_only}]))
        plan.start(); self.addCleanup(plan.stop)
        return self.request("POST", "/workflows", role="reader", json={"request_id": str(uuid4()), "query": "找测试图书"})

    def test_parent_selection_confirmation_and_replay_use_existing_business(self):
        book = self.setup_agent(); run = self.start(); path = "/workflows/" + run["workflow_id"]
        self.assertEqual(run["status"], "ready")
        run = self.request("POST", path + "/retry", role="reader")
        step = run["steps"][0]
        run = self.request("POST", path + "/steps", role="reader", json={"operation": "select", "step_id": step["id"], "book_id": book["id"]})
        self.assertEqual(self.request("GET", "/loans", role="reader")["total"], 0)
        data = {"operation": "decision", "step_id": step["id"], "action_id": run["steps"][0]["result"]["action"]["id"], "confirmed": True}
        self.assertEqual(self.request("POST", path + "/steps", role="reader", json=data)["status"], "completed")
        self.assertEqual(self.request("POST", path + "/steps", role="reader", json=data)["status"], "completed")
        self.assertEqual(self.request("GET", "/loans", role="reader")["total"], 1)

    def test_cross_user_forged_steps_and_legacy_child_access_are_rejected(self):
        self.setup_agent(); run = self.start(); path = "/workflows/" + run["workflow_id"]
        other = self.client.get("/api" + path, headers=self.headers["other"])
        self.assertEqual(other.json()["code"], 404)
        forged = self.client.post("/api" + path + "/steps", headers=self.headers["reader"], json={"operation": "skip", "step_id": 999})
        self.assertEqual(forged.json()["code"], 404)
        child = run["steps"][0]["child_run_id"]
        direct = self.client.post("/api/agent/runs", headers=self.headers["reader"], json={"request_id": child, "query": "其他任务"})
        self.assertEqual(direct.json()["code"], 409)

    def test_strict_action_arguments_and_read_only_plan_cannot_submit(self):
        book = self.setup_agent(); run = self.start(True); path = "/workflows/" + run["workflow_id"]
        run = self.request("POST", path + "/retry", role="reader")
        step_id = run["steps"][0]["id"]
        for data in ({"operation": "select", "step_id": step_id, "book_id": book["id"], "user_id": 1},
                {"operation": "decision", "step_id": step_id, "action_id": str(uuid4()), "confirmed": "true"}):
            response = self.client.post("/api" + path + "/steps", headers=self.headers["reader"], json=data)
            self.assertEqual(response.json()["code"], 422)
        response = self.client.post("/api" + path + "/steps", headers=self.headers["reader"], json={"operation": "select", "step_id": step_id, "book_id": book["id"]})
        self.assertEqual(response.json()["code"], 409)
