import hashlib
import json
import os
from dataclasses import replace
from urllib.parse import parse_qs

import httpx
import pytest

from openlist_codex.config import PluginError


def entry(name, *, is_dir=False, size=3, **extra):
    return {"name": name, "is_dir": is_dir, "size": size, "modified": "2026-01-01T00:00:00Z", **extra}


def api_response(data, *, code=200, message="success"):
    return httpx.Response(200, json={"code": code, "message": message, "data": data})


class AsyncChunks(httpx.AsyncByteStream):
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error


async def test_listing_auth_pagination_mount_and_safe_field_allowlist(make_client, settings):
    requests = []

    def handler(request):
        requests.append(request)
        return api_response({
            "content": [entry("report.txt", raw_url="https://private.example?sign=secret", sign="secret", token="private-token", provider_id="secret")],
            "total": 3,
            "raw_url": "secret",
        })

    client = make_client(handler, replace(settings, path_password="private-password"))
    listing = await client.list_files("reports", page=2, per_page=1)
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/fs/list"
    assert request.headers["Authorization"] == "test-secret"
    assert json.loads(request.content) == {"path": "/Quark/reports", "password": "private-password", "page": 2, "per_page": 1, "refresh": False}
    assert listing["has_more"] is True
    assert listing["entries"] == [{"name": "report.txt", "path": "reports/report.txt", "is_dir": False, "size": 3, "modified": "2026-01-01T00:00:00Z"}]
    assert "secret" not in json.dumps(listing)


async def test_null_content_is_a_valid_empty_directory(make_client):
    client = make_client(lambda request: api_response({"content": None, "total": 0}))
    assert (await client.list_files())["entries"] == []


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_http_api_failures_hide_response_bodies(make_client, status):
    client = make_client(lambda request: httpx.Response(status, text="token=test-secret&sign=private-signature"))
    with pytest.raises(PluginError) as error:
        await client.list_files()
    assert "test-secret" not in str(error.value)
    assert "private-signature" not in str(error.value)


@pytest.mark.parametrize("envelope", [[], {"code": 200, "data": None}, {"code": 200, "data": []}, {"code": "secret-token", "message": "secret-token"}, {"code": 403, "message": "secret-token"}])
async def test_malformed_or_failed_envelopes_are_safe_errors(make_client, envelope):
    client = make_client(lambda request: httpx.Response(200, json=envelope))
    with pytest.raises(PluginError) as error:
        await client.list_files()
    assert "secret-token" not in str(error.value)


async def test_non_json_api_response_is_reported_safely(make_client):
    client = make_client(lambda request: httpx.Response(200, content=b"<html>token=test-secret</html>"))
    with pytest.raises(PluginError, match="invalid JSON"):
        await client.list_files()


async def test_api_response_size_is_bounded(make_client):
    client = make_client(lambda request: httpx.Response(200, stream=AsyncChunks([b"x" * (4 * 1024 * 1024 + 1)])))
    with pytest.raises(PluginError, match="4 MiB"):
        await client.list_files()


async def test_connectivity_errors_do_not_echo_signed_urls(make_client):
    def handler(request):
        raise httpx.ConnectError("https://private.example?token=test-secret&sign=private", request=request)

    with pytest.raises(PluginError, match="Cannot reach OpenList") as error:
        await make_client(handler).list_files()
    assert "test-secret" not in str(error.value)
    assert "private.example" not in str(error.value)


async def test_missing_token_prevents_any_request(make_client, settings):
    def handler(request):
        pytest.fail("Unauthenticated operations must not contact OpenList")

    with pytest.raises(PluginError, match="OPENLIST_TOKEN_FILE"):
        await make_client(handler, replace(settings, token="")).list_files()


