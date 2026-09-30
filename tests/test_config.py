import os

import pytest

from openlist_codex.config import (
    PluginError,
    Settings,
    read_secret,
    validate_filename,
    validate_relative_path,
)


def test_mount_paths_are_relative_and_cannot_escape(settings):
    assert settings.remote_path("") == "/Quark"
    assert settings.remote_path("/报告/总结.pdf/") == "/Quark/报告/总结.pdf"
    assert settings.relative_path("/Quark/报告/总结.pdf") == "报告/总结.pdf"
    assert settings.relative_path("/Quark") == ""
    with pytest.raises(PluginError, match="outside"):
        settings.relative_path("/Quark-other/private.txt")


def test_generic_default_root_uses_account_visible_mounts(tmp_path):
    settings = Settings.from_env({"OPENLIST_TOKEN": "test-secret", "OPENLIST_DOWNLOAD_DIR": str(tmp_path)})
    assert settings.root == "/"
    assert settings.remote_path("团队盘/说明.txt") == "/团队盘/说明.txt"
    assert settings.relative_path("/WebDAV/说明.txt") == "WebDAV/说明.txt"
    assert settings.download_dir == tmp_path


@pytest.mark.parametrize("path", ["../private", "a/../private", "a/./b", "a//b", "a\\b", "a\n", "\x00", "x" * 4097])
def test_relative_paths_reject_traversal_and_ambiguous_components(path):
    with pytest.raises(PluginError):
        validate_relative_path(path)


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../secret", "a/b", "a\\b", "C:secret", "CON", "con.txt", "NUL.csv", "LPT1", "COM9.dat", "trailing.", "trailing ", "line\n", "x" * 241, "中" * 81],
)
def test_download_names_are_single_portable_filenames(name):
    with pytest.raises(PluginError):
        validate_filename(name)


def test_unicode_filenames_and_nonreserved_prefixes_are_valid():
    assert validate_filename("报告 2026.pdf") == "报告 2026.pdf"
    assert validate_filename("CONTEXT.txt") == "CONTEXT.txt"


@pytest.mark.parametrize("name", [123, [], {"name": "report"}])
def test_malformed_upstream_filename_is_a_safe_error(name):
    with pytest.raises(PluginError):
        validate_filename(name)


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com", "example.com", "http://openlist.example", "https://user:pass@example.com", "https://example.com?token=secret", "https://example.com/#private", "https://example.com:invalid", "https://example.com/\n"],
)
def test_server_urls_reject_credentials_and_insecure_remote_transport(url):
    with pytest.raises(PluginError):
        Settings(url=url)


@pytest.mark.parametrize("url", ["http://localhost:5244", "http://127.0.0.1:5244", "http://[::1]:5244", "https://openlist.example/app/"])
def test_loopback_or_https_urls_are_allowed(url):
    assert Settings(url=url).url == url.rstrip("/")


def test_secret_is_hidden_from_settings_repr_and_public_status(settings):
    assert "test-secret" not in repr(settings)
    assert "test-secret" not in str(settings.public_status())
    assert settings.public_status()["authentication"] == "present"


def test_secret_file_with_restrictive_permissions(tmp_path):
    token = tmp_path / "token"
    token.write_text("test-secret\n", encoding="utf-8")
    token.chmod(0o600)
    assert read_secret({"OPENLIST_TOKEN_FILE": str(token)}, "OPENLIST_TOKEN") == "test-secret"


@pytest.mark.skipif(os.name != "posix", reason="POSIX credential file permissions")
def test_world_readable_secret_file_is_rejected(tmp_path):
    token = tmp_path / "token"
    token.write_text("private-value", encoding="utf-8")
    token.chmod(0o644)
    with pytest.raises(PluginError, match="0600") as error:
        read_secret({"OPENLIST_TOKEN_FILE": str(token)}, "OPENLIST_TOKEN")
    assert "private-value" not in str(error.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX symbolic links")
def test_symlink_secret_file_is_rejected(tmp_path):
    token = tmp_path / "token"
    token.write_text("private-value", encoding="utf-8")
    token.chmod(0o600)
    link = tmp_path / "token-link"
    link.symlink_to(token)
    with pytest.raises(PluginError, match="safely read"):
        read_secret({"OPENLIST_TOKEN_FILE": str(link)}, "OPENLIST_TOKEN")


@pytest.mark.skipif(os.name != "posix", reason="POSIX FIFO")
def test_fifo_secret_file_is_rejected_without_blocking(tmp_path):
    token = tmp_path / "token-fifo"
    os.mkfifo(token, 0o600)
    with pytest.raises(PluginError, match="regular file"):
        read_secret({"OPENLIST_TOKEN_FILE": str(token)}, "OPENLIST_TOKEN")


def test_secret_file_and_inline_token_are_mutually_exclusive(tmp_path):
    with pytest.raises(PluginError, match="not both"):
        read_secret({"OPENLIST_TOKEN": "secret", "OPENLIST_TOKEN_FILE": str(tmp_path / "token")}, "OPENLIST_TOKEN")


@pytest.mark.parametrize("value", ["secret\ninjection", "secret\x00", "x" * 8193])
def test_secret_rejects_header_injection_and_oversized_values(value):
    with pytest.raises(PluginError):
        read_secret({"OPENLIST_TOKEN": value}, "OPENLIST_TOKEN")


def test_explicit_missing_credentials_are_actionable(tmp_path):
    with pytest.raises(PluginError, match="safely read"):
        read_secret({"OPENLIST_TOKEN_FILE": str(tmp_path / "missing")}, "OPENLIST_TOKEN")
    assert read_secret({}, "OPENLIST_TOKEN", tmp_path / "missing") == ""


def test_from_env_reads_configuration_and_protects_mount(tmp_path):
    settings = Settings.from_env({
        "OPENLIST_URL": "https://openlist.example",
        "OPENLIST_ROOT": "/Quark",
        "OPENLIST_TOKEN": "test-secret",
        "OPENLIST_PATH_PASSWORD": "mount-password",
        "OPENLIST_DOWNLOAD_DIR": str(tmp_path),
        "OPENLIST_MAX_DOWNLOAD_BYTES": "123",
    })
    assert settings.max_download_bytes == 123
    assert settings.download_dir == tmp_path
    assert settings.path_password == "mount-password"
    assert "mount-password" not in repr(settings)
    with pytest.raises(PluginError):
        Settings.from_env({"OPENLIST_ROOT": "/Quark/../other"})


@pytest.mark.parametrize("limit", ["0", "-1", str(10 * 1024**3 + 1), "not-a-number"])
def test_invalid_download_limits_are_rejected(limit):
    with pytest.raises(PluginError):
        Settings.from_env({"OPENLIST_MAX_DOWNLOAD_BYTES": limit})
