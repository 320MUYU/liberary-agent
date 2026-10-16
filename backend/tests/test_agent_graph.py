import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.agent.graph import build_graph


class AgentGraphTest(unittest.TestCase):
    def test_unavailable_tools_are_not_reported_as_empty_catalogue(self):
        with SqliteSaver.from_conn_string(":memory:") as saver:
            graph = build_graph(saver, lambda _: AIMessage(content="", tool_calls=[{"id": "t", "name": "search_books", "args": {"keyword": "Python"}}]), lambda *_: {"ok": False, "error_code": "unavailable"})
            result = graph.invoke({"query": "找书", "books": [], "messages": []}, {"configurable": {"thread_id": "failed"}})
            self.assertEqual(result["status"], "tool_unavailable")

    def test_write_node_requires_exact_action_confirmation(self):
        calls = []
        with SqliteSaver.from_conn_string(":memory:") as saver:
            graph = build_graph(saver, lambda _: AIMessage(content=""), lambda *_: None,
                prepare=lambda book_id: {"id": "action-1", "book_id": book_id},
                execute=lambda action_id, confirmed: calls.append((action_id, confirmed)) or {"status": "pending", "message": "待管理员确认"})
            config = {"configurable": {"thread_id": "write"}}
            graph.invoke({"query": "Python", "books": [{"id": 3}], "messages": []}, config)
            result = graph.invoke(Command(resume={"book_id": 3}), config)
            self.assertEqual(result["__interrupt__"][0].value["kind"], "confirm_borrow")
            self.assertEqual(calls, [])
            result = graph.invoke(Command(resume={"action_id": "action-1", "confirmed": True}), config)
            self.assertEqual(calls, [("action-1", True)])
            self.assertEqual(result["status"], "pending")

    def test_react_reads_then_persists_selection_without_writing(self):
        calls = []
        replies = iter([AIMessage(content="", tool_calls=[{"id": "t1", "name": "search_books", "args": {"keyword": "Python"}}]), AIMessage(content="已找到")])
        def read(name, args):
            calls.append(name)
            return {"ok": True, "data": {"books": [{"id": 3, "title": "Python", "available_copies": 1}]}}
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "state.sqlite")
            with SqliteSaver.from_conn_string(path) as saver:
                graph = build_graph(saver, lambda messages: next(replies), read)
                config = {"configurable": {"thread_id": "reader-run"}}
                result = graph.invoke({"query": "找 Python 书", "books": [], "model_calls": 0, "tool_calls": 0, "messages": []}, config)
                self.assertEqual(result["__interrupt__"][0].value["kind"], "select_book")
                self.assertEqual(calls, ["search_books"])
            with SqliteSaver.from_conn_string(path) as saver:
                graph = build_graph(saver, lambda _: self.fail("resume must not call model"), read)
                result = graph.invoke(Command(resume={"book_id": 3}), config)
                self.assertEqual(result["selected_book_id"], 3)

    def test_model_text_cannot_claim_success_or_select_a_book(self):
        with SqliteSaver.from_conn_string(":memory:") as saver:
            graph = build_graph(saver, lambda _: AIMessage(content="已帮你借出图书"), lambda *_: self.fail())
            result = graph.invoke({"query": "你好", "books": [], "model_calls": 0, "tool_calls": 0, "messages": []}, {"configurable": {"thread_id": "empty"}})
            self.assertNotIn("已帮你借出", result["message"])
            self.assertFalse(result.get("selected_book_id"))

    def test_repeated_tool_calls_stop_at_budget(self):
        with SqliteSaver.from_conn_string(":memory:") as saver:
            graph = build_graph(saver, lambda _: AIMessage(content="", tool_calls=[{"id": "t", "name": "search_books", "args": {"keyword": "不存在"}}]), lambda *_: {"ok": True, "data": {"books": []}})
            result = graph.invoke({"query": "找书", "books": [], "model_calls": 0, "tool_calls": 0, "messages": []}, {"configurable": {"thread_id": "bounded"}})
            self.assertLessEqual(result["model_calls"], 4)
            self.assertLessEqual(result["tool_calls"], 8)

    def test_selection_rejects_unreturned_book(self):
        with SqliteSaver.from_conn_string(":memory:") as saver:
            graph = build_graph(saver, lambda _: AIMessage(content=""), lambda *_: None)
            config = {"configurable": {"thread_id": "selection"}}
            graph.invoke({"query": "Python", "books": [{"id": 3}], "model_calls": 0, "tool_calls": 0, "messages": []}, config)
            with self.assertRaises(ValueError):
                graph.invoke(Command(resume={"book_id": 99}), config)
