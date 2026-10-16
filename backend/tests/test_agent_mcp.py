import asyncio
import unittest

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import sessionmaker

from tests import test_loan_service as fixtures
from app.agent.mcp_adapter import issue_token
from app.mcp.library import create_server
from app.agent.actions import prepare_borrow


class AgentMcpTest(unittest.TestCase):
    setUp = fixtures.LoanServiceTest.setUp
    add_book = fixtures.LoanServiceTest.add_book

    def test_mcp_read_and_scoped_write_use_same_business_contract(self):
        action = prepare_borrow(self.db, self.reader.id, "mcp-test-run", self.book.id)
        user_id = self.reader.id
        self.db.close()
        server, app = create_server(sessionmaker(bind=self.engine))
        async def call(token, name, arguments):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers={"Authorization": "Bearer " + token}) as client:
                async with streamable_http_client("http://127.0.0.1:8002/mcp", http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
                        return result
        async def check():
            async with server.session_manager.run():
                reader = issue_token(user_id)
                result = await call(reader, "search_books", {"keyword": "Python"})
                self.assertFalse(result.isError)
                self.assertTrue(result.structuredContent["ok"])
                denied = await call(reader, "submit_borrow_decision", {"action_id": action["id"], "confirmed": True})
                self.assertFalse(denied.structuredContent["ok"])
                approved = issue_token(user_id, action["id"], True)
                result = await call(approved, "submit_borrow_decision", {"action_id": action["id"], "confirmed": True})
                self.assertEqual(result.structuredContent["data"]["status"], "pending")
                replay = await call(approved, "submit_borrow_decision", {"action_id": action["id"], "confirmed": True})
                self.assertEqual(result.structuredContent, replay.structuredContent)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                    response = await client.post("http://127.0.0.1:8002/mcp", json={})
                    self.assertEqual(response.status_code, 401)
        asyncio.run(check())
