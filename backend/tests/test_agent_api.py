import tempfile
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage
from tests import test_library_flow as fixtures
import unittest


class AgentApiTest(unittest.TestCase):
    setUp = fixtures.LibraryFlowTest.setUp
    request = fixtures.LibraryFlowTest.request
    catalogue = fixtures.LibraryFlowTest.catalogue

    def setup_agent(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = patch("app.agent.runtime.settings.AGENT_CHECKPOINT_PATH", Path(directory.name) / "graph.sqlite")
        config.start(); self.addCleanup(config.stop)
        responses = iter([AIMessage(content="", tool_calls=[{"id": "t1", "name": "search_books", "args": {"keyword": "测试"}}]), AIMessage(content="")])
        model = patch("app.agent.runtime.call_model", side_effect=lambda *_: next(responses))
        model.start(); self.addCleanup(model.stop)
        return self.catalogue()[0]

    def start(self):
        return self.request("POST", "/agent/runs", role="reader", json={"request_id": "7fb09321-340b-4aa6-9725-2668638fbdd0", "query": "找测试图书"})

    def test_find_select_confirm_and_replay_create_one_pending_loan(self):
        book = self.setup_agent()
        run = self.start()
        self.assertEqual(run["status"], "select_book")
        self.assertEqual(self.start()["run_id"], run["run_id"])
        path = "/agent/runs/" + run["run_id"]
        selected = self.request("POST", path + "/select", role="reader", json={"book_id": book["id"]})
        self.assertEqual(selected["status"], "confirm_borrow")
        self.assertEqual(self.request("GET", "/loans", role="reader")["total"], 0)
        payload = {"action_id": selected["action"]["id"], "confirmed": True}
        result = self.request("POST", path + "/decision", role="reader", json=payload)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(self.request("POST", path + "/decision", role="reader", json=payload)["receipt"], result["receipt"])
        self.assertEqual(self.request("GET", "/loans", role="reader")["total"], 1)
        self.assertEqual(self.request("GET", "/books/" + str(book["id"]), role="reader")["available_copies"], 1)
        self.assertEqual(self.request("GET", path, role="reader")["status"], "pending")

    def test_other_reader_and_forged_selection_cannot_advance(self):
        self.setup_agent()
        run = self.start(); path = "/agent/runs/" + run["run_id"]
        other = self.client.get("/api" + path, headers=self.headers["other"])
        self.assertEqual(other.json()["code"], 404)
        invalid = self.client.post("/api" + path + "/select", headers=self.headers["reader"], json={"book_id": 999})
        self.assertEqual(invalid.json()["code"], 409)
        self.assertEqual(self.request("GET", "/loans", role="reader")["total"], 0)

    def test_cancel_and_reload_never_submit(self):
        book = self.setup_agent(); run = self.start(); path = "/agent/runs/" + run["run_id"]
        selected = self.request("POST", path + "/select", role="reader", json={"book_id": book["id"]})
        result = self.request("POST", path + "/decision", role="reader", json={"action_id": selected["action"]["id"], "confirmed": False})
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.request("GET", path, role="reader")["status"], "cancelled")
        self.assertEqual(self.request("GET", "/loans", role="reader")["total"], 0)
