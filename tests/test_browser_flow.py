"""Opt-in real browser flow using a synthetic OpenList-shaped local fixture."""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from openlist_codex.browser_link import link
from openlist_codex.browser_session import load_session
from openlist_codex.client import OpenListClient
from openlist_codex.config import PluginError, Settings

pytestmark = pytest.mark.skipif(os.getenv('OPENLIST_RUN_BROWSER_TESTS') != '1', reason='Opt-in installed Edge/Chrome browser flow')


async def test_browser_login_mcp_read_and_logout(tmp_path, monkeypatch):
    from playwright.async_api import BrowserType
    page_ready = asyncio.Event()
    browser_contexts = []
    original_launch = BrowserType.launch_persistent_context

    async def launch(self, *args, **kwargs):
        context = await original_launch(self, *args, **kwargs)
        browser_contexts.append(context)
        page_ready.set()
        return context

    monkeypatch.setattr(BrowserType, 'launch_persistent_context', launch)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, value):
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == '/api/me':
                self.send_json({'code': 200, 'data': {'role': 0, 'disabled': False}} if self.headers.get('Authorization') == 'synthetic-browser-session' else {'code': 401})
            else:
                raw = b'''<!doctype html><title>OpenList browser flow fixture</title><button id="login" onclick="localStorage.setItem('token','synthetic-browser-session')">Log in fixture</button><button id="logout" onclick="localStorage.setItem('token','')">Log out fixture</button>'''
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.send_json({'code': 200, 'data': {'content': [], 'total': 0}} if self.headers.get('Authorization') == 'synthetic-browser-session' else {'code': 401})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    state = tmp_path / 'session.json'
    task = asyncio.create_task(link(url, 'msedge', state, tmp_path / 'profile', headless=True))
    try:
        await asyncio.wait_for(page_ready.wait(), 30)
        page = browser_contexts[0].pages[0]
        await page.wait_for_selector('#login')
        await page.locator('#login').click()
        for _ in range(40):
            if load_session(state, url):
                break
            await asyncio.sleep(0.25)
        assert load_session(state, url)[1] == 'synthetic-browser-session'
        client = OpenListClient(Settings(url=url, browser_session_file=state, download_dir=tmp_path / 'downloads'))
        try:
            assert (await client.list_files())['entries'] == []
            await page.locator('#logout').click()
            for _ in range(40):
                if load_session(state, url) is None:
                    break
                await asyncio.sleep(0.25)
            assert load_session(state, url) is None
            with pytest.raises(PluginError, match='not linked'):
                await client.list_files()
        finally:
            await client.close()
        await page.close()
        await asyncio.wait_for(task, 10)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        server.shutdown()
        server.server_close()
