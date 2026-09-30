import json
import os
import stat

import pytest

from openlist_codex import browser_session
from openlist_codex.browser_session import (
    BrowserSessionError,
    clear_session,
    default_session_path,
    load_session,
    normalize_url,
    save_session,
)

URL = "http://127.0.0.1:5244"
TOKEN = "test-browser-token-中文"


def _write_state(path, state):
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)


def test_save_and_load_explicit_browser_handoff(tmp_path):
    path = tmp_path / "private" / "browser-session.json"
    save_session(path, URL + "/", TOKEN)
    assert load_session(path, URL) == (URL, TOKEN)
    assert load_session(path) == (URL, TOKEN)
    assert list(path.parent.iterdir()) == [path]


def test_missing_session_does_not_require_login(tmp_path):
    assert load_session(tmp_path / "missing.json", URL) is None


def test_logout_replaces_previous_token(tmp_path):
    path = tmp_path / "session.json"
    save_session(path, URL, TOKEN)
    clear_session(path, URL)
    assert load_session(path, URL) is None
    assert TOKEN not in path.read_text(encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == ""


def test_logout_without_existing_session_persists_logged_out_state(tmp_path):
    path = tmp_path / "session.json"
    clear_session(path, URL)
    assert path.is_file()
    assert load_session(path, URL) is None


@pytest.mark.parametrize("other", ["http://localhost:5244", "http://127.0.0.1:5245", "https://127.0.0.1:5244", URL + "/other"])
def test_handoff_never_sends_credentials_to_another_server_or_basepath(tmp_path, other):
    path = tmp_path / "session.json"
    save_session(path, URL, TOKEN)
    with pytest.raises(BrowserSessionError, match="different OpenList") as error:
        load_session(path, other)
    assert TOKEN not in str(error.value)


def test_url_normalization_preserves_base_path_case(tmp_path):
    path = tmp_path / "session.json"
    save_session(path, "https://OPENLIST.example:443/Mount/", TOKEN)
    assert load_session(path, "https://openlist.example/Mount") == ("https://openlist.example/Mount", TOKEN)
    with pytest.raises(BrowserSessionError, match="base path"):
        load_session(path, "https://openlist.example/mount")


@pytest.mark.parametrize("url", ["http://localhost:5244", "http://127.0.0.1:5244", "http://[::1]:5244", "https://openlist.example/subpath"])
def test_allowed_openlist_addresses(url):
    assert normalize_url(url) == url


@pytest.mark.parametrize(
    "url",
    [None, 123, "", "example.com", "ftp://openlist.example", "http://openlist.example", "https://user:private-secret@openlist.example", "https://@openlist.example", "https://openlist.example?token=private-secret", "https://openlist.example?", "https://openlist.example#private-secret", "https://openlist.example#", "https://openlist.example:invalid", "https://openlist.example:99999", "https://openlist.example/\n", "https://openlist.example/\x00", "https://openlist.example\\@another.example", "https://openlist.example/base/../private", "x" * 4097],
)
def test_invalid_urls_are_rejected_without_disclosing_credentials(tmp_path, url):
    with pytest.raises(BrowserSessionError) as error:
        save_session(tmp_path / "session.json", url, TOKEN)
    assert "private-secret" not in str(error.value)
    assert TOKEN not in str(error.value)
    assert not (tmp_path / "session.json").exists()


@pytest.mark.parametrize("token", [None, 123, "", "secret\n", "secret\r", "secret\x00", "secret\x7f", "\ud800", "x" * 8193])
def test_invalid_browser_token_is_never_saved(tmp_path, token):
    path = tmp_path / "session.json"
    with pytest.raises(BrowserSessionError) as error:
        save_session(path, URL, token)
    assert "secret" not in str(error.value)
    assert not path.exists()


def test_explicit_session_path_env_overrides_default(monkeypatch, tmp_path):
    explicit = tmp_path / "chosen-session.json"
    monkeypatch.setenv("OPENLIST_BROWSER_SESSION_FILE", str(explicit))
    assert default_session_path() == explicit


@pytest.mark.skipif(os.name != "nt", reason="Windows local app data path")
def test_windows_default_is_plugin_owned_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENLIST_BROWSER_SESSION_FILE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_session_path() == tmp_path / "OpenList-Codex" / "browser-session.json"


@pytest.mark.skipif(os.name != "posix", reason="POSIX default and permissions")
def test_posix_default_is_plugin_owned_config(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENLIST_BROWSER_SESSION_FILE", raising=False)
    monkeypatch.setattr(browser_session.Path, "home", lambda: tmp_path)
    assert default_session_path() == tmp_path / ".config" / "openlist-codex" / "browser-session.json"


@pytest.mark.skipif(os.name != "nt", reason="Current-user DPAPI")
def test_windows_protects_raw_token_with_dpapi(tmp_path):
    path = tmp_path / "session.json"
    save_session(path, URL, TOKEN)
    raw = path.read_text(encoding="utf-8")
    assert TOKEN not in raw
    assert json.loads(raw)["protection"] == "dpapi"
    assert load_session(path, URL) == (URL, TOKEN)


@pytest.mark.skipif(os.name != "nt", reason="Current-user DPAPI")
def test_windows_encryption_detects_blob_tampering(tmp_path):
    path = tmp_path / "session.json"
    save_session(path, URL, TOKEN)
    state = json.loads(path.read_text(encoding="utf-8"))
    encoded = state["token"]
    offset = len(encoded) // 2
    state["token"] = encoded[:offset] + ("A" if encoded[offset] != "A" else "B") + encoded[offset + 1:]
    _write_state(path, state)
    with pytest.raises(BrowserSessionError, match="protect or unlock") as error:
        load_session(path, URL)
    assert TOKEN not in str(error.value)


@pytest.mark.skipif(os.name != "nt", reason="Current-user DPAPI additional entropy")
def test_windows_encryption_is_bound_to_server_url(tmp_path):
    path = tmp_path / "session.json"
    save_session(path, URL, TOKEN)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["url"] = "https://other.example"
    _write_state(path, state)
    with pytest.raises(BrowserSessionError, match="protect or unlock"):
        load_session(path, "https://other.example")


@pytest.mark.skipif(os.name != "posix", reason="POSIX credential file permissions")
def test_posix_atomic_save_creates_owner_only_file(tmp_path):
    path = tmp_path / "private" / "session.json"
    save_session(path, URL, TOKEN)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == TOKEN
    assert load_session(path, URL) == (URL, TOKEN)


@pytest.mark.skipif(os.name != "posix", reason="POSIX credential file permissions")
def test_posix_shared_session_file_is_rejected(tmp_path):
    path = tmp_path / "session.json"
    save_session(path, URL, TOKEN)
    path.chmod(0o644)
    with pytest.raises(BrowserSessionError, match="0600") as error:
        load_session(path, URL)
    assert TOKEN not in str(error.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX symbolic links")
def test_symbolic_link_cannot_read_or_overwrite_another_file(tmp_path):
    target = tmp_path / "target.json"
    save_session(target, URL, TOKEN)
    original = target.read_bytes()
    link = tmp_path / "linked.json"
    link.symlink_to(target)
    with pytest.raises(BrowserSessionError, match="regular file"):
        load_session(link, URL)
    with pytest.raises(BrowserSessionError, match="regular file"):
        clear_session(link, URL)
    assert target.read_bytes() == original


@pytest.mark.skipif(os.name != "posix", reason="POSIX FIFO")
def test_fifo_cannot_block_reading_login_state(tmp_path):
    path = tmp_path / "session.json"
    os.mkfifo(path, 0o600)
    with pytest.raises(BrowserSessionError, match="regular file"):
        load_session(path, URL)


@pytest.mark.parametrize("state", [None, [], "secret", {}, {"version": 2}, {"version": True}, {"version": 1, "url": URL}, {"version": 1, "url": URL, "token": 123}, {"version": 1, "url": 123, "token": "secret"}, {"version": 1, "url": URL, "token": "secret", "protection": "unsupported"}])
def test_invalid_or_incomplete_session_state_is_a_safe_error(tmp_path, state):
    path = tmp_path / "session.json"
    _write_state(path, state)
    with pytest.raises(BrowserSessionError) as error:
        load_session(path, URL)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("raw", [b"{\"token\":\"private-secret\"", b"\xff\xfe", b" " * (64 * 1024 + 1)], ids=["malformed-json", "invalid-utf8", "oversized"])
def test_corrupt_or_oversized_state_is_rejected_without_secrets(tmp_path, raw):
    path = tmp_path / "session.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    with pytest.raises(BrowserSessionError) as error:
        load_session(path, URL)
    assert "private-secret" not in str(error.value)


def test_failed_atomic_replace_preserves_previous_session(monkeypatch, tmp_path):
    path = tmp_path / "session.json"
    save_session(path, URL, TOKEN)
    original = path.read_bytes()

    def fail_replace(*_args):
        raise PermissionError("credential-containing-internal-detail")

    monkeypatch.setattr(browser_session.os, "replace", fail_replace)
    with pytest.raises(BrowserSessionError, match="safely save") as error:
        clear_session(path, URL)
    assert "credential-containing-internal-detail" not in str(error.value)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
