import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from langchain_core.messages import AIMessage
from tests import test_library_flow as fixtures
from app.agent.actions import decide_return


class AgentReturnApiTest(unittest.TestCase):
    setUp = fixtures.LibraryFlowTest.setUp
    request = fixtures.LibraryFlowTest.request
    catalogue = fixtures.LibraryFlowTest.catalogue

    def setup_returns(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for target, value in [("AGENT_CHECKPOINT_PATH", Path(directory.name) / "graph.sqlite"), ("AGENT_TOOL_TRANSPORT", "local")]:
            config = patch("app.agent.runtime.settings." + target, value)
            config.start(); self.addCleanup(config.stop)
        self.calls = 0
        def respond(*args):
            self.calls += 1
            return AIMessage(content="", tool_calls=([{"id": "loans", "name": "list_my_loans", "args": {}}] if self.calls % 2 else []))
        model = patch("app.agent.runtime.call_model", side_effect=respond)
        model.start(); self.addCleanup(model.stop)
        book, copy = self.catalogue()
        loan = self.request("POST", "/loans", role="reader", json={"book_id": book["id"]})
        self.request("POST", f"/admin/loans/{loan['id']}/confirm-borrow", json={})
        return book, copy, loan

    def start(self, task_type="return", request_id=None):
        return self.request("POST", "/agent/runs", role="reader", json={"request_id": request_id or str(uuid4()),
            "query": "查询我的借阅，我想还书", "task_type": task_type})

    def test_query_select_confirm_restore_and_admin_progress(self):
        book, _, loan = self.setup_returns()
        run = self.start("my_loans")
        self.assertEqual(run["status"], "select_loan")
        self.assertEqual(run["loans"][0]["id"], loan["id"])
        path = "/agent/runs/" + run["run_id"]
        selected = self.request("POST", path + "/select-loan", role="reader", json={"loan_id": loan["id"]})
        self.assertEqual(selected["status"], "confirm_return")
        self.assertEqual(self.request("GET", "/loans", role="reader")["items"][0]["status"], "borrowed")
        self.assertEqual(self.request("GET", path, role="reader")["action"], selected["action"])
        payload = {"action_id": selected["action"]["id"], "confirmed": True}
        result = self.request("POST", path + "/decision", role="reader", json=payload)
        self.assertEqual(result["status"], "return_pending")
        self.assertEqual(self.request("POST", path + "/decision", role="reader", json=payload)["receipt"], result["receipt"])
        self.assertEqual(self.request("GET", f"/books/{book['id']}", role="reader")["available_copies"], 0)
        self.request("POST", f"/admin/loans/{loan['id']}/confirm-return")
        self.assertEqual(self.request("GET", path, role="reader")["status"], "returned")

    def test_cross_user_forged_selection_and_task_binding(self):
        _, _, loan = self.setup_returns()
        run = self.start()
        path = "/agent/runs/" + run["run_id"]
        for role, suffix, data in [("other", "/select-loan", {"loan_id": loan["id"]}),
                                   ("reader", "/select-loan", {"loan_id": 999}),
                                   ("reader", "/select", {"book_id": loan["book_id"]})]:
            result = self.client.post("/api" + path + suffix, headers=self.headers[role], json=data)
            self.assertIn(result.json()["code"], (404, 409))
        result = self.client.post("/api/agent/runs", headers=self.headers["reader"], json={
            "request_id": run["run_id"], "query": "查询我的借阅，我想还书", "task_type": "borrow"})
        self.assertEqual(result.json()["code"], 409)

    def test_cancel_and_lost_write_response_recover_without_resubmission(self):
        _, _, loan = self.setup_returns()
        run = self.start(); path = "/agent/runs/" + run["run_id"]
        selected = self.request("POST", path + "/select-loan", role="reader", json={"loan_id": loan["id"]})
        cancelled = self.request("POST", path + "/decision", role="reader", json={"action_id": selected["action"]["id"], "confirmed": False})
        self.assertEqual(cancelled["status"], "cancelled")
        run = self.start(); path = "/agent/runs/" + run["run_id"]
        selected = self.request("POST", path + "/select-loan", role="reader", json={"loan_id": loan["id"]})
        def interrupted(*args):
            decide_return(*args)
            raise RuntimeError("lost return response")
        with patch("app.agent.runtime.decide_return", side_effect=interrupted):
            result = self.client.post("/api" + path + "/decision", headers=self.headers["reader"],
                json={"action_id": selected["action"]["id"], "confirmed": True})
        self.assertEqual(result.json()["code"], 503)
        self.assertEqual(self.request("POST", path + "/retry", role="reader")["status"], "return_pending")
        self.assertEqual(self.request("GET", "/loans", role="reader")["total"], 1)

    def test_pagination_is_read_only_and_checkpoint_selection_tracks_current_page(self):
        self.setup_returns()
        for i in range(6):
            book = self.request("POST", "/admin/books", json={"title": f"分页图书{i}", "author": "作者", "category": "文学"})
            self.request("POST", "/admin/book-copies", json={"book_id": book["id"], "barcode": f"PAGE-{i}", "location": "A"})
            self.request("POST", "/loans", role="reader", json={"book_id": book["id"]})
        run = self.start("my_loans"); path = "/agent/runs/" + run["run_id"]
        self.assertEqual(run["loan_page"]["total"], 7)
        page = self.request("POST", path + "/loans-page", role="reader", json={"page": 2})
        self.assertEqual(len(page["loans"]), 1)
        self.assertEqual(page["loan_page"]["page"], 2)
        self.assertEqual(self.request("GET", path, role="reader")["loans"], page["loans"])
        selected = self.request("POST", path + "/select-loan", role="reader", json={"loan_id": page["loans"][0]["id"]})
        self.assertEqual(selected["status"], "confirm_return")

    def test_empty_personal_page_is_distinct_from_query_failure(self):
        self.setup_returns()
        run = self.request("POST", "/agent/runs", role="other", json={
            "request_id": str(uuid4()), "query": "我的借阅", "task_type": "my_loans"})
        self.assertEqual(run["status"], "select_loan")
        self.assertEqual(run["loan_page"]["total"], 0)
        self.assertEqual(run["loans"], [])
        with patch("app.agent.runtime.execute_read_tool", return_value={"ok": False, "error_code": "unavailable"}):
            failed = self.start()
        self.assertEqual(failed["status"], "tool_unavailable")
        self.assertEqual(self.request("GET", "/loans", role="reader")["items"][0]["status"], "borrowed")

    def test_pending_return_record_cannot_be_selected_again(self):
        _, _, loan = self.setup_returns()
        self.request("POST", f"/loans/{loan['id']}/request-return", role="reader")
        run = self.start()
        self.assertEqual(run["loans"][0]["status"], "return_pending")
        result = self.client.post("/api/agent/runs/" + run["run_id"] + "/select-loan",
            headers=self.headers["reader"], json={"loan_id": loan["id"]})
        self.assertEqual(result.json()["code"], 409)
