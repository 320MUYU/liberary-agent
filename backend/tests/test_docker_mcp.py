"""Container transport must retain the first-party MCP host boundary."""

import asyncio
import unittest
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.agent import mcp_adapter
from app.config import Settings, settings
from app.mcp.library import create_server


class DockerMcpTest(unittest.TestCase):
    def test_loopback_defaults_and_explicit_container_allowlist(self):
        with patch.dict("os.environ", {}, clear=True):
            config = Settings(_env_file=None, DATABASE_URL="sqlite://", JWT_SECRET_KEY="test",
                JWT_EXPIRE_HOURS=24, JWT_ALGORITHM="HS256")
        self.assertIn("127.0.0.1", config.AGENT_MCP_ALLOWED_HOSTS)
        self.assertNotIn("mcp", config.AGENT_MCP_ALLOWED_HOSTS)
        with patch.object(settings, "AGENT_MCP_ALLOWED_HOSTS", ["mcp"]):
            self.assertEqual(mcp_adapter.validate_endpoint("http://mcp:8002/mcp"), "http://mcp:8002/mcp")
            for url in ("http://evil/mcp", "http://mcp.evil/mcp", "http://user@mcp/mcp",
                        "http://mcp/mcp?token=x", "http://mcp/mcp#x", "file://mcp/mcp"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    mcp_adapter.validate_endpoint(url)

    def test_container_host_accepts_authenticated_protocol_but_rejects_other_hosts(self):
        with patch.object(settings, "AGENT_MCP_ALLOWED_HOSTS", ["mcp"]):
            server, app = create_server()

        async def check():
            async with server.session_manager.run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                        headers={"Authorization": "Bearer " + mcp_adapter.issue_token(1)}) as client:
                    async with streamable_http_client("http://mcp:8002/mcp", http_client=client) as streams:
                        async with ClientSession(streams[0], streams[1]) as session:
                            await session.initialize()
                            self.assertTrue((await session.list_tools()).tools)
                    denied = await client.post("http://evil:8002/mcp", json={})
                    self.assertEqual(denied.status_code, 421)
                    origin = await client.post("http://mcp:8002/mcp", json={}, headers={"Origin": "http://evil"})
                    self.assertEqual(origin.status_code, 403)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                    self.assertEqual((await client.post("http://mcp:8002/mcp", json={})).status_code, 401)

        asyncio.run(check())
