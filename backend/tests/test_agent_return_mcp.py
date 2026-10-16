import asyncio
import unittest

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import sessionmaker

from tests import test_loan_service as fixtures
from app.agent.actions import prepare_return
from app.agent.mcp_adapter import issue_token
from app.agent.policy import RunBudget
from app.agent.tools import execute_read_tool
from app.mcp.library import create_server
from app.schemas.loan import LoanRequest, BorrowConfirmRequest
from app.services import loan_service


class AgentReturnMcpTest(unittest.TestCase):
    setUp = fixtures.LoanServiceTest.setUp
    add_book = fixtures.LoanServiceTest.add_book

    def test_loan_read_parity_and_return_capability_cannot_be_forged_or_reused_for_borrow(self):
        loan = loan_service.create_loan(self.db, self.reader, LoanRequest(book_id=self.book.id))
        loan_service.confirm_borrow(self.db, self.admin, loan.id, BorrowConfirmRequest())
        loan_id, user_id, other_id = loan.id, self.reader.id, self.other.id
        action = prepare_return(self.db, user_id, "mcp-return", loan_id)
        local = execute_read_tool(self.db, user_id, "list_my_loans", {}, RunBudget())
        self.db.close()
        server, app = create_server(sessionmaker(bind=self.engine))
        async def call(token, name, arguments):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers={"Authorization": "Bearer " + token}) as client:
                async with streamable_http_client("http://127.0.0.1:8002/mcp", http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        return (await session.call_tool(name, arguments)).structuredContent
        async def check():
            async with server.session_manager.run():
                reader = issue_token(user_id, read_scope="loans:read")
                self.assertEqual(await call(reader, "list_my_loans", {}), local)
                self.assertFalse((await call(issue_token(user_id), "list_my_loans", {}))["ok"])
                self.assertFalse((await call(issue_token(other_id, read_scope="loans:read"), "get_my_loan", {"loan_id": loan_id}))["ok"])
                args = {"action_id": action["id"], "confirmed": True}
                for token in [reader, issue_token(user_id, action["id"], True),
                    issue_token(user_id, "another-action", True, action_type="return"),
                    issue_token(user_id, action["id"], False, action_type="return")]:
                    self.assertFalse((await call(token, "submit_return_decision", args))["ok"])
                approved = issue_token(user_id, action["id"], True, action_type="return")
                self.assertFalse((await call(approved, "submit_borrow_decision", args))["ok"])
                result = await call(approved, "submit_return_decision", args)
                self.assertEqual(result["data"]["status"], "return_pending")
                self.assertEqual(result, await call(approved, "submit_return_decision", args))
        asyncio.run(check())