@pytest.mark.parametrize("data", [
    {"content": [], "total": -1},
    {"content": [], "total": True},
    {"content": {}, "total": 1},
    {"content": [], "total": 2},
    {"content": [entry("first"), entry("second")], "total": 2},
    {"content": [entry("../escape")], "total": 1},
    {"content": [entry("secret\\file")], "total": 1},
    {"content": [entry("bad", size=True)], "total": 1},
    {"content": [entry("bad", size=-1)], "total": 1},
    {"content": [entry("bad", is_dir="false")], "total": 1},
])
async def test_invalid_listings_are_rejected(make_client, data):
    client = make_client(lambda request: api_response(data))
    with pytest.raises(PluginError):
        await client.list_files(per_page=1)


@pytest.mark.parametrize("page,per_page", [(0, 100), (100001, 100), (1, 0), (1, 101)])
async def test_list_page_limits_are_enforced_before_network(make_client, page, per_page):
    def handler(request):
        pytest.fail("Invalid pagination must not contact OpenList")

    with pytest.raises(PluginError):
        await make_client(handler).list_files(page=page, per_page=per_page)


def tree_handler(tree, requests):
    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        names = tree[payload["path"]]
        offset = (payload["page"] - 1) * payload["per_page"]
        return api_response({"content": names[offset : offset + payload["per_page"]], "total": len(names)})

    return handler


async def test_search_matches_filenames_case_insensitively_and_walks_mount(make_client):
    requests = []
    tree = {
        "/Quark": [entry("folder", is_dir=True), entry("REPORT.txt"), entry("unrelated.txt")],
        "/Quark/folder": [entry("Report.pdf"), entry("do-not-match.txt", description="report")],
    }
    result = await make_client(tree_handler(tree, requests)).search("report")
    assert [item["path"] for item in result["matches"]] == ["REPORT.txt", "folder/Report.pdf"]
    assert result["scanned_entries"] == 5
    assert result["truncated"] is False
    assert {item["path"] for item in requests} == {"/Quark", "/Quark/folder"}


async def test_generic_root_search_spans_differently_named_mounts(make_client, settings):
    requests = []
    tree = {
        "/": [entry("团队盘", is_dir=True), entry("WebDAV", is_dir=True)],
        "/团队盘": [entry("report.txt")],
        "/WebDAV": [entry("report.pdf")],
    }
    result = await make_client(tree_handler(tree, requests), replace(settings, root="/")).search("report")
    assert {item["path"] for item in result["matches"]} == {"团队盘/report.txt", "WebDAV/report.pdf"}
    assert {request["path"] for request in requests} == {"/", "/团队盘", "/WebDAV"}
    assert result["truncated"] is False


async def test_nonrecursive_search_stays_in_selected_directory(make_client):
    requests = []
    tree = {"/Quark/folder": [entry("nested", is_dir=True), entry("report.txt")]}
    result = await make_client(tree_handler(tree, requests)).search("report", path="folder", recursive=False)
    assert [item["path"] for item in result["matches"]] == ["folder/report.txt"]
    assert len(requests) == 1
    assert result["truncated"] is False


async def test_search_keeps_page_size_constant_when_nearing_budget(make_client):
    requests = []
    tree = {"/Quark": [entry(f"file-{index:03}.txt") for index in range(205)]}
    result = await make_client(tree_handler(tree, requests)).search("file-140", max_entries=150)
    assert [item["path"] for item in result["matches"]] == ["file-140.txt"]
    assert result["scanned_entries"] == 150
    assert result["truncated"] is True
    assert [request["per_page"] for request in requests] == [100, 100]
    assert [request["page"] for request in requests] == [1, 2]


async def test_search_enforces_tiny_scan_budget_and_result_limit(make_client):
    requests = []
    tree = {"/Quark": [entry(f"report-{index}.txt") for index in range(20)]}
    client = make_client(tree_handler(tree, requests))
    result = await client.search("report", limit=2, max_entries=3)
    assert len(result["matches"]) == 2
    assert result["scanned_entries"] == 2
    assert result["truncated"] is True
    assert len(requests) == 1


async def test_search_caps_requests_independently_of_scan_budget(make_client):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return api_response({"content": [entry("next", is_dir=True)], "total": 1})

    result = await make_client(handler).search("absent", max_entries=10000)
    assert len(requests) == 100
    assert result["scanned_entries"] == 100
    assert result["truncated"] is True


