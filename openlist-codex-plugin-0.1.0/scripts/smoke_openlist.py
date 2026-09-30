"""Opt-in stdio smoke test against an operator-provided OpenList Local fixture.

Run with OPENLIST_TOKEN_FILE, OPENLIST_ROOT and OPENLIST_URL configured.
The fixture contains 你好 世界.txt and 中文资料/会议纪要.md. No token is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def smoke(fixtures: Path) -> dict:
    project = Path(__file__).resolve().parents[1]
    config = json.loads((project / ".mcp.json").read_text())["mcpServers"]["openlist"]
    checks = []

    def passed(name: str) -> None:
        checks.append({"check": name, "result": "PASS"})

    with tempfile.TemporaryDirectory(prefix="openlist-mcp-smoke-") as download_dir:
        env = {key: os.environ[key] for key in config["env_vars"] if key in os.environ}
        env["OPENLIST_DOWNLOAD_DIR"] = download_dir
        params = StdioServerParameters(
            command=config["command"], args=config["args"], cwd=str(project / config["cwd"]), env=env,
        )
        async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
            await session.initialize()
            passed("MCP stdio initialize using saved .mcp.json command")
            tools = (await session.list_tools()).tools
            assert {tool.name for tool in tools} == {"openlist_status", "openlist_list", "openlist_search", "openlist_download"}
            assert next(tool for tool in tools if tool.name == "openlist_download").annotations.readOnlyHint is False
            passed("four tools with correct download write annotation")

            async def call(name: str, arguments: dict | None = None):
                result = await session.call_tool(name, arguments or {})
                # All returned content is scanned for fields that must stay internal.
                encoded = result.model_dump_json()
                assert "raw_url" not in encoded and "?sign=" not in encoded and '"Authorization"' not in encoded
                return result

            status = await call("openlist_status")
            assert not status.isError and status.structuredContent["verified"] is True
            passed("verified read access to live OpenList mount")
            listing = await call("openlist_list")
            assert not listing.isError
            assert {entry["name"] for entry in listing.structuredContent["entries"]} >= {"你好 世界.txt", "中文资料"}
            passed("Chinese directory listing")
            search = await call("openlist_search", {"query": "纪要"})
            assert not search.isError and search.structuredContent["truncated"] is False
            assert "中文资料/会议纪要.md" in {entry["path"] for entry in search.structuredContent["matches"]}
            passed("recursive Chinese filename search without search index")
            for path in ("你好 世界.txt", "中文资料/会议纪要.md"):
                download = await call("openlist_download", {"path": path})
                assert not download.isError
                data = download.structuredContent
                expected = (fixtures / path).read_bytes()
                saved = Path(data["saved_path"])
                assert saved.read_bytes() == expected
                assert data["bytes"] == len(expected) and data["sha256"] == hashlib.sha256(expected).hexdigest()
                passed(f"byte-identical signed proxy download: {path}")
                again = await call("openlist_download", {"path": path})
                assert again.isError and saved.read_bytes() == expected
                passed(f"refuse overwriting existing file: {path}")
            traversal = await call("openlist_list", {"path": "../other"})
            assert traversal.isError
            passed("reject traversal outside configured mount")
            # OpenList denies this to the dedicated fixture reader; the adapter must report an error.
            denied = await call("openlist_list", {"path": "nonexistent-directory"})
            assert denied.isError
            passed("upstream failure remains an MCP error")
    return {"backend": "OpenList Local fixture; cloud storage drivers not individually verified", "checks": checks, "passed": len(checks)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = asyncio.run(smoke(args.fixtures))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
