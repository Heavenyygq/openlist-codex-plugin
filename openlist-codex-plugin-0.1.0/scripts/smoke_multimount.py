"""Opt-in integration test for an OpenList Local + WebDAV fixture server."""

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


async def smoke(local_fixture: Path, webdav_fixture: Path) -> dict:
    project = Path(__file__).resolve().parents[1]
    config = json.loads((project / ".mcp.json").read_text())["mcpServers"]["openlist"]
    checks = []
    with tempfile.TemporaryDirectory(prefix="openlist-multimount-smoke-") as download_dir:
        env = {key: os.environ[key] for key in config["env_vars"] if key in os.environ}
        env["OPENLIST_DOWNLOAD_DIR"] = download_dir
        params = StdioServerParameters(command=config["command"], args=config["args"], cwd=str(project), env=env)
        async with stdio_client(params) as streams, ClientSession(*streams) as session:
            await session.initialize()

            async def call(name: str, arguments: dict | None = None) -> dict:
                result = await session.call_tool(name, arguments or {})
                assert not result.isError, "MCP operation failed; inspect sanitized error locally"
                assert result.structuredContent is not None
                text = result.model_dump_json()
                assert "raw_url" not in text and "?sign=" not in text
                return result.structuredContent

            def passed(name: str) -> None:
                checks.append({"check": name, "result": "PASS"})

            status = await call("openlist_status")
            assert status["verified"] and status["mount"] == "/"
            passed("configured user root spans mounts")
            listing = await call("openlist_list")
            assert {"Quark", "WebDAV"} <= {entry["name"] for entry in listing["entries"]}
            passed("enumerate Local and WebDAV mounts through one account")
            found = await call("openlist_search", {"query": ".txt"})
            paths = {entry["path"] for entry in found["matches"]}
            assert {"Quark/你好 世界.txt", "WebDAV/跨网盘说明.txt"} <= paths
            assert found["truncated"] is False
            passed("recursive filename search crosses storage drivers")
            for remote, source, driver in (
                ("Quark/你好 世界.txt", local_fixture / "你好 世界.txt", "Local"),
                ("WebDAV/跨网盘说明.txt", webdav_fixture / "跨网盘说明.txt", "WebDav"),
            ):
                data = await call("openlist_download", {"path": remote})
                expected = source.read_bytes()
                assert Path(data["saved_path"]).read_bytes() == expected
                assert data["sha256"] == hashlib.sha256(expected).hexdigest()
                assert data["bytes"] == len(expected)
                passed(f"byte-identical signed proxy download through {driver}")
    return {"backend": "OpenList v4.2.6 Local and WebDav test fixtures; individual cloud drives not tested", "passed": len(checks), "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-fixtures", type=Path, required=True)
    parser.add_argument("--webdav-fixtures", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = asyncio.run(smoke(args.local_fixtures, args.webdav_fixtures))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
