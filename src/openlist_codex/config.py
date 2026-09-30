"""Configuration is supplied by the operator, never by an MCP tool call."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class PluginError(Exception):
    """An error whose message is safe to send to the model."""


def read_secret(env: dict[str, str], name: str, default_file: Path | None = None, *, preserve_whitespace: bool = False) -> str:
    inline = env.get(name, "")
    explicit = env.get(f"{name}_FILE", "")
    if inline and explicit:
        raise PluginError(f"Set only {name} or {name}_FILE, not both.")
    if inline:
        value = inline if preserve_whitespace else inline.strip()
    else:
        secret_path = Path(explicit).expanduser() if explicit else default_file
        if secret_path is None or (not explicit and not secret_path.exists()):
            return ""
        try:
            # Avoid following links and do not read a FIFO/device as a credential.
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            fd = os.open(secret_path, flags)
            with os.fdopen(fd, "r", encoding="utf-8") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise PluginError(f"{name}_FILE must be a regular file.")
                if os.name == "posix" and (info.st_mode & 0o077 or info.st_uid != os.getuid()):
                    raise PluginError(f"{name}_FILE must be owned by you and have permissions 0600.")
                raw = source.read(8193)
                value = raw if preserve_whitespace else raw.strip()
        except (OSError, UnicodeError):
            raise PluginError(f"Cannot safely read {name}_FILE; check its path and permissions.") from None
    if len(value) > 8192 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PluginError(f"{name} contains invalid characters or is too long.")
    return value


def validate_relative_path(value: str) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise PluginError("Path must be a string of at most 4096 characters.")
    if "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PluginError("Path contains unsupported characters.")
    parts = value.strip("/").split("/")
    if any(part in (".", "..") for part in parts):
        raise PluginError("Path cannot contain '.' or '..' components.")
    if any(part == "" for part in parts) and value.strip("/"):
        raise PluginError("Path cannot contain empty components.")
    return value.strip("/")


def validate_filename(value: str) -> str:
    if not isinstance(value, str) or not value or value in (".", "..") or len(value.encode("utf-8")) > 240:
        raise PluginError("Choose a nonempty filename of at most 240 UTF-8 bytes.")
    if any(char in value for char in '/\\:<>"|?*') or value[-1:] in (" ", "."):
        raise PluginError("Filename must be a single portable filename without path separators.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PluginError("Filename contains control characters.")
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", value, re.I):
        raise PluginError("Filename is reserved on Windows.")
    return value


@dataclass(frozen=True)
class Settings:
    url: str = "http://127.0.0.1:5244"
    token: str = field(default="", repr=False)
    browser_session_file: Path | None = field(default=None, repr=False)
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    otp_code: str = field(default="", repr=False)
    root: str = "/"
    path_password: str = field(default="", repr=False)
    download_dir: Path = field(default_factory=lambda: Path.cwd() / "openlist-downloads")
    max_download_bytes: int = 100 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.browser_session_file and (self.token or self.username or self.password):
            raise PluginError("Use browser association or explicit credentials, not both.")
        if self.token and (self.username or self.password or self.otp_code):
            raise PluginError("Use either token authentication or account login, not both.")
        if bool(self.username) != bool(self.password):
            raise PluginError("Account login requires both OPENLIST_USERNAME and OPENLIST_PASSWORD or its _FILE.")
        for value in (self.username, self.password, self.otp_code):
            if len(value) > 8192 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
                raise PluginError("Account credentials contain invalid characters or are too long.")
        if self.otp_code and (not self.username or not re.fullmatch(r"[0-9]{6}", self.otp_code)):
            raise PluginError("OPENLIST_OTP_CODE requires account login and a six-digit code.")
        try:
            parsed = urlsplit(self.url)
            _ = parsed.port
        except ValueError:
            raise PluginError("OPENLIST_URL is invalid.") from None
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            raise PluginError("OPENLIST_URL must be an absolute HTTP(S) URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PluginError("OPENLIST_URL cannot contain credentials, a query or a fragment.")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise PluginError("Use HTTPS for a remote OpenList server; HTTP is allowed only on loopback.")
        if any(ord(char) < 32 or ord(char) == 127 for char in self.url):
            raise PluginError("OPENLIST_URL contains control characters.")
        root = validate_relative_path(self.root)
        object.__setattr__(self, "root", "/" + root)
        object.__setattr__(self, "url", self.url.rstrip("/"))
        object.__setattr__(self, "download_dir", self.download_dir.expanduser().absolute())
        if not 1 <= self.max_download_bytes <= 10 * 1024**3:
            raise PluginError("OPENLIST_MAX_DOWNLOAD_BYTES must be between 1 byte and 10 GiB.")

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ) if environ is None else environ
        try:
            limit = int(env.get("OPENLIST_MAX_DOWNLOAD_BYTES", str(100 * 1024 * 1024)))
        except ValueError:
            raise PluginError("OPENLIST_MAX_DOWNLOAD_BYTES must be an integer.") from None
        account_login = bool(env.get("OPENLIST_USERNAME") or env.get("OPENLIST_PASSWORD") or env.get("OPENLIST_PASSWORD_FILE"))
        default_token = None if account_login or env.get("OPENLIST_BROWSER_SESSION_FILE") else Path.home() / ".config/openlist-codex/openlist-token"
        token = read_secret(env, "OPENLIST_TOKEN", default_token)
        browser_file = None
        url = env.get("OPENLIST_URL", "http://127.0.0.1:5244")
        if env.get("OPENLIST_BROWSER_SESSION_FILE") and (token or account_login):
            raise PluginError("Use browser association or explicit credentials, not both.")
        if not token and not account_login:
            from .browser_session import (
                BrowserSessionError,
                default_session_path,
                load_session,
            )
            candidate = Path(env["OPENLIST_BROWSER_SESSION_FILE"]).expanduser() if env.get("OPENLIST_BROWSER_SESSION_FILE") else default_session_path()
            if env.get("OPENLIST_BROWSER_SESSION_FILE") or candidate.exists():
                browser_file = candidate
                try:
                    state = load_session(candidate, env.get("OPENLIST_URL"))
                except BrowserSessionError:
                    raise PluginError("Cannot read browser association; reopen the OpenList association window.") from None
                if state:
                    url = state[0]
        return cls(
            url=url,
            token=token,
            browser_session_file=browser_file,
            username=env.get("OPENLIST_USERNAME", "").strip(),
            password=read_secret(env, "OPENLIST_PASSWORD", preserve_whitespace=True),
            otp_code=env.get("OPENLIST_OTP_CODE", "").strip(),
            root=env.get("OPENLIST_ROOT", "/"),
            path_password=read_secret(env, "OPENLIST_PATH_PASSWORD"),
            download_dir=Path(env.get("OPENLIST_DOWNLOAD_DIR", str(Path.cwd() / "openlist-downloads"))),
            max_download_bytes=limit,
        )

    def remote_path(self, relative: str) -> str:
        suffix = validate_relative_path(relative)
        return f"{self.root.rstrip('/')}/{suffix}" if suffix else self.root

    def relative_path(self, remote: str) -> str:
        if remote == self.root:
            return ""
        prefix = self.root.rstrip("/") + "/"
        if not remote.startswith(prefix):
            raise PluginError("OpenList returned a path outside the configured mount.")
        return validate_relative_path(remote[len(prefix) :])

    @property
    def configured(self) -> bool:
        return bool(self.browser_session_file or self.token or (self.username and self.password))

    def public_status(self) -> dict:
        return {
            "configured": self.configured,
            "backend": "OpenList",
            "mount": self.root,
            "download_dir": str(self.download_dir),
            "max_download_bytes": self.max_download_bytes,
            "authentication": "present" if self.configured else "missing",
            "authentication_method": "browser" if self.browser_session_file else ("account" if self.username else ("token" if self.token else "none")),
        }
