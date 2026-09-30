import asyncio
import hashlib
import json
from dataclasses import replace

import httpx
import pytest

from openlist_codex.config import PluginError, Settings


def test_account_config_and_secret_redaction(tmp_path):
    s = Settings.from_env({'OPENLIST_USERNAME': 'reader', 'OPENLIST_PASSWORD': ' pass ', 'OPENLIST_DOWNLOAD_DIR': str(tmp_path)})
    assert s.password == ' pass '
    assert s.configured
    assert s.public_status()['authentication_method'] == 'account'
    assert ' pass ' not in repr(s)
    assert 'reader' not in repr(s)
    assert 'password' not in json.dumps(s.public_status())


@pytest.mark.parametrize('env', [
    {'OPENLIST_USERNAME': 'reader'},
    {'OPENLIST_PASSWORD': 'secret'},
    {'OPENLIST_USERNAME': 'reader', 'OPENLIST_PASSWORD': 'secret', 'OPENLIST_TOKEN': 'token'},
    {'OPENLIST_USERNAME': 'reader', 'OPENLIST_PASSWORD': 'secret', 'OPENLIST_OTP_CODE': 'bad'},
])
def test_invalid_account_config(env):
    with pytest.raises(PluginError):
        Settings.from_env(env)


def test_password_file_preserves_spaces(tmp_path):
    path = tmp_path / 'password'
    path.write_text(' pass ', encoding='utf-8')
    path.chmod(0o600)
    s = Settings.from_env({'OPENLIST_USERNAME': 'reader', 'OPENLIST_PASSWORD_FILE': str(path)})
    assert s.password == ' pass '


async def test_account_login_cached_for_concurrent_requests(make_client, settings):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/auth/login/hash'):
            data = json.loads(request.content)
            assert data['username'] == 'reader'
            assert data['password'] == hashlib.sha256(b' pass -https://github.com/alist-org/alist').hexdigest()
            assert 'Authorization' not in request.headers
            return httpx.Response(200, json={'code': 200, 'data': {'token': 'session-secret'}})
        assert request.headers['Authorization'] == 'session-secret'
        return httpx.Response(200, json={'code': 200, 'data': {'content': [], 'total': 0}})

    client = make_client(handler, replace(settings, token='', username='reader', password=' pass '))
    await asyncio.gather(client.list_files(), client.list_files())
    assert len([r for r in requests if r.url.path.endswith('/auth/login/hash')]) == 1


@pytest.mark.parametrize('envelope', [
    {'code': 401, 'message': 'private-password'},
    {'code': 402},
    {'code': 429},
    {'code': 200, 'data': {}},
    {'code': 200, 'data': {'token': 'bad\nheader'}},
    [],
])
async def test_failed_login_not_repeated_or_leaked(make_client, settings, envelope):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope)

    client = make_client(handler, replace(settings, token='', username='reader', password='private-password'))
    for _ in range(2):
        with pytest.raises(PluginError) as error:
            await client.list_files()
        assert 'private-password' not in str(error.value)
    assert len(requests) == 1


async def test_account_token_expiry_reauth_next_call(make_client, settings):
    logins = 0
    calls = 0

    def handler(request):
        nonlocal logins, calls
        if request.url.path.endswith('/auth/login/hash'):
            logins += 1
            return httpx.Response(200, json={'code': 200, 'data': {'token': f'session-{logins}'}})
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={'code': 401})
        return httpx.Response(200, json={'code': 200, 'data': {'content': [], 'total': 0}})

    client = make_client(handler, replace(settings, token='', username='reader', password='secret'))
    with pytest.raises(PluginError):
        await client.list_files()
    await client.list_files()
    assert logins == 2