@pytest.mark.parametrize("arguments", [{"query": " "}, {"query": "x" * 257}, {"query": "x", "limit": 0}, {"query": "x", "limit": 101}, {"query": "x", "max_entries": 0}, {"query": "x", "max_entries": 10001}, {"query": "x", "path": "../escape"}])
async def test_invalid_search_arguments_do_not_contact_server(make_client, arguments):
    def handler(request):
        pytest.fail("Invalid search must not contact OpenList")

    with pytest.raises(PluginError):
        await make_client(handler).search(**arguments)


def download_handler(info=None, chunks=None, headers=None, status=200, callback=None):
    metadata = entry("report.txt", raw_url="/p/Quark/report.txt?sign=private-signature&d=0")
    metadata.update(info or {})

    def handler(request):
        if callback:
            callback(request)
        if request.method == "POST":
            assert request.url.path == "/api/fs/get"
            return api_response(metadata)
        return httpx.Response(status, headers=headers, stream=AsyncChunks(chunks if chunks is not None else [b"abc"]))

    return handler


async def test_download_uses_same_origin_proxy_without_api_authorization(make_client, settings):
    requests = []
    client = make_client(download_handler(callback=requests.append))
    result = await client.download("folder/report.txt")
    assert len(requests) == 2
    assert requests[0].headers["Authorization"] == "test-secret"
    assert json.loads(requests[0].content)["path"] == "/Quark/folder/report.txt"
    assert requests[1].method == "GET"
    assert requests[1].url.path == "/p/Quark/report.txt"
    assert requests[1].url.host == "127.0.0.1"
    assert "authorization" not in requests[1].headers
    assert parse_qs(requests[1].url.query.decode()) == {"sign": ["private-signature"], "d": ["1"]}
    assert (settings.download_dir / "report.txt").read_bytes() == b"abc"
    assert result == {"saved_path": str(settings.download_dir / "report.txt"), "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
    assert "private-signature" not in json.dumps(result)
    assert list(settings.download_dir.glob("*.part")) == []


async def test_download_handles_server_url_path_prefix(make_client, settings):
    custom = replace(settings, url="https://openlist.example/app")

    def handler(request):
        if request.method == "POST":
            assert request.url.path == "/app/api/fs/get"
            return api_response(entry("report.txt", raw_url="https://openlist.example/app/p/Quark/report.txt?sign=private"))
        assert request.url.path == "/app/p/Quark/report.txt"
        assert "authorization" not in request.headers
        return httpx.Response(200, stream=AsyncChunks([b"abc"]))

    result = await make_client(handler, custom).download("report.txt")
    assert result["bytes"] == 3


@pytest.mark.parametrize("raw_url", ["https://external.example/file?sign=private", "http://127.0.0.1:9999/p/Quark/file", "/d/Quark/file", "/api/fs/list", "//external.example/p/file", "http://user:pass@127.0.0.1:5244/p/file", "/p/file#fragment", ""])
async def test_external_or_nonproxy_download_urls_are_rejected_before_get(make_client, raw_url):
    requests = []
    client = make_client(download_handler(info={"raw_url": raw_url}, callback=requests.append))
    with pytest.raises(PluginError):
        await client.download("report.txt")
    assert len(requests) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308])
async def test_download_does_not_follow_redirects(make_client, settings, status):
    requests = []
    client = make_client(download_handler(status=status, headers={"Location": "https://external.example?sign=private"}, callback=requests.append))
    with pytest.raises(PluginError, match="redirected") as error:
        await client.download("report.txt")
    assert len(requests) == 2
    assert "external.example" not in str(error.value)
    assert list(settings.download_dir.iterdir()) == []


@pytest.mark.parametrize("info", [{"is_dir": True}, {"size": True}, {"size": -1}, {"name": "../escape"}, {"name": "CON.txt"}, {"name": 123}])
async def test_invalid_download_metadata_never_reaches_download_get(make_client, info):
    requests = []
    with pytest.raises(PluginError):
        await make_client(download_handler(info=info, callback=requests.append)).download("report.txt")
    assert len(requests) == 1


