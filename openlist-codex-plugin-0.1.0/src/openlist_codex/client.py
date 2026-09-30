"""Use OpenList's HTTP API; drive sessions stay in the OpenList server."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections import deque
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from .config import PluginError, Settings, validate_filename, validate_relative_path


class OpenListClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=10),
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "openlist-codex/0.1.0", "Accept-Encoding": "identity"},
        )
        self._download_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.http.aclose()

    async def _api(self, endpoint: str, payload: dict) -> dict:
        if not self.settings.token:
            raise PluginError("Configure OPENLIST_TOKEN_FILE with a dedicated read-only OpenList user's token.")
        try:
            async with self.http.stream(
                "POST", self.settings.url + "/api/fs/" + endpoint,
                headers={"Authorization": self.settings.token}, json=payload,
            ) as response:
                if response.status_code in (401, 403):
                    raise PluginError("OpenList denied access; check your token and read permissions.")
                if response.status_code != 200:
                    raise PluginError(f"OpenList HTTP request failed (status {response.status_code}); check the server URL.")
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 4 * 1024 * 1024:
                        raise PluginError("OpenList API response exceeds 4 MiB; use a smaller page.")
                    chunks.append(chunk)
                envelope = json.loads(b"".join(chunks))
        except (httpx.HTTPError, OSError):
            # HTTP exceptions contain URLs, which can contain a download signature.
            raise PluginError("Cannot reach OpenList; check connectivity, HTTPS certificates and server availability.") from None
        except (ValueError, UnicodeError):
            raise PluginError("OpenList returned an invalid JSON response.") from None
        if not isinstance(envelope, dict):
            raise PluginError("OpenList returned an invalid API envelope.")
        code = envelope.get("code")
        if code in (401, 403):
            raise PluginError("OpenList denied access; check your token, mount password and read permissions.")
        if code != 200:
            # Do not expose upstream message/traceback: it can contain tokens and raw URLs.
            safe_code = str(code) if isinstance(code, int) else "unknown"
            raise PluginError(f"OpenList operation failed (code {safe_code}); check the mount and server logs locally.")
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise PluginError("OpenList response is missing its data object.")
        return data

    def _payload(self, relative: str) -> dict:
        return {"path": self.settings.remote_path(relative), "password": self.settings.path_password}

    @staticmethod
    def _entry(raw: dict, parent: str) -> dict:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not isinstance(raw.get("is_dir"), bool):
            raise PluginError("OpenList returned an invalid file entry.")
        name = raw["name"]
        if not name or "/" in name or "\\" in name:
            raise PluginError("OpenList returned a filename with invalid path separators.")
        relative = validate_relative_path(f"{parent}/{name}" if parent else name)
        size = raw.get("size", 0)
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise PluginError("OpenList returned an invalid file size.")
        return {
            "name": name,
            "path": relative,
            "is_dir": raw["is_dir"],
            "size": size,
            "modified": raw.get("modified") if isinstance(raw.get("modified"), str) else None,
        }

    async def list_files(self, path: str = "", page: int = 1, per_page: int = 100) -> dict:
        relative = validate_relative_path(path)
        if isinstance(page, bool) or isinstance(per_page, bool) or not 1 <= page <= 100000 or not 1 <= per_page <= 100:
            raise PluginError("page must be 1–100000 and per_page must be 1–100.")
        payload = {**self._payload(relative), "page": page, "per_page": per_page, "refresh": False}
        data = await self._api("list", payload)
        content = data.get("content")
        # OpenList's empty directories can encode a nil slice as JSON null.
        if content is None:
            content = []
        total = data.get("total")
        if not isinstance(content, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0 or len(content) > per_page:
            raise PluginError("OpenList returned an invalid directory listing.")
        entries = [self._entry(item, relative) for item in content]
        more = page * per_page < total
        if more and not entries:
            raise PluginError("OpenList returned an empty page before the end of a directory.")
        return {"path": relative, "entries": entries, "total": total, "page": page, "per_page": per_page, "has_more": more}

    async def search(self, query: str, path: str = "", recursive: bool = True, limit: int = 100, max_entries: int = 2000) -> dict:
        """Bounded filename walk: no search-index setup is required in OpenList."""
        relative = validate_relative_path(path)
        if not query.strip() or len(query) > 256:
            raise PluginError("query must contain 1–256 characters.")
        if not 1 <= limit <= 100 or not 1 <= max_entries <= 10000:
            raise PluginError("limit must be 1–100 and max_entries must be 1–10000.")
        pending = deque([(relative, 1)])
        seen = {relative}
        matches: list[dict] = []
        scanned = requests = 0
        needle = query.casefold()
        while pending and scanned < max_entries and requests < 100 and len(matches) < limit:
            parent, page = pending.popleft()
            listing = await self.list_files(parent, page, 100)
            requests += 1
            # A constant page size keeps OpenList's page offset stable near the budget.
            for entry in listing["entries"]:
                if scanned >= max_entries:
                    break
                scanned += 1
                if needle in entry["name"].casefold():
                    matches.append(entry)
                if recursive and entry["is_dir"] and entry["path"] not in seen:
                    seen.add(entry["path"])
                    pending.append((entry["path"], 1))
                if len(matches) >= limit:
                    break
            if listing["has_more"]:
                pending.appendleft((parent, page + 1))
            incomplete_page = scanned >= max_entries or len(matches) >= limit
            if incomplete_page:
                return {"query": query, "path": relative, "matches": matches, "scanned_entries": scanned, "truncated": True}
        return {"query": query, "path": relative, "matches": matches, "scanned_entries": scanned, "truncated": bool(pending)}

    def _proxy_url(self, raw_url: str) -> str:
        if not isinstance(raw_url, str) or not raw_url:
            raise PluginError("OpenList did not return a download URL; enable Web proxy for this mount.")
        try:
            absolute = urljoin(self.settings.url + "/", raw_url)
            parsed, base = urlsplit(absolute), urlsplit(self.settings.url)
            def origin(value):
                return (value.scheme, value.hostname, value.port or (443 if value.scheme == "https" else 80))
            if origin(parsed) != origin(base) or parsed.username or parsed.password or parsed.fragment:
                raise PluginError("Download must use this OpenList server's proxy; enable Web proxy and configure its site URL correctly.")
            prefix = base.path.rstrip("/") + "/p/"
            if not parsed.path.startswith(prefix):
                raise PluginError("OpenList download URL is not a proxy URL; enable Web proxy for this mount.")
            query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "d"]
            query.append(("d", "1"))
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
        except ValueError:
            raise PluginError("OpenList returned an invalid proxy URL.") from None

    async def download(self, path: str, filename: str | None = None) -> dict:
        relative = validate_relative_path(path)
        if not relative:
            raise PluginError("Choose a file path relative to the configured mount.")
        if filename is not None:
            validate_filename(filename)
        async with self._download_lock:
            info = await self._api("get", self._payload(relative))
            if info.get("is_dir") is not False:
                raise PluginError("Only files can be downloaded.")
            expected = info.get("size")
            if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
                raise PluginError("OpenList returned an invalid file size.")
            if expected > self.settings.max_download_bytes:
                raise PluginError("File exceeds OPENLIST_MAX_DOWNLOAD_BYTES.")
            name = validate_filename(filename if filename is not None else info.get("name", ""))
            url = self._proxy_url(info.get("raw_url", ""))
            return await self._save_download(url, name, expected)

    async def _save_download(self, url: str, name: str, expected: int) -> dict:
        root = self.settings.download_dir
        temp_path: Path | None = None
        try:
            root.mkdir(parents=True, exist_ok=True)
            if root.is_symlink() or not root.is_dir():
                raise PluginError("Download directory must be a real directory, not a symlink.")
            destination = root / name
            if os.path.lexists(destination):
                raise PluginError("Destination already exists; choose a different filename.")
            digest = hashlib.sha256()
            size = 0
            # Authorization is deliberately absent on the /p download request.
            async with self.http.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    raise PluginError("OpenList redirected the download; disable its external download proxy and enable Web proxy.")
                if response.status_code != 200:
                    raise PluginError(f"OpenList download failed (HTTP {response.status_code}).")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise PluginError("Unexpected download content encoding; configure the proxy to return identity encoding.")
                length = response.headers.get("content-length")
                if length is not None:
                    try:
                        length_int = int(length)
                    except ValueError:
                        raise PluginError("OpenList returned an invalid Content-Length.") from None
                    if length_int != expected:
                        raise PluginError("Download length differs from OpenList's file metadata; retry after refreshing the listing.")
                with tempfile.NamedTemporaryFile(prefix=".openlist-", suffix=".part", dir=root, delete=False) as target:
                    temp_path = Path(target.name)
                    async for chunk in response.aiter_raw():
                        size += len(chunk)
                        if size > self.settings.max_download_bytes or size > expected:
                            raise PluginError("Download exceeded its allowed size.")
                        target.write(chunk)
                        digest.update(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                if size != expected:
                    raise PluginError("Download ended before the expected number of bytes arrived.")
                # Link publishes a complete file and fails atomically if another file won the name.
                os.link(temp_path, destination)
            return {"saved_path": str(destination), "bytes": size, "sha256": digest.hexdigest()}
        except FileExistsError:
            raise PluginError("Destination already exists; choose a different filename.") from None
        except (httpx.HTTPError, OSError):
            raise PluginError("Download failed; check OpenList connectivity, disk space and directory permissions.") from None
        finally:
            if temp_path is not None:
                with suppress(OSError):
                    temp_path.unlink()
