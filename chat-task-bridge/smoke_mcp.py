"""Actual MCP stdio handshake and excluded-scope check. No live chat reads."""
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(__file__).resolve().parent
    spec = StdioServerParameters(command=sys.executable, args=[str(root / "mcp_server.py"), "--config", str(root / "config.example.json")],
                                 env={"PYTHONIOENCODING": "utf-8"})
    async with stdio_client(spec) as (read, write):
        async with ClientSession(read, write) as session:
            hello = (await session.initialize()).model_dump(by_alias=True)
            tools = await session.list_tools()
            status = (await session.call_tool("bridge_status", {})).model_dump(by_alias=True, mode="json")
            denial = (await session.call_tool("search_messages", {"chat_alias": "excluded-group", "start_date": "2026-10-01", "end_date": "2026-10-29", "keyword": "", "purpose": "scope regression test"})).model_dump(by_alias=True, mode="json")
            assert [x.name for x in tools.tools] == ["bridge_status", "search_messages", "download_attachment"]
            assert "会话未在允许名单" in json.dumps(denial, ensure_ascii=False)
            print(json.dumps({"ok": True, "protocol": hello.get("protocolVersion"), "tools": [x.name for x in tools.tools], "excluded_scope_rejected": True}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