async def test_metadata_size_limit_is_checked_before_download(make_client, settings):
    requests = []
    client = make_client(download_handler(info={"size": 11}, callback=requests.append), replace(settings, max_download_bytes=10))
    with pytest.raises(PluginError, match="exceeds"):
        await client.download("report.txt")
    assert len(requests) == 1
    assert not settings.download_dir.exists()


@pytest.mark.parametrize("chunks,headers,message", [
    ([b"abcd"], {}, "exceeded"),
    ([b"ab"], {}, "ended before"),
    ([b"abc"], {"Content-Length": "4"}, "length differs"),
    ([b"abc"], {"Content-Length": "invalid"}, "invalid Content-Length"),
    ([b"abc"], {"Content-Encoding": "gzip"}, "content encoding"),
])
async def test_download_length_and_encoding_failures_remove_partial_files(make_client, settings, chunks, headers, message):
    with pytest.raises(PluginError, match=message):
        await make_client(download_handler(chunks=chunks, headers=headers)).download("report.txt")
    assert list(settings.download_dir.iterdir()) == []


async def test_stream_failure_is_safe_and_removes_partial_file(make_client, settings):
    def handler(request):
        if request.method == "POST":
            return api_response(entry("report.txt", raw_url="/p/report.txt?sign=private"))
        return httpx.Response(200, stream=AsyncChunks([b"a"], httpx.ReadError("https://private.example?sign=private")))

    with pytest.raises(PluginError, match="Download failed") as error:
        await make_client(handler).download("report.txt")
    assert "private.example" not in str(error.value)
    assert list(settings.download_dir.iterdir()) == []


async def test_existing_destination_is_never_overwritten(make_client, settings):
    settings.download_dir.mkdir()
    destination = settings.download_dir / "report.txt"
    destination.write_bytes(b"existing data")
    requests = []
    with pytest.raises(PluginError, match="already exists"):
        await make_client(download_handler(callback=requests.append)).download("report.txt")
    assert len(requests) == 1
    assert destination.read_bytes() == b"existing data"


async def test_atomic_publication_preserves_destination_created_during_transfer(make_client, settings, monkeypatch):
    destination = settings.download_dir / "report.txt"
    real_link = os.link

    def race_link(source, target):
        destination.write_bytes(b"concurrent writer")
        return real_link(source, target)

    monkeypatch.setattr("openlist_codex.client.os.link", race_link)
    with pytest.raises(PluginError, match="already exists"):
        await make_client(download_handler()).download("report.txt")
    assert destination.read_bytes() == b"concurrent writer"
    assert set(settings.download_dir.iterdir()) == {destination}


@pytest.mark.skipif(os.name != "posix", reason="POSIX symbolic links")
async def test_destination_symlink_is_never_followed(make_client, settings, tmp_path):
    settings.download_dir.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"original")
    (settings.download_dir / "report.txt").symlink_to(outside)
    with pytest.raises(PluginError, match="already exists"):
        await make_client(download_handler()).download("report.txt")
    assert outside.read_bytes() == b"original"


@pytest.mark.skipif(os.name != "posix", reason="POSIX symbolic links")
async def test_download_root_symlink_is_rejected(make_client, settings, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    settings.download_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PluginError, match="not a symlink"):
        await make_client(download_handler()).download("report.txt")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("path,filename", [("../private", None), ("", None), ("report.txt", "../escape"), ("report.txt", "CON")])
async def test_unsafe_download_arguments_are_rejected_before_network(make_client, path, filename):
    def handler(request):
        pytest.fail("Unsafe download paths must not contact OpenList")

    with pytest.raises(PluginError):
        await make_client(handler).download(path, filename)


async def test_custom_filename_and_zero_byte_download(make_client, settings):
    client = make_client(download_handler(info={"size": 0}, chunks=[], headers={"Content-Length": "0"}))
    result = await client.download("report.txt", filename="我的报告.txt")
    assert result["bytes"] == 0
    assert (settings.download_dir / "我的报告.txt").read_bytes() == b""
