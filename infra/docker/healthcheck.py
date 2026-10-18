"""Readiness probes without publishing infrastructure ports."""

import asyncio
import sys

sys.path.insert(0, "/app")


def check(service):
    if service == "api":
        import urllib.request
        from sqlalchemy import text
        from app.database import engine
        urllib.request.urlopen("http://127.0.0.1:8000/", timeout=3).close()
        with engine.connect() as db:
            db.execute(text("SELECT 1"))
    elif service == "mcp":
        import httpx
        from app.agent.mcp_adapter import issue_token
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async def probe():
            async with httpx.AsyncClient(timeout=3, trust_env=False,
                    headers={"Authorization": "Bearer " + issue_token(1)}) as client:
                async with streamable_http_client("http://mcp:8002/mcp", http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        assert (await session.list_tools()).tools
        asyncio.run(probe())
    else:
        raise ValueError("Unknown healthcheck")


if __name__ == "__main__":
    check(sys.argv[1])
