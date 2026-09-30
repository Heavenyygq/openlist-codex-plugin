"""Explicit browser login association. Never inspect ordinary browser profiles."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import shutil
import subprocess
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .browser_session import (
    BrowserSessionError,
    clear_session,
    default_session_path,
    normalize_url,
    save_session,
)


def in_scope(page_url: str, server_url: str) -> bool:
    try:
        page = urlsplit(page_url)
        server = urlsplit(server_url)
        def origin(value):
            return value.scheme, value.hostname, value.port or (443 if value.scheme == "https" else 80)
        if origin(page) != origin(server) or page.username or page.password:
            return False
        base = server.path.rstrip("/")
        return page.path == base or page.path.startswith(base + "/")
    except ValueError:
        return False


async def verify_session(client: httpx.AsyncClient, url: str, token: str) -> bool:
    if not isinstance(token, str) or not token or len(token) > 8192 or any(ord(ch) < 32 or ord(ch) == 127 for ch in token):
        return False
    try:
        async with client.stream("GET", url + "/api/me", headers={"Authorization": token}) as response:
            if response.status_code != 200:
                return False
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    return False
            import json
            result = json.loads(body)
        data = result.get("data") if isinstance(result, dict) else None
        return isinstance(result, dict) and result.get("code") == 200 and isinstance(data, dict) and type(data.get("role")) is int and data.get("role") in (0, 2) and not data.get("disabled", False)
    except (httpx.HTTPError, OSError, ValueError):
        return False


def launch_codex(url: str, session_file: Path) -> subprocess.Popen:
    executable = shutil.which("codex")
    if not executable:
        raise BrowserSessionError("Codex CLI was not found. Install Codex, then reopen the association window.")
    env = dict(os.environ)
    for name in ("OPENLIST_TOKEN", "OPENLIST_TOKEN_FILE", "OPENLIST_USERNAME", "OPENLIST_PASSWORD", "OPENLIST_PASSWORD_FILE", "OPENLIST_OTP_CODE"):
        env.pop(name, None)
    env["OPENLIST_BROWSER_SESSION_FILE"] = str(session_file)
    env["OPENLIST_URL"] = url
    env.setdefault("OPENLIST_DOWNLOAD_DIR", str(Path.home() / "Downloads" / "OpenList-Codex"))
    prompt = "调用 openlist_status 检查 OpenList 登录关联，再用 openlist_list 列出根目录。不要下载、修改或删除文件。"
    return subprocess.Popen([executable, prompt], env=env)


async def link(url: str, browser: str, session_file: Path, profile_dir: Path | None = None, launch: bool = False, headless: bool = False) -> None:
    from playwright.async_api import Error, async_playwright
    url = normalize_url(url)
    profile = profile_dir or session_file.parent / ("browser-profile-" + hashlib.sha256(url.encode()).hexdigest()[:12])
    profile.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        profile.chmod(0o700)
    clear_session(session_file, url)
    print("OpenList 关联窗口已打开，请在网页中登录。此窗口使用独立的浏览器配置。", flush=True)
    print("窗口保持打开时会同步登录和退出；关闭窗口保留最后一次已验证会话。", flush=True)
    launched = False
    last_token = ""
    last_verified = 0.0
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(str(profile), channel=browser, headless=headless)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                while context.pages:
                    pages = [p for p in context.pages if in_scope(p.url, url)]
                    if not pages:
                        await asyncio.sleep(1)
                        continue
                    try:
                        token = await pages[0].evaluate("() => localStorage.getItem('token') || ''")
                    except Error:
                        await asyncio.sleep(1)
                        continue
                    if not token:
                        if last_token:
                            clear_session(session_file, url)
                            last_token = ""
                            print("OpenList 已退出，插件关联已清除。", flush=True)
                    elif token != last_token or asyncio.get_running_loop().time() - last_verified > 30:
                        valid = await verify_session(client, url, token)
                        last_verified = asyncio.get_running_loop().time()
                        if valid:
                            if token != last_token:
                                save_session(session_file, url, token)
                                last_token = token
                                print("OpenList 登录已关联，插件可以使用。", flush=True)
                            if launch and not launched:
                                launch_codex(url, session_file)
                                launched = True
                        else:
                            if last_token:
                                clear_session(session_file, url)
                                last_token = ""
                                print("会话已失效，请在 OpenList 关联窗口重新登录。", flush=True)
                            # Avoid retrying an invalid token every second.
                            await asyncio.sleep(5)
                    await asyncio.sleep(1)
        finally:
            with suppress(Error):
                await context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Open your OpenList login page and associate its session with the local Codex plugin.")
    parser.add_argument("--url", default="http://127.0.0.1:5244")
    parser.add_argument("--browser", choices=["msedge", "chrome", "chromium"], default="msedge")
    parser.add_argument("--session-file", type=Path)
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--launch-codex", action="store_true")
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        asyncio.run(link(args.url, args.browser, args.session_file or default_session_path(), args.profile_dir, args.launch_codex, args.headless))
    except KeyboardInterrupt:
        pass
    except Exception:
        # Browser errors can include page URLs or JavaScript values. Keep output safe.
        print("关联窗口无法启动或连接中断。请检查 OpenList 地址、浏览器安装状态及窗口是否已在运行。", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
