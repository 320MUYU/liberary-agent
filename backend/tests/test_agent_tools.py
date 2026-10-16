import unittest
from unittest.mock import patch

from tests import test_loan_service as fixtures
from app.agent.policy import RunBudget
from app.agent.tools import execute_read_tool, tool_definitions
from app.models.loans import Loan


class AgentToolsTest(unittest.TestCase):
    setUp = fixtures.LoanServiceTest.setUp
    add_book = fixtures.LoanServiceTest.add_book

    def test_search_returns_only_active_books_and_never_writes(self):
        self.add_book(title="Python 隐藏", barcode="HIDDEN", is_active=False)
        self.db.commit()
        result = execute_read_tool(self.db, self.reader.id, "search_books", {"keyword": "Python"}, RunBudget())
        self.assertTrue(result["ok"])
        self.assertEqual([b["id"] for b in result["data"]["books"]], [self.book.id])
        self.assertEqual(self.db.query(Loan).count(), 0)

    def test_arbitrary_tools_and_identity_arguments_are_rejected(self):
        for name, args in [("confirm_borrow", {}), ("search_books", {"keyword": "Python", "user_id": self.other.id}), ("get_book", {"book_id": True})]:
            result = execute_read_tool(self.db, self.reader.id, name, args, RunBudget())
            self.assertFalse(result["ok"])
        self.assertEqual({t["name"] for t in tool_definitions()}, {"search_books", "get_book"})

    def test_disabled_identity_cannot_use_tools(self):
        self.reader.status = 0
        self.db.commit()
        result = execute_read_tool(self.db, self.reader.id, "search_books", {"keyword": "Python"}, RunBudget())
        self.assertEqual(result["error_code"], "unauthorized")

    def test_budget_and_upstream_errors_are_safe(self):
        budget = RunBudget(max_tools=1)
        execute_read_tool(self.db, self.reader.id, "get_book", {"book_id": self.book.id}, budget)
        self.assertEqual(execute_read_tool(self.db, self.reader.id, "get_book", {"book_id": self.book.id}, budget)["error_code"], "budget_exceeded")
        with patch("app.agent.tools.book_service.get_book_detail", side_effect=RuntimeError("private-secret")):
            result = execute_read_tool(self.db, self.reader.id, "get_book", {"book_id": self.book.id}, RunBudget())
        self.assertNotIn("private-secret", str(result))
        self.assertEqual(result["error_code"], "unavailable")
