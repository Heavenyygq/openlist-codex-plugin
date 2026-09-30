import json
from dataclasses import replace

import httpx
import pytest

from openlist_codex.browser_link import in_scope, verify_session
from openlist_codex.browser_session import clear_session, save_session
from openlist_codex.config import PluginError, Settings


@pytest.mark.parametrize('page,expected', [
    ('https://openlist.example/app/', True),
    ('https://openlist.example/app/@login', True),
    ('https://openlist.example/other', False),
    ('https://external.example/app', False),
    ('http://openlist.example/app', False),
    ('https://user:pass@openlist.example/app', False),
])
def test_page_scope(page, expected):
    assert in_scope(page, 'https://openlist.example/app') is expected


@pytest.mark.parametrize('envelope,valid', [
    ({'code': 200, 'data': {'role': 0, 'disabled': False}}, True),
    ({'code': 200, 'data': {'role': 1}}, False),
    ({'code': 200, 'data': {'role': 0, 'disabled': True}}, False),
    ({'code': 401}, False),
    ([], False),
])
async def test_verify_web_session(envelope, valid):
    def handler(request):
        assert request.url.path == '/app/api/me'
        assert request.headers['Authorization'] == 'fixture-session'
        return httpx.Response(200, json=envelope)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await verify_session(client, 'https://openlist.example/app', 'fixture-session') is valid


async def test_browser_login_switch_logout_followed_without_mcp_restart(make_client, settings, tmp_path):
    path = tmp_path / 'session.json'
    calls = []
    def handler(request):
        calls.append(request.headers['Authorization'])
        return httpx.Response(200, json={'code': 200, 'data': {'content': [], 'total': 0}})
    custom = replace(settings, token='', browser_session_file=path)
    client = make_client(handler, custom)
    save_session(path, settings.url, 'first-session')
    await client.list_files()
    save_session(path, settings.url, 'second-session')
    await client.list_files()
    clear_session(path, settings.url)
    with pytest.raises(PluginError, match='not linked'):
        await client.list_files()
    assert calls == ['first-session', 'second-session']


def test_config_auto_discovers_url_and_credential_conflict(tmp_path):
    path = tmp_path / 'session.json'
    save_session(path, 'https://openlist.example/app', 'fixture-session')
    env = {'OPENLIST_BROWSER_SESSION_FILE': str(path)}
    s = Settings.from_env(env)
    assert s.url == 'https://openlist.example/app'
    assert s.browser_session_file == path
    assert s.public_status()['authentication_method'] == 'browser'
    assert 'fixture-session' not in json.dumps(s.public_status())
    with pytest.raises(PluginError, match='not both'):
        Settings.from_env({**env, 'OPENLIST_TOKEN': 'explicit'})
    with pytest.raises(PluginError, match='Cannot read'):
        Settings.from_env({**env, 'OPENLIST_URL': 'https://other.example'})