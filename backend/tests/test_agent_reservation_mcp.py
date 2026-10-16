import asyncio
import unittest

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import sessionmaker

from tests import test_reservation as fixtures
from app.agent.mcp_adapter import issue_token
from app.agent.policy import RunBudget
from app.agent.reservation_actions import prepare_reservation
from app.agent.tools import execute_read_tool
from app.mcp.library import create_server
from app.services.space_discovery import SpaceConditions


class AgentReservationMcpTest(unittest.TestCase):
    setUp = fixtures.ReservationFlowTest.setUp
    tearDown = fixtures.ReservationFlowTest.tearDown
    request = fixtures.ReservationFlowTest.request

    def test_real_protocol_parity_and_confirmation_scope_binding(self):
        conditions = SpaceConditions.model_validate(self.request().model_dump(exclude={"lab_id"}))
        action = prepare_reservation(self.db, self.student.id, "mcp-space", self.lab.id, conditions)
        uid, other = self.student.id, self.other.id
        args = {"conditions": conditions.model_dump(mode="json")}
        local = execute_read_tool(self.db, uid, "search_spaces", args, RunBudget())
        local["data"].pop("checked_at")
        self.db.close()
        server, app = create_server(sessionmaker(bind=self.engine))

        async def call(token, name, arguments):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers={"Authorization":"Bearer "+token}) as client:
                async with streamable_http_client("http://127.0.0.1:8002/mcp",http_client=client) as streams:
                    async with ClientSession(streams[0],streams[1]) as session:
                        await session.initialize()
                        return (await session.call_tool(name,arguments)).structuredContent

        async def check():
            async with server.session_manager.run():
                result = await call(issue_token(uid,read_scope="spaces:read"),"search_spaces",args)
                result["data"].pop("checked_at")
                self.assertEqual(result, local)
                self.assertFalse((await call(issue_token(uid),"search_spaces",args))["ok"])
                decision = {"action_id":action["id"],"confirmed":True}
                for token in [issue_token(uid,read_scope="spaces:read"), issue_token(uid,action["id"],True),
                    issue_token(other,action["id"],True,action_type="reservation"),
                    issue_token(uid,"wrong-action",True,action_type="reservation"),
                    issue_token(uid,action["id"],False,action_type="reservation")]:
                    self.assertFalse((await call(token,"submit_reservation_decision",decision))["ok"])
                capability = issue_token(uid,action["id"],True,action_type="reservation")
                self.assertFalse((await call(capability,"submit_return_decision",decision))["ok"])
                result=await call(capability,"submit_reservation_decision",decision)
                self.assertEqual(result["data"]["status"],"reservation_pending")
                self.assertEqual(result,await call(capability,"submit_reservation_decision",decision))

        asyncio.run(check())
