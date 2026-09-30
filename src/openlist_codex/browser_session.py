"""Store a deliberately linked browser login for the current local user.

No existing browser profiles are inspected. Windows protects login tokens with
current-user DPAPI; POSIX uses an owner-only file, like other credential stores.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import ipaddress
import json
import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_MAX_FILE_BYTES = 64 * 1024
_MAX_TOKEN_CHARS = 8192
_DPAPI_UI_FORBIDDEN = 1


class BrowserSessionError(ValueError):
    """A credential-free error that can be shown to a user."""


def normalize_url(url: str) -> str:
    """Validate an OpenList server URL without disclosing its input in errors."""
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise BrowserSessionError("OpenList address is invalid.")
    if any(ord(char) <= 32 or ord(char) == 127 for char in url) or "\\" in url:
        raise BrowserSessionError("OpenList address contains unsupported characters.")
    try:
        url.encode("utf-8")
    except UnicodeError:
        raise BrowserSessionError("OpenList address contains unsupported characters.") from None
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise BrowserSessionError("OpenList address is invalid.") from None
    if parts.scheme not in ("http", "https") or not host:
        raise BrowserSessionError("OpenList address must be an absolute HTTP(S) URL.")
    if parts.username is not None or parts.password is not None or "?" in url or "#" in url:
        raise BrowserSessionError("OpenList address cannot contain credentials, a query or a fragment.")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    if parts.scheme == "http" and not loopback:
        raise BrowserSessionError("Use HTTPS for a remote OpenList server.")
    if any(component in (".", "..") for component in parts.path.split("/")):
        raise BrowserSessionError("OpenList address cannot contain relative path components.")
    host = host.lower()
    authority = f"[{host}]" if ":" in host else host
    if port is not None and port != (443 if parts.scheme == "https" else 80):
        authority += f":{port}"
    return urlunsplit((parts.scheme, authority, parts.path.rstrip("/"), "", ""))


def default_session_path() -> Path:
    """Return only this plugin's session file, never a browser's profile path."""
    explicit = os.environ.get("OPENLIST_BROWSER_SESSION_FILE")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        root = Path(local) if local else Path.home() / "AppData" / "Local"
        return root / "OpenList-Codex" / "browser-session.json"
    return Path.home() / ".config" / "openlist-codex" / "browser-session.json"


def _validate_token(token: str, *, allow_empty: bool = False) -> None:
    if not isinstance(token, str) or (not token and not allow_empty):
        raise BrowserSessionError("Browser login does not contain a valid token.")
    if len(token) > _MAX_TOKEN_CHARS or any(ord(char) < 32 or ord(char) == 127 for char in token):
        raise BrowserSessionError("Browser login token contains invalid characters or is too long.")
    try:
        token.encode("utf-8")
    except UnicodeError:
        raise BrowserSessionError("Browser login token contains invalid characters.") from None


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _dpapi(data: bytes, url: str, *, decrypt: bool) -> bytes:
    """Use DPAPI with current-user scope and server-specific additional entropy."""
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(value: bytes) -> tuple[DataBlob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(value)
        return DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    try:
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        protect = crypt.CryptProtectData
        protect.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
        protect.restype = wintypes.BOOL
        unprotect = crypt.CryptUnprotectData
        unprotect.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
        unprotect.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        source, source_buffer = blob(data)
        entropy, entropy_buffer = blob(b"openlist-codex-browser-session-v1\x00" + url.encode("utf-8"))
        output = DataBlob()
        if decrypt:
            succeeded = unprotect(ctypes.byref(source), None, ctypes.byref(entropy), None, None, _DPAPI_UI_FORBIDDEN, ctypes.byref(output))
        else:
            succeeded = protect(ctypes.byref(source), "OpenList Codex browser login", ctypes.byref(entropy), None, None, _DPAPI_UI_FORBIDDEN, ctypes.byref(output))
        # Keep source buffers alive until the native call completes.
        _ = source_buffer, entropy_buffer
        if not succeeded:
            raise BrowserSessionError("Cannot protect or unlock the browser login for this Windows user.")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))
    except (AttributeError, OSError):
        raise BrowserSessionError("Windows browser login protection is unavailable.") from None


def _atomic_write(path: Path, state: dict) -> None:
    raw = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > _MAX_FILE_BYTES:
        raise BrowserSessionError("Browser login state is too large.")
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            existing = path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None and (_is_link(existing) or not stat.S_ISREG(existing.st_mode)):
            raise BrowserSessionError("Browser login state must be a regular file.")
        fd, name = tempfile.mkstemp(prefix=".browser-session-", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as target:
            if os.name == "posix":
                os.fchmod(target.fileno(), 0o600)
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError:
        raise BrowserSessionError("Cannot safely save the browser login; check its path and permissions.") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def save_session(path: Path, url: str, token: str) -> None:
    """Save a token explicitly handed over by the linked OpenList page."""
    normalized = normalize_url(url)
    _validate_token(token)
    protection = "dpapi" if os.name == "nt" else "posix"
    stored = base64.b64encode(_dpapi(token.encode("utf-8"), normalized, decrypt=False)).decode("ascii") if os.name == "nt" else token
    _atomic_write(Path(path).expanduser(), {"version": 1, "url": normalized, "protection": protection, "token": stored})


def clear_session(path: Path, url: str) -> None:
    """Persist logout so later processes cannot reuse a previous login."""
    _atomic_write(Path(path).expanduser(), {"version": 1, "url": normalize_url(url), "protection": "dpapi" if os.name == "nt" else "posix", "token": ""})


def _read_state(path: Path) -> dict | None:
    try:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if _is_link(info):
            raise BrowserSessionError("Browser login state must be a regular file.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise BrowserSessionError("Browser login state must be a regular file.")
            if os.name == "posix" and (info.st_mode & 0o077 or info.st_uid != os.getuid()):
                raise BrowserSessionError("Browser login state must be owned by you and have permissions 0600.")
            raw = source.read(_MAX_FILE_BYTES + 1)
        if len(raw) > _MAX_FILE_BYTES:
            raise BrowserSessionError("Browser login state is too large.")
        state = json.loads(raw.decode("utf-8"))
        if not isinstance(state, dict):
            raise BrowserSessionError("Browser login state is invalid.")
        return state
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise BrowserSessionError("Cannot safely read the browser login state; reconnect from OpenList.") from None


def load_session(path: Path, expected_url: str | None = None) -> tuple[str, str] | None:
    """Return linked credentials only for the exact configured server/base path."""
    expected = normalize_url(expected_url) if expected_url is not None else None
    state = _read_state(Path(path).expanduser())
    if state is None:
        return None
    if type(state.get("version")) is not int or state["version"] != 1 or not isinstance(state.get("url"), str) or not isinstance(state.get("token"), str):
        raise BrowserSessionError("Browser login state is incomplete or unsupported; reconnect from OpenList.")
    normalized = normalize_url(state["url"])
    if expected is not None and expected != normalized:
        raise BrowserSessionError("Browser login belongs to a different OpenList server or base path; reconnect from the configured server.")
    protection = "dpapi" if os.name == "nt" else "posix"
    if state.get("protection") != protection:
        raise BrowserSessionError("Browser login protection does not match this operating system; reconnect from OpenList.")
    stored = state["token"]
    if not stored:
        return None
    if os.name == "nt":
        try:
            token = _dpapi(base64.b64decode(stored, validate=True), normalized, decrypt=True).decode("utf-8")
        except (binascii.Error, UnicodeError):
            raise BrowserSessionError("Browser login is damaged; reconnect from OpenList.") from None
    else:
        token = stored
    _validate_token(token)
    return normalized, token